# FF Like API

Free Fire guest account generator + like API + Discord bot + web panel.

## Features
- Guest account auto-generate on demand, uid:pass DB me save hote hain
- `!like ind <uid> <amt>` / `/like` slash command
- Credits (per command deduct), daily 100 likes/user cap
- Admin credits/ban/pool control
- Web panel se API on/off, pricing, pool, logs
- Channel-locked commands, admin bypass

## Local setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # values bhar
python run.py
```
Panel: http://localhost:8000 — `.env` ka `ADMIN_TOKEN` password hai.

## Generator akela chalana
```bash
python ffapi.py -n 10
```

## GitHub
```bash
git init && git add . && git commit -m "init"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

## Render deploy
1. Render → New → Blueprint → repo select.
2. `ff-like-secrets` env group banao: `BOT_TOKEN`, `ADMIN_IDS`, `ALLOWED_CHANNEL_IDS`, `ADMIN_TOKEN`, `API_KEY`.
3. Disk `/data` (Starter plan) — free plan par restart pe DB reset hoga.
4. Deploy ke baad `/` panel, bot same process me chalega.
5. Free plan 15 min idle pe sleep karta hai — UptimeRobot se `/health` ping kar.

## Bot invite
OAuth2 URL → scopes `bot applications.commands`, permissions: Send Messages, Embed Links, Read Message History.

## API (X-API-Key header)
```
GET  /api/status
GET  /api/profile/<uid>?region=ind
POST /api/like  {"uid":"123","amount":5,"region":"ind","discord_id":111}
```

## Commands
| cmd | kaam |
|---|---|
| `!like ind <uid> [amt]` | likes |
| `!balance` / `!profile <uid>` | info |
| `!addcredits @u <n>` `!removecredits` `!setcredits` | admin credits |
| `!ban` / `!unban` | access |
| `!apion` / `!apioff` / `!maintenance <msg>` | toggle |
| `!refill <n>` / `!pool` / `!stats` | pool |
