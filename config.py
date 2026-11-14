import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "https://vgek43.ru/")
DB_PATH = os.getenv("DB_PATH", "schedule.db")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "1800"))  # секунд между проверками сайта
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# --- бэкапы базы ---
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))          # сколько копий хранить на сервере
BACKUP_TIME = os.getenv("BACKUP_TIME", "03:00")           # во сколько делать ежедневный бэкап

# --- прочее ---
DATA_DIR = os.getenv("DATA_DIR", "data")                   # фото на фоне и др. файлы пользователей
ALERT_AFTER = int(os.getenv("ALERT_AFTER", "3"))          # после скольких неудачных проверок сайта писать админу
REF_BONUS_DAYS = int(os.getenv("REF_BONUS_DAYS", "7"))    # дней Premium за приглашённого друга

# --- 💳 оплата картой и СБП через ЮKassa (Telegram Payments) ---
# Токен провайдера: @BotFather → бот → Payments → ЮKassa. Пусто — оплата только звёздами.
YOOKASSA_TOKEN = os.getenv("YOOKASSA_PROVIDER_TOKEN", "").strip()
# Чек по 54-ФЗ: 1 — передавать в ЮKassa данные чека (нужно ИП/ООО с онлайн-кассой ЮKassa).
# Самозанятым с «Чеками от ЮKassa» оставить 0 — чек в «Мой налог» сформируется сам.
YOOKASSA_RECEIPT = os.getenv("YOOKASSA_RECEIPT", "0") == "1"
YOOKASSA_VAT_CODE = int(os.getenv("YOOKASSA_VAT_CODE", "1"))  # 1 — без НДС

# --- 📲 виджет на рабочий стол телефона (веб-сервер для картинок) ---
# PUBLIC_URL — внешний адрес бота с портом, например http://my-server.example.com:8080
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEB_PORT = int(os.getenv("WEB_PORT") or os.getenv("SERVER_PORT") or "0")  # 0 — веб-сервер выключен
