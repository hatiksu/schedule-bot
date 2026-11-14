from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineQuery, InlineQueryResultsButton, Message

from config import ADMIN_IDS
from utils.core import ALL_BUTTONS, BTN_BELLS, BTN_LOAD, BTN_ROOMS, BTN_SEARCH, BTN_SETTINGS, BTN_WHERE, \
    db, log, now, runtime

MAINTENANCE_TEXT = ("🛠 <b>Бот обновляется</b>\n"
                    "<blockquote>Идут технические работы — загляни через пару минут 🙏</blockquote>")

CALLBACK_EVENTS = {
    "v": "schedule", "img": "img", "nt": "notes", "ntp": "notes", "ntw": "notes", "ntd": "notes",
    "fr": "rooms", "wh": "where", "ld": "workload", "dg": "digest", "ap": "appearance", "pm": "premium",
    "fav": "favorites", "rm": "reminders", "bells": "bells", "st": "settings", "fb": "feedback",
    "gf": "gifts", "ref": "referral", "ach": "achievements", "wg": "widget", "set": "setup", "role": "setup",
}
BUTTON_EVENTS = {BTN_SEARCH: "search", BTN_ROOMS: "rooms", BTN_BELLS: "bells", BTN_WHERE: "where",
                 BTN_LOAD: "workload", BTN_SETTINGS: "settings"}
_checked: dict[int, str] = {}


def event_name(event) -> str | None:
    if isinstance(event, CallbackQuery):
        return CALLBACK_EVENTS.get((event.data or "").split(":")[0])
    if isinstance(event, InlineQuery):
        return "inline"
    if isinstance(event, Message):
        if event.successful_payment:
            return "payment"
        text = event.text or ""
        if text.startswith("/"):
            return "cmd:" + text[1:].split()[0].split("@")[0].lower()[:20]
        if text in BUTTON_EVENTS:
            return BUTTON_EVENTS[text]
        if text in ALL_BUTTONS:
            return "schedule"
        return "text" if text else "other"
    return None


FLOW_CALLBACKS = {
    "Setup": ("role:", "set:"),
    "Search": (),
    "NoteState": ("nt:", "ntp:", "ntw:"),
    "WhereState": ("wh:",),
    "LoadState": ("ld:",),
    "FeedbackState": ("fb:",),
    "ReplyState": ("fbr:", "fbo:"),
    "PromoState": ("pm:promo",),
    "PhotoState": ("ap:photo",),
    "FindUser": ("adm:find", "adm:user:"),
    "Broadcast": ("adm:bc",),
    "HolidayState": ("adm:hol",),
    "PromoCreate": ("pa:pnew",),
    "ImportState": ("bk:imp", "bk:mg", "bk:rp"),
}


def leaves_flow(event, raw_state: str) -> bool:
    group = raw_state.split(":", 1)[0]
    if isinstance(event, Message):
        text = event.text or ""
        return text.startswith("/") or text in ALL_BUTTONS
    if isinstance(event, CallbackQuery):
        allowed = FLOW_CALLBACKS.get(group, ())
        return not (event.data or "").startswith(allowed) if allowed else True
    return False


class UserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if not u or u.is_bot:
            return await handler(event, data)
        banned = False
        try:
            data["is_new_user"] = not await db.user_exists(u.id)
            banned = await db.touch_user(u.id, u.username, u.full_name)
        except Exception:
            log.exception("Не удалось сохранить пользователя %s", u.id)
        if isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)
        if u.id not in ADMIN_IDS:
            if banned:
                if isinstance(event, CallbackQuery):
                    await event.answer("🚫 Доступ к боту ограничен", show_alert=True)
                return None
            if runtime["maintenance"]:
                if isinstance(event, CallbackQuery):
                    await event.answer("🛠 Идут техработы, загляни через пару минут", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(MAINTENANCE_TEXT)
                elif isinstance(event, InlineQuery):
                    await event.answer([], cache_time=10, is_personal=True,
                                       button=InlineQueryResultsButton(text="🛠 Идут техработы",
                                                                       start_parameter="maint"))
                return None
        if data.get("raw_state") and leaves_flow(event, data["raw_state"]):
            state = data.get("state")
            if state:
                await state.clear()
            data["raw_state"] = None
        result = await handler(event, data)
        try:
            name = event_name(event)
            if name and u.id not in ADMIN_IDS:
                await db.log_event(u.id, name)
            today = now().date().isoformat()
            if _checked.get(u.id) != today:
                _checked[u.id] = today
                from modules.achievements import check
                await check(data["bot"], u.id)
        except Exception:
            log.exception("Статистика / достижения")
        return result


def setup(dp) -> None:
    for observer in (dp.message, dp.callback_query, dp.inline_query):
        observer.outer_middleware(UserMiddleware())
