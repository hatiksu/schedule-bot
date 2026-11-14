"""🎁 Подарить Premium: покупаешь звёздами — получаешь ссылку-подарок и отправляешь кому угодно."""
from __future__ import annotations

import secrets
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from modules.appearance import show
from utils.core import btn, db, runtime
from utils.premium import PLANS, status_text

router = Router(name="gifts")


def gift_link(code: str) -> str:
    return f"https://t.me/{runtime['bot_username']}?start=gift_{code}"


@router.callback_query(F.data == "gf:menu")
async def cb_menu(c: CallbackQuery):
    gifts = await db.gifts_of(c.from_user.id)
    mine = ""
    if gifts:
        lines = []
        for g in gifts:
            who = f"✅ получил {escape(g['full_name'] or 'друг')}" if g["redeemed_by"] else "⏳ ещё не открыт"
            lines.append(f"{PLANS[g['plan']][0]} · {who}")
        mine = "\n\n<b>Твои подарки</b>\n<blockquote>" + "\n".join(lines) + "</blockquote>"
    rows = [[btn(f"🎁 {PLANS[p][0].split(' ', 1)[1]} — {PLANS[p][1]} ⭐", f"gf:buy:{p}")] for p in PLANS]
    rows.append([btn("◀️ К Premium", "pm:menu")])
    await show(c, "🎁 <b>Подарить Premium</b>\n<blockquote>После оплаты пришлю ссылку-подарок — "
                  "отправь её другу, старосте, одногруппнику. Открыть её может любой, даже кто ещё "
                  "не пользуется ботом.</blockquote>" + mine,
               InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("gf:buy:"))
async def cb_buy(c: CallbackQuery):
    from modules.shop import send_invoice
    plan = c.data.split(":")[2]
    if plan not in PLANS:
        await c.answer()
        return
    title = PLANS[plan][0].replace("⭐ ", "").replace("👑 ", "")
    await send_invoice(c.message, f"gift:{plan}", f"🎁 Подарок: {title}",
                       "После оплаты получишь ссылку-подарок для друга.")
    await c.answer()


async def after_purchase(m: Message, plan: str) -> None:
    """Вызывается из shop после оплаты подарка."""
    code = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    await db.create_gift(code, plan, m.from_user.id)
    link = gift_link(code)
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('Держи подарок — Premium в боте расписания 🎁')}"
    await m.answer(
        f"🎁 <b>Подарок готов!</b>\n<blockquote>{PLANS[plan][0]}</blockquote>\n\n"
        f"Отправь эту ссылку тому, кому даришь:\n<code>{link}</code>\n\n"
        "<i>Ссылка одноразовая — сработает у первого, кто её откроет.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Отправить другу", url=share)]]))


async def redeem(m: Message, payload: str) -> bool:
    """/start gift_КОД. Возвращает True, если это была ссылка-подарок (обработана)."""
    code = payload.removeprefix("gift_")
    gift = await db.get_gift(code)
    if not gift:
        await m.answer("🎁 Подарок не найден — проверь ссылку.")
        return True
    if gift["redeemed_by"]:
        await m.answer("🎁 Этот подарок уже кто-то открыл.")
        return True
    if gift["buyer_id"] == m.from_user.id:
        await m.answer("🎁 Это твой подарок — отправь ссылку другу, чтобы он его открыл 😉")
        return True
    if not await db.redeem_gift(code, m.from_user.id):
        await m.answer("🎁 Этот подарок уже кто-то открыл.")
        return True
    await db.extend_premium(m.from_user.id, PLANS[gift["plan"]][2])
    await db.add_purchase(m.from_user.id, f"gifted:{gift['plan']}", 0, None)
    user = await db.get_user(m.from_user.id)
    buyer = await db.get_user(gift["buyer_id"]) or {}
    await m.answer(f"🎉 <b>Тебе подарили Premium!</b>\n<blockquote>от {escape(buyer.get('full_name') or 'друга')} · "
                   f"{status_text(user)}</blockquote>\nЗагляни в ⚙️ Настройки → 🎨 Оформление 😉")
    try:
        await m.bot.send_message(gift["buyer_id"], f"🎁 Твой подарок открыл "
                                                   f"<b>{escape(user.get('full_name') or 'друг')}</b> — спасибо, что радуешь друзей 💙")
    except TelegramAPIError:
        pass
    return True
