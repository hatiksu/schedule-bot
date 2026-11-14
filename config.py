import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "https://vgek43.ru/")
DB_PATH = os.getenv("DB_PATH", "schedule.db")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "1800"))
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))
BACKUP_TIME = os.getenv("BACKUP_TIME", "03:00")

DATA_DIR = os.getenv("DATA_DIR", "data")
ALERT_AFTER = int(os.getenv("ALERT_AFTER", "3"))
REF_BONUS_DAYS = int(os.getenv("REF_BONUS_DAYS", "7"))

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "").strip()
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "").strip()
YOOKASSA_RECEIPT = os.getenv("YOOKASSA_RECEIPT", "0") == "1"
YOOKASSA_VAT_CODE = int(os.getenv("YOOKASSA_VAT_CODE", "1"))

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEB_PORT = int(os.getenv("WEB_PORT") or os.getenv("SERVER_PORT") or "0")
