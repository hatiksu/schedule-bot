"""🤝 Реферальная программа: своя ссылка, +REF_BONUS_DAYS дней Premium за каждого друга,
который впервые пришёл по ссылке и выбрал группу."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import REF_BONUS_DAYS
from modules.appearance import show
from utils.core import btn, db, log, runtime
from utils.premium import status_text

router = Router(name="referral")


def ref_link(uid: int) -> str:
    return f"https://t.me/{runtime['bot_username']}?start=ref_{uid}"


async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    came, counted = await db.referral_counts(uid)
    link = ref_link(uid)
    share_text = "Удобное расписание колледжа в Telegram: пары, замены, звонки, свободные аудитории 📚"
    share = f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}"
    text = (
        "🤝 <b>Пригласи друзей — получи Premium</b>\n\n"
        f"<blockquote>За каждого друга, который зайдёт по твоей ссылке и выберет группу, — "
        f"<b>+{REF_BONUS_DAYS} дней Premium</b>. Дни складываются!</blockquote>\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>\n<i>(нажми, чтобы скопировать)</i>\n\n"
        f"<blockquote>👥 Пришли по ссылке: <b>{came}</b>\n"
        f"✅ Засчитано: <b>{counted}</b> → <b>+{counted * REF_BONUS_DAYS} дн.</b> Premium</blockquote>\n"
        "🏆 За 5 и 10 друзей — ещё бонусы в достижениях"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share)],
        [btn("🏆 Достижения", "ach:list"), btn("◀️ К настройкам", "st:home")],
    ])
    return text, kb


@router.message(Command("invite"))
async def cmd_invite(m: Message):
    text, kb = await menu_view(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ref:menu")
async def cb_menu(c: CallbackQuery):
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()


async def remember_inviter(uid: int, payload: str, is_new: bool) -> None:
    """/start ref_123 — запоминаем пригласившего, только если пользователь новый."""
    raw = payload.removeprefix("ref_")
    if not is_new or not raw.isdigit() or int(raw) == uid or not await db.user_exists(int(raw)):
        return
    await db.set_referrer(uid, int(raw))


async def reward_inviter(bot: Bot, uid: int) -> None:
    """Вызывается, когда приглашённый выбрал группу. Бонус — один раз."""
    inviter = await db.take_referral_reward(uid)
    if not inviter:
        return
    try:
        await db.extend_premium(inviter, REF_BONUS_DAYS)
        await db.add_purchase(inviter, f"ref:{uid}", 0, None)
        friend = await db.get_user(uid) or {}
        name = escape(friend.get("full_name") or "Друг")
        user = await db.get_user(inviter)
        await bot.send_message(inviter, f"🤝 <b>{name}</b> присоединился по твоей ссылке!\n"
                                        f"<blockquote>🎁 +{REF_BONUS_DAYS} дней Premium · {status_text(user)}"
                                        "</blockquote>",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("🤝 Пригласить ещё",
                                                                                       "ref:menu")]]))
    except TelegramAPIError:
        pass
    except Exception:
        log.exception("Реферальный бонус")
    from modules.achievements import check
    await check(bot, inviter)
