"""⭐ Premium: товары, цены в Telegram Stars и рублях (ЮKassa), темы, проверки доступа."""
from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

FOREVER = "9999-12-31 23:59:59"
TRIAL_DAYS = 3
FREE_NOTES = 5  # без Premium — столько активных заметок (на сегодня и вперёд)
FAV_LIMIT = 10

# id: (название, звёзды, дней; None = навсегда)
PLANS = {
    "month": ("⭐ Premium на месяц", 30, 30),
    "year": ("⭐ Premium на год", 200, 365),
    "forever": ("👑 Premium навсегда", 350, None),
}
DONATES = [10, 25, 50, 100, 250, 500]

# --- 💳 цены в рублях (оплата картой / СБП через ЮKassa) ---
STARS = "XTR"
RUB = "RUB"
RUB_PLANS = {"month": 79, "year": 490, "forever": 890}
RUB_THEMES = {"neon": 39, "pastel": 39, "anime": 49, "minimal": 29, "notebook": 39, "newyear": 29, "halloween": 29}
RUB_DONATES = [50, 100, 200, 500, 1000]

# id: (название, эмодзи, цена отдельно; 0 — бесплатно для всех)
THEMES = {
    "classic": ("Классика", "🌌", 0),
    "neon": ("Неон", "💜", 20),
    "pastel": ("Пастель", "🍬", 20),
    "anime": ("Сакура", "🌸", 25),
    "minimal": ("Минимализм", "⚪", 15),
    "notebook": ("Тетрадка", "📓", 20),
    "newyear": ("Новогодняя", "🎄", 15),
    "halloween": ("Хэллоуин", "🎃", 15),
}
ACCENTS = {
    "blue": ("Синий", "#638CFF"), "violet": ("Фиолетовый", "#A86EFF"), "pink": ("Розовый", "#FF5FA2"),
    "red": ("Красный", "#FF5A5A"), "orange": ("Оранжевый", "#FF9A3C"), "yellow": ("Жёлтый", "#FFD23F"),
    "green": ("Зелёный", "#3DDC84"), "cyan": ("Бирюзовый", "#38D9F5"),
}
BACKGROUNDS = {
    "black": ("Чёрный", "#000000"), "graphite": ("Графит", "#16181D"), "navy": ("Ночной синий", "#0E1A33"),
    "wine": ("Винный", "#2A0E1A"), "forest": ("Лесной", "#0D2318"), "white": ("Белый", "#FFFFFF"),
    "cream": ("Сливочный", "#FFF7E8"), "sky": ("Небесный", "#EAF3FF"),
}
STYLES = {"normal": "Обычный", "compact": "Компактный", "detailed": "Подробный"}
EMOJI_SETS = {
    "classic": ("Классика", {"subj": "📖", "room": "🚪", "teacher": "👤", "group": "👥", "date": "📅",
                             "now": "🟢", "next": "⏳", "gap": "☕", "note": "📝"}),
    "cute": ("Милые", {"subj": "🌸", "room": "🏠", "teacher": "🧑‍🏫", "group": "🫂", "date": "🗓",
                       "now": "💖", "next": "⌛", "gap": "🧋", "note": "🎀"}),
    "space": ("Космос", {"subj": "🪐", "room": "🛸", "teacher": "👽", "group": "👾", "date": "🌌",
                         "now": "🚀", "next": "🌠", "gap": "☄️", "note": "📡"}),
    "minimal": ("Без эмодзи", {"subj": "", "room": "ауд.", "teacher": "", "group": "", "date": "",
                               "now": "●", "next": "○", "gap": "—", "note": "✎"}),
}
DEFAULT_ICONS = EMOJI_SETS["classic"][1]

FEATURES = (
    "🎨 8 тем картинок, свой цвет и фон, без подписи бота\n"
    "💬 стиль сообщений и наборы эмодзи\n"
    "⏳ напоминание перед парой — с аудиторией\n"
    "⭐ избранное: несколько групп и преподавателей\n"
    "📲 виджет с расписанием на экране телефона\n"
    "⏰ утренняя <b>и</b> вечерняя рассылка + неделя в воскресенье\n"
    "📝 безлимит заметок и напоминание о них утром\n"
    "👑 значок Premium и ранний доступ к новинкам"
)


def price(product: str, currency: str = STARS) -> int | None:
    """Цена товара: в звёздах (XTR) или рублях (RUB). None — такого товара нет в этой валюте."""
    kind, _, value = product.partition(":")
    if currency == STARS:
        if kind in ("plan", "gift") and value in PLANS:
            return PLANS[value][1]
        if kind == "theme" and value in THEMES and THEMES[value][2] > 0:
            return THEMES[value][2]
        if kind == "donate" and value.isdigit() and int(value) in DONATES:
            return int(value)
    elif currency == RUB:
        if kind in ("plan", "gift") and value in RUB_PLANS:
            return RUB_PLANS[value]
        if kind == "theme" and value in RUB_THEMES:
            return RUB_THEMES[value]
        if kind == "donate" and value.isdigit() and int(value) in RUB_DONATES:
            return int(value)
    return None


def fmt_price(amount: int, currency: str = STARS) -> str:
    return f"{amount} ₽" if currency == RUB else f"{amount} ⭐"


def price_label(product: str, rub: bool) -> str:
    """«30 ⭐» или «30 ⭐ / 79 ₽» — для кнопок, когда включена оплата картой."""
    stars, rubles = price(product, STARS), price(product, RUB)
    parts = [fmt_price(stars)] if stars else []
    if rub and rubles:
        parts.append(fmt_price(rubles, RUB))
    return " / ".join(parts)


def product_title(product: str) -> tuple[str, str]:
    """Название и описание товара для счёта."""
    kind, _, value = product.partition(":")
    if kind == "plan" and value in PLANS:
        title, _, days = PLANS[value]
        period = "навсегда" if days is None else ("на месяц" if days == 30 else "на год")
        return title, f"Все функции Premium {period}: темы, напоминания, избранное, рассылки и не только."
    if kind == "gift" and value in PLANS:
        name = PLANS[value][0].replace("⭐ ", "").replace("👑 ", "")
        return f"🎁 Подарок: {name}", "После оплаты получишь ссылку-подарок для друга."
    if kind == "theme" and value in THEMES:
        name, emoji, _ = THEMES[value]
        return f"{emoji} Тема «{name}»", "Тема картинки-расписания — твоя навсегда."
    if kind == "donate":
        return "💝 Поддержка бота", "Спасибо, что помогаешь боту жить!"
    return product, product


def receipt(product: str, rubles: int, vat_code: int = 1) -> dict:
    """Данные чека для ЮKassa (provider_data): одна позиция — услуга с полной оплатой."""
    title, _ = product_title(product)
    description = "".join(ch for ch in title if ch.isalnum() or ch in " «»:-.,").strip()[:128] or "Premium"
    return {"receipt": {"items": [{
        "description": description,
        "quantity": "1.00",
        "amount": {"value": f"{rubles}.00", "currency": RUB},
        "vat_code": vat_code,
        "payment_mode": "full_payment",
        "payment_subject": "service",
    }]}}


def _now_str() -> str:
    from utils.core import now  # здесь, чтобы не было циклического импорта
    return now().strftime("%Y-%m-%d %H:%M:%S")


def is_premium(user: dict | None) -> bool:
    return bool(user and user.get("premium_until") and user["premium_until"] >= _now_str())


def is_forever(user: dict | None) -> bool:
    return bool(user and user.get("premium_until") == FOREVER)


def status_text(user: dict | None) -> str:
    if is_forever(user):
        return "👑 Premium навсегда"
    if is_premium(user):
        until = datetime.strptime(user["premium_until"], "%Y-%m-%d %H:%M:%S")
        return f"⭐ Premium до {until:%d.%m.%Y}"
    return "без Premium"


def can_use_theme(user: dict | None, theme: str, owned: set[str]) -> bool:
    return THEMES.get(theme, ("", "", 1))[2] == 0 or is_premium(user) or theme in owned


def icons_for(user: dict | None) -> dict:
    """Набор эмодзи пользователя (только для Premium, иначе — классика)."""
    if is_premium(user):
        return EMOJI_SETS.get(user.get("emoji_set") or "classic", EMOJI_SETS["classic"])[1]
    return DEFAULT_ICONS


def style_for(user: dict | None) -> str:
    return (user.get("msg_style") or "normal") if is_premium(user) else "normal"


PAYWALL_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="⭐ Подробнее о Premium", callback_data="pm:menu")]])


def paywall(feature: str) -> str:
    from config import YOOKASSA_TOKEN
    cost = price_label("plan:month", bool(YOOKASSA_TOKEN)).replace(" / ", "</b> или <b>")
    return (f"⭐ <b>{feature}</b> — функция Premium\n\n"
            f"<blockquote>{FEATURES}</blockquote>\n\n"
            f"От <b>{cost}</b> в месяц. Новым — <b>{TRIAL_DAYS} дня бесплатно</b> 🎁")
