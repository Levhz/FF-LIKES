"""Guest account pool — zaroorat par auto generate karta hai."""
import asyncio
import json

import ffapi
import config
import db
from utils import today_str, now_iso

ffapi.QUIET = True


class LikeError(Exception):
    pass


class Pool:
    def __init__(self):
        self._sem = asyncio.Semaphore(config.POOL_CREATE_CONCURRENCY)
        self._task = None
        self._creating = 0

    # ---------------------------------------------------------- lifecycle
    async def start(self):
        await self.warm(config.POOL_MIN)
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while True:
            try:
                await asyncio.sleep(45)
                await self._reap()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

    async def _reap(self):
        day = today_str()
        for row in db.guest_list(400):
            if row["day"] and row["day"] != day and row["likes_today"]:
                db.set_guest(row["id"], likes_today=0, day=day)
            if row["status"] == "busy":
                db.set_guest(row["id"], status="ready")  # stuck claims release
        await self.warm(config.POOL_TARGET)

    async def warm(self, target: int):
        have = db.ready_count(config.DEFAULT_REGION, config.ACCOUNT_DAILY_CAP, today_str())
        deficit = target - have - self._creating
        for _ in range(max(0, deficit)):
            asyncio.create_task(self._create_safe(config.DEFAULT_REGION))

    # ---------------------------------------------------------- creation
    async def _create_safe(self, region: str):
        self._creating += 1
        try:
            await self._create(region)
        except Exception:
            pass
        finally:
            self._creating -= 1

    async def _create(self, region: str):
        async with self._sem:
            uid, password, device = await asyncio.to_thread(ffapi.guest_register, region)
            gid = db.add_guest(uid, password, json.dumps(device), region)
            acc = {"uid": uid, "password": password, "device": device,
                   "region": region, "name": "Guest"}
            try:
                res = await asyncio.to_thread(ffapi.activate, acc)
            except Exception:
                db.set_guest(gid, status="dead", fails=99)
                raise
            db.set_guest(gid, status="ready", jwt=res["jwt"],
                         account_id=str(res.get("account_id") or ""))
            return gid

    async def refresh(self, row: dict) -> dict:
        acc = {"uid": row["uid"], "password": row["password"],
               "device": json.loads(row["device"]) if row["device"] else None,
               "region": row["region"], "name": "Guest",
               "account_id": row["account_id"]}
        res = await asyncio.to_thread(ffapi.activate, acc)
        db.set_guest(row["id"], status="ready", jwt=res["jwt"], fails=0,
                     account_id=str(res.get("account_id") or row["account_id"] or ""))
        row = db.get_guest(row["id"])
        return row

    async def mark_failed(self, row: dict):
        fails = (row["fails"] or 0) + 1
        status = "dead" if fails >= config.ACCOUNT_MAX_FAILS else "ready"
        db.set_guest(row["id"], status=status, fails=fails)
        if status == "dead":
            asyncio.create_task(self._create_safe(row["region"]))

    # ---------------------------------------------------------- acquire
    async def acquire(self, region: str) -> dict:
        day = today_str()
        row = db.claim_guest(region, config.ACCOUNT_DAILY_CAP, day)
        if row:
            return row
        # on-demand generation — user ko wait karana padega
        gid = await self._create(region)
        row = db.get_guest(gid)
        db.set_guest(gid, status="busy")
        row["status"] = "busy"
        return row

    def release(self, row: dict, ok: int):
        db.set_guest(row["id"], status="ready", last_used=now_iso())
        if ok:
            db.bump_guest_likes(row["id"], ok, today_str())

    # ---------------------------------------------------------- like
    async def like_many(self, target: str, amount: int, region: str) -> dict:
        row = await self.acquire(region)
        ok = 0
        refreshed = False
        try:
            before = await asyncio.to_thread(ffapi.profile, row["jwt"], region, target)
            if not before:
                row = await self.refresh(row)
                before = await asyncio.to_thread(ffapi.profile, row["jwt"], region, target)
            if not before:
                raise LikeError("UID us server par nahi mila")

            for _ in range(amount):
                r = await asyncio.to_thread(ffapi.send_like, row["jwt"], region, target)
                code = getattr(r, "status_code", None)
                if code in (200, 201):
                    ok += 1
                    await asyncio.sleep(config.LIKE_GAP)
                elif code in (401, 403) and not refreshed:
                    row = await self.refresh(row)
                    refreshed = True
                else:
                    await asyncio.sleep(0.5)

            after = await asyncio.to_thread(ffapi.profile, row["jwt"], region, target) or {}
            return {"ok": ok, "guest": row["uid"], "nickname": before.get("nickname"),
                    "before": before.get("likes"), "after": after.get("likes")}
        except Exception:
            await self.mark_failed(row)
            raise
        finally:
            self.release(row, ok)


pool = Pool()
