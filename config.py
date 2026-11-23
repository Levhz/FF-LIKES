"""Central config. Sab .env se aata hai."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR") or (BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "fflike.db"

def _ints(raw: str):
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GUILD_ID = int(os.getenv("GUILD_ID") or 0)
ALLOWED_CHANNEL_IDS = _ints(os.getenv("ALLOWED_CHANNEL_IDS", ""))
ADMIN_IDS = _ints(os.getenv("ADMIN_IDS", ""))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip() or secrets.token_urlsafe(24)
API_KEY = os.getenv("API_KEY", "").strip() or secrets.token_urlsafe(24)

DEFAULT_REGION = os.getenv("DEFAULT_REGION", "IND").upper()
DAY_TZ = os.getenv("DAY_TZ", "Asia/Kolkata")

# economics
COST_PER_CMD = int(os.getenv("COST_PER_CMD", "10"))
COST_PER_LIKE = int(os.getenv("COST_PER_LIKE", "0"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "100"))
MAX_AMOUNT = int(os.getenv("MAX_AMOUNT", "100"))
WELCOME_CREDITS = int(os.getenv("WELCOME_CREDITS", "0"))

# pool
POOL_TARGET = int(os.getenv("POOL_TARGET", "8"))
POOL_MIN = int(os.getenv("POOL_MIN", "2"))
POOL_CREATE_CONCURRENCY = int(os.getenv("POOL_CREATE_CONCURRENCY", "3"))
ACCOUNT_DAILY_CAP = int(os.getenv("ACCOUNT_DAILY_CAP", "100"))
ACCOUNT_MAX_FAILS = int(os.getenv("ACCOUNT_MAX_FAILS", "3"))
LIKE_GAP = float(os.getenv("LIKE_GAP", "0.35"))
CMD_COOLDOWN = float(os.getenv("CMD_COOLDOWN", "5"))
