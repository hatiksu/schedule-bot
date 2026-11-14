from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from modules.appearance import show
from utils.core import btn, db, log, now

router = Router(name="achievements")

ACHIEVEMENTS = {
    "start": ("🎓", "Первый шаг", "выбрать группу или преподавателя", "chosen", 1, 0),
    "streak7": ("🔥", "Неделя с ботом", "заходить в бота 7 дней подряд", "streak", 7, 1),
    "notes10": ("📝", "Организатор", "написать 10 заметок к парам", "notes", 10, 0),
    "images10": ("🖼", "Фотограф", "сделать 10 картинок расписания", "images", 10, 0),
    "digest30": ("⏰", "Режим дня", "получить 30 авторассылок", "digests", 30, 3),
    "invite1": ("🤝", "Первый друг", "пригласить друга", "invites", 1, 0),
    "invite5": ("📣", "Душа компании", "пригласить 5 друзей", "invites", 5, 7),
    "invite10": ("🚀", "Амбассадор", "пригласить 10 друзей", "invites", 10, 30),
    "supporter": ("💝", "Меценат", "оформить Premium, купить тему или поддержать бота", "paid", 1, 0),
    "gift": ("🎁", "Щедрая душа", "подарить Premium другу", "gifts", 1, 0),
}


async def _progress(uid: int) -> dict:
    return await db.achievement_progress(uid, (now().date() - timedelta(days=6)).isoformat())


async def check(bot: Bot, uid: int) -> None:
    try:
        have = await db.achievements(uid)
        prog = await _progress(uid)
        for code, (emoji, title, desc, key, goal, reward) in ACHIEVEMENTS.items():
            if code in have or prog.get(key, 0) < goal:
                continue
            if not await db.grant_achievement(uid, code):
                continue
            bonus = ""
            if reward:
                await db.extend_premium(uid, reward)
                await db.add_purchase(uid, f"ach:{code}", 0, None)
                bonus = f"\n🎁 Награда: <b>+{reward} дн. Premium</b>"
            try:
                await bot.send_message(uid, f"🏆 <b>Новое достижение!</b>\n<blockquote>{emoji} <b>{title}</b>"
                                            f" — {desc}{bonus}</blockquote>",
                                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                           [btn("🏆 Все достижения", "ach:list")]]))
            except TelegramAPIError:
                pass
    except Exception:
        log.exception("Проверка достижений %s", uid)


async def list_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    have = await db.achievements(uid)
    prog = await _progress(uid)
    lines = []
    for code, (emoji, title, desc, key, goal, reward) in ACHIEVEMENTS.items():
        reward_s = f" · 🎁 +{reward} дн. Premium" if reward else ""
        if code in have:
            lines.append(f"✅ {emoji} <b>{title}</b> — {desc}{reward_s}")
        else:
            cur = min(prog.get(key, 0), goal)
            bar = f" <i>({cur}/{goal})</i>" if goal > 1 else ""
            lines.append(f"🔒 {emoji} {title} — {desc}{bar}{reward_s}")
    text = (f"🏆 <b>Достижения</b> · {len(have)}/{len(ACHIEVEMENTS)}\n\n<blockquote>"
            + "\n".join(lines) + "</blockquote>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn("🤝 Пригласить друзей", "ref:menu")],
                                               [btn("◀️ К настройкам", "st:home")]])
    return text, kb


@router.message(Command("achievements"))
async def cmd_list(m: Message):
    await check(m.bot, m.from_user.id)
    text, kb = await list_view(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ach:list")
async def cb_list(c: CallbackQuery):
    await check(c.bot, c.from_user.id)
    text, kb = await list_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()
