import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import ffapi
from likesvc import process_like, quota
from pool import pool, LikeError
from utils import clean_uid

ffapi.QUIET = True

REGIONS = {"ind", "id", "sg", "my", "ph", "th", "vn", "bd", "pk", "tw",
           "cis", "ru", "sac", "br", "me", "us"}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=("!", "/"), intents=intents, help_command=None)


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def channel_ok(channel_id: int) -> bool:
    return not config.ALLOWED_CHANNEL_IDS or channel_id in config.ALLOWED_CHANNEL_IDS


async def _like_flow(user, region: str, uid: str, amount: int):
    try:
        res = await process_like(user.id, region, uid, amount)
    except LikeError as e:
        return False, f"{e}"
    q = quota(user.id)
    txt = (f"**{res['nickname'] or uid}** ko **{res['sent']}** likes bheje\n"
           f"Likes: {res['before']} → {res['after']}\n"
           f"Cost: {res['cost']} credits | Balance: {res['credits']}\n"
           f"Aaj bacha: {q['remaining']}/{q['limit']} (reset {q['reset_in']})")
    return True, txt


@bot.event
async def on_ready():
    print(f"logged in as {bot.user} ({bot.user.id})")
    try:
        if config.GUILD_ID:
            bot.tree.copy_global_to(guild=discord.Object(id=config.GUILD_ID))
            await bot.tree.sync(guild=discord.Object(id=config.GUILD_ID))
        else:
            await bot.tree.sync()
    except Exception as e:
        print("sync failed:", e)


# ------------------------------------------------------------------ user cmds
@bot.command(name="like", aliases=["l"])
@commands.cooldown(1, config.CMD_COOLDOWN, commands.BucketType.user)
async def like_cmd(ctx, *args):
    if not channel_ok(ctx.channel.id) and not is_admin(ctx.author.id):
        return await ctx.reply(f"<#{list(config.ALLOWED_CHANNEL_IDS)[0]}> me use kar.")
    args = list(args)
    region = config.DEFAULT_REGION
    if args and args[0].lower() in REGIONS:
        region = args.pop(0).upper()
    if not args:
        return await ctx.reply("Use: `!like ind <uid> [amount]`")
    uid = clean_uid(args.pop(0))
    if not uid:
        return await ctx.reply("Invalid UID.")
    try:
        amount = int(args.pop(0)) if args else 1
    except ValueError:
        return await ctx.reply("Amount number hona chahiye.")
    ok, msg = await _like_flow(ctx.author, region, uid, amount)
    await ctx.reply(("✅ " if ok else "❌ ") + msg)


@bot.tree.command(name="like", description="Free Fire profile par likes bhejo")
@app_commands.describe(uid="Free Fire UID", amount="kitne likes", region="region code")
async def like_slash(inter: discord.Interaction, uid: str, amount: int = 1,
                     region: str = config.DEFAULT_REGION):
    if not channel_ok(inter.channel_id) and not is_admin(inter.user.id):
        return await inter.response.send_message("Is channel me allowed nahi.", ephemeral=True)
    await inter.response.defer()
    ok, msg = await _like_flow(inter.user, region.upper(), uid, amount)
    await inter.followup.send(("✅ " if ok else "❌ ") + msg)


@bot.command(name="balance", aliases=["bal", "credits"])
async def balance(ctx):
    u = db.ensure_user(ctx.author.id)
    q = quota(ctx.author.id)
    await ctx.reply(f"Credits: **{u['credits']}** | Aaj: {q['used']}/{q['limit']} "
                    f"(reset {q['reset_in']}) | Total likes: {u['total_likes']}")


@bot.command(name="profile")
async def profile_cmd(ctx, uid: str):
    uid = clean_uid(uid)
    if not uid:
        return await ctx.reply("Invalid UID.")
    row = db.claim_guest(config.DEFAULT_REGION, 10**6, "")
    if not row:
        return await ctx.reply("Koi account available nahi, dobara try kar.")
    try:
        p = await asyncio.to_thread(ffapi.profile, row["jwt"], config.DEFAULT_REGION, uid)
    finally:
        db.set_guest(row["id"], status="ready")
    if not p:
        return await ctx.reply("Profile nahi mili.")
    await ctx.reply(f"**{p['nickname']}** | Lv {p['level']} | Likes {p['likes']}")


@bot.command(name="help")
async def help_cmd(ctx):
    e = discord.Embed(title="FF Like Bot", color=0x00c2ff)
    e.add_field(name="Commands", value=(
        "`!like ind <uid> [amount]` — likes bhejo\n"
        "`!balance` — credits + daily quota\n"
        "`!profile <uid>` — profile dekho\n"
        "`!help` — ye list"), inline=False)
    if is_admin(ctx.author.id):
        e.add_field(name="Admin", value=(
            "`!addcredits @user <amt>` / `!removecredits` / `!setcredits`\n"
            "`!ban @user` / `!unban @user`\n"
            "`!apion` / `!apioff` / `!maintenance <msg>`\n"
            "`!refill <n>` / `!pool` / `!stats`"), inline=False)
    await ctx.reply(embed=e)


# ------------------------------------------------------------------ admin cmds
def _target_id(raw: str):
    if raw.startswith("<@") and raw.endswith(">"):
        raw = raw.strip("<@!>")
    return int(raw) if raw.isdigit() else None


@bot.command(name="addcredits", aliases=["give"])
async def addcredits(ctx, member: str, amount: int):
    if not is_admin(ctx.author.id):
        return
    tid = _target_id(member)
    if not tid:
        return await ctx.reply("User mention/ID do.")
    await ctx.reply(f"<@{tid}> ko {amount} credits. Balance: **{db.add_credits(tid, amount)}**")


@bot.command(name="removecredits", aliases=["take"])
async def removecredits(ctx, member: str, amount: int):
    if not is_admin(ctx.author.id):
        return
    tid = _target_id(member)
    if not tid:
        return await ctx.reply("User mention/ID do.")
    await ctx.reply(f"<@{tid}> se {amount} credits. Balance: **{db.add_credits(tid, -amount)}**")


@bot.command(name="setcredits")
async def setcredits(ctx, member: str, amount: int):
    if not is_admin(ctx.author.id):
        return
    tid = _target_id(member)
    if not tid:
        return await ctx.reply("User mention/ID do.")
    await ctx.reply(f"<@{tid}> ka balance set: **{db.set_credits(tid, amount)}**")


@bot.command(name="ban")
async def ban(ctx, member: str):
    if not is_admin(ctx.author.id):
        return
    tid = _target_id(member)
    if tid:
        db.set_banned(tid, True)
        await ctx.reply(f"<@{tid}> banned.")


@bot.command(name="unban")
async def unban(ctx, member: str):
    if not is_admin(ctx.author.id):
        return
    tid = _target_id(member)
    if tid:
        db.set_banned(tid, False)
        await ctx.reply(f"<@{tid}> unbanned.")


@bot.command(name="apion")
async def apion(ctx):
    if not is_admin(ctx.author.id):
        return
    db.set_setting("api_enabled", "1")
    await ctx.reply("API ON.")


@bot.command(name="apioff")
async def apioff(ctx):
    if not is_admin(ctx.author.id):
        return
    db.set_setting("api_enabled", "0")
    await ctx.reply("API OFF.")


@bot.command(name="maintenance")
async def maintenance(ctx, *, msg: str = ""):
    if not is_admin(ctx.author.id):
        return
    db.set_setting("maintenance_msg", msg)
    await ctx.reply(f"Maintenance msg set: `{msg}`")


@bot.command(name="refill")
async def refill(ctx, count: int = 3):
    if not is_admin(ctx.author.id):
        return
    await pool.warm(min(20, max(1, count)))
    await ctx.reply(f"{count} account generate queue me.")


@bot.command(name="pool")
async def pool_cmd(ctx):
    if not is_admin(ctx.author.id):
        return
    c = db.pool_counts()
    await ctx.reply(f"ready={c.get('ready',0)} busy={c.get('busy',0)} "
                    f"new={c.get('new',0)} dead={c.get('dead',0)}")


@bot.command(name="stats")
async def stats_cmd(ctx):
    if not is_admin(ctx.author.id):
        return
    s = db.stats()
    await ctx.reply(f"users={s['users']} total_likes={s['total_likes']} today={s['today_likes']}")


@like_cmd.error
async def like_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"Ruko {error.retry_after:.1f}s")


async def run_bot():
    async with bot:
        await bot.start(config.BOT_TOKEN)
