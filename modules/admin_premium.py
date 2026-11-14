from __future__ import annotations

import re
from html import escape

import httpx
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from modules.appearance import show
from utils.core import btn, db, now
from utils.filters import IsAdmin
from utils.premium import PLANS, RUB, THEMES, fmt_price, status_text
from utils.yookassa import YooKassaError

router = Router(name="admin_premium")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

BACK = [btn("◀️ К Premium", "pa:menu")]


class PromoCreate(StatesGroup):
    text = State()


def product_name(p: str) -> str:
    kind, _, v = p.partition(":")
    if kind == "plan":
        return PLANS.get(v, (v,))[0]
    if kind == "theme":
        name, emoji, _ = THEMES.get(v, (v, "🎨", 0))
        return f"{emoji} тема «{name}»"
    if kind == "donate":
        return "💝 донат"
    if kind == "grant":
        return "🎁 выдал админ"
    if kind == "promo":
        return f"🎟 промокод {v}"
    return {"trial": "🎁 пробный период"}.get(p, p)


@router.callback_query(F.data == "pa:menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    n = now()
    s = await db.premium_stats(n.strftime("%Y-%m-%d %H:%M:%S"), n.strftime("%Y-%m-01 00:00:00"))
    top = "\n".join(f"{product_name(r['product'])} — {r['c']} шт · <b>{fmt_price(r['s'], r['currency'])}</b>"
                    for r in s["by_product"]) or "продаж пока нет"
    rub = f" + <b>{s['month_rub']} ₽</b>" if s["total_rub"] else ""
    rub_total = f" + <b>{s['total_rub']} ₽</b>" if s["total_rub"] else ""
    await show(c,
               "⭐ <b>Premium и продажи</b>\n\n<blockquote>"
               f"👑 Активных Premium: <b>{s['active']}</b> (навсегда: {s['forever']}, на пробе: {s['trials']})\n\n"
               f"💰 Выручка за месяц: <b>{s['month']} ⭐</b>{rub}\n"
               f"💰 Всего: <b>{s['total']} ⭐</b>{rub_total} · покупок: {s['cnt']}</blockquote>\n"
               f"<b>Что покупают</b>\n<blockquote>{top}</blockquote>\n\n"
               "<i>Звёзды выводятся через @BotFather → бот → Monetization (Fragment), "
               "рубли приходят на счёт в ЮKassa.</i>",
               InlineKeyboardMarkup(inline_keyboard=[
                   [btn("🧾 Последние покупки", "pa:sales"), btn("🎟 Промокоды", "pa:promos")],
                   [btn("◀️ В админку", "adm:home")]]))
    await c.answer()


@router.callback_query(F.data == "pa:sales")
async def cb_sales(c: CallbackQuery):
    items = await db.purchases(15)
    lines, rows = [], []
    for p in items:
        who = escape(p["full_name"] or str(p["user_id"]))
        mark = " · ↩️ возврат" if p["refunded"] else ""
        lines.append(f"#{p['id']} · {p['created_at'][5:16]} · {who} · {product_name(p['product'])} · "
                     f"<b>{fmt_price(p['stars'], p.get('currency') or 'XTR')}</b>{mark}")
        if p["charge_id"] and not p["refunded"]:
            rows.append(btn(f"↩️ #{p['id']}", f"pa:ref:{p['id']}"))
    kb = [rows[i:i + 4] for i in range(0, len(rows), 4)] + [BACK]
    await show(c, "🧾 <b>Последние покупки</b>\n<blockquote>" + ("\n".join(lines) or "пока пусто") +
               "</blockquote>\n\n↩️ — вернуть оплату (и забрать купленное)",
               InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()


@router.callback_query(F.data.startswith("pa:ref:"))
async def cb_refund_ask(c: CallbackQuery):
    p = await db.get_purchase(int(c.data.split(":")[2]))
    if not p:
        await c.answer("Не найдено", show_alert=True)
        return
    amount = fmt_price(p["stars"], p.get("currency") or "XTR")
    if p.get("currency") == RUB:
        note = "Деньги вернутся на карту через ЮKassa, купленное заберу."
    else:
        note = "Звёзды вернутся покупателю, купленное заберу."
    await show(c, f"↩️ Вернуть <b>{amount}</b> за «{product_name(p['product'])}» (#{p['id']})?\n"
                  f"<blockquote>{note}</blockquote>",
               InlineKeyboardMarkup(inline_keyboard=[[btn("✅ Да, вернуть", f"pa:rr:{p['id']}")],
                                                     [btn("◀️ Назад", "pa:sales")]]))
    await c.answer()


@router.callback_query(F.data.startswith("pa:rr:"))
async def cb_refund(c: CallbackQuery):
    p = await db.get_purchase(int(c.data.split(":")[2]))
    if not p or p["refunded"] or not p["charge_id"]:
        await c.answer("Возврат уже сделан или невозможен", show_alert=True)
        return
    is_rub = p.get("currency") == RUB
    if is_rub:
        from modules.shop import yookassa
        try:
            status = await yookassa.refund(p["provider_charge_id"] or p["charge_id"], p["stars"])
        except (YooKassaError, httpx.HTTPError) as e:
            await c.answer(f"ЮKassa не дала вернуть: {e}"[:190], show_alert=True)
            return
        if status == "canceled":
            await c.answer("ЮKassa отклонила возврат — проверь в личном кабинете", show_alert=True)
            return
    else:
        try:
            await c.bot.refund_star_payment(user_id=p["user_id"], telegram_payment_charge_id=p["charge_id"])
        except TelegramAPIError as e:
            await c.answer(f"Telegram не дал вернуть: {e}", show_alert=True)
            return
    await db.mark_refunded(p["id"])
    kind, _, value = p["product"].partition(":")
    if kind == "plan":
        await db.revoke_premium(p["user_id"])
    elif kind == "theme":
        await db.remove_theme(p["user_id"], value)
        user = await db.get_user(p["user_id"])
        if user and user.get("theme") == value:
            await db.set_pref(p["user_id"], "theme", None)
    try:
        amount = fmt_price(p["stars"], p.get("currency") or "XTR")
        when = " Деньги придут на карту в течение нескольких дней." if is_rub else ""
        await c.bot.send_message(p["user_id"], f"↩️ Тебе вернули <b>{amount}</b> за «{product_name(p['product'])}».{when}")
    except TelegramAPIError:
        pass
    await c.answer("✅ Возврат оформлен" if is_rub else "✅ Звёзды возвращены", show_alert=True)
    await cb_sales(c)


@router.callback_query(F.data == "pa:promos")
async def cb_promos(c: CallbackQuery, state: FSMContext):
    await state.clear()
    items = await db.promos()
    lines = []
    for p in items:
        days = "навсегда" if p["days"] == 0 else f"{p['days']} дн."
        left = "∞" if p["uses_left"] < 0 else p["uses_left"]
        lines.append(f"<code>{escape(p['code'])}</code> · {days} · осталось {left} · использовали {p['used']}")
    rows = [[btn(f"🗑 {p['code']}", f"pa:pdel:{p['code']}")] for p in items[:10]]
    await show(c, "🎟 <b>Промокоды</b>\n<blockquote>" + ("\n".join(lines) or "пока нет") + "</blockquote>",
               InlineKeyboardMarkup(inline_keyboard=[[btn("➕ Создать промокод", "pa:pnew")]] + rows + [BACK]))
    await c.answer()


@router.callback_query(F.data == "pa:pnew")
async def cb_promo_new(c: CallbackQuery, state: FSMContext):
    await state.set_state(PromoCreate.text)
    await show(c, "➕ <b>Новый промокод</b>\nНапиши: <code>КОД ДНЕЙ КОЛИЧЕСТВО</code>\n<blockquote>"
                  "<code>START7 7 100</code> — 7 дней Premium, 100 активаций\n"
                  "<code>VIP 0 5</code> — Premium навсегда, 5 активаций\n"
                  "<code>FRIENDS 30 0</code> — 30 дней, без лимита активаций</blockquote>",
               InlineKeyboardMarkup(inline_keyboard=[[btn("◀️ Назад", "pa:promos")]]))
    await c.answer()


@router.message(PromoCreate.text, F.text)
async def got_promo(m: Message, state: FSMContext):
    parts = m.text.split()
    if len(parts) != 3 or not re.fullmatch(r"[A-Za-zА-Яа-я0-9_-]{3,32}", parts[0]) \
            or not parts[1].isdigit() or not parts[2].isdigit():
        await m.answer("🤔 Формат: <code>КОД ДНЕЙ КОЛИЧЕСТВО</code>, например <code>START7 7 100</code>")
        return
    code, days, uses = parts[0].upper(), int(parts[1]), int(parts[2])
    await db.create_promo(code, days, uses if uses > 0 else -1)
    await state.clear()
    await m.answer(f"✅ Промокод <code>{escape(code)}</code> создан\n<blockquote>"
                   f"{'навсегда' if days == 0 else f'{days} дн. Premium'} · "
                   f"{'без лимита' if uses == 0 else f'{uses} активаций'}</blockquote>",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("🎟 К промокодам", "pa:promos")]]))


@router.callback_query(F.data.startswith("pa:pdel:"))
async def cb_promo_del(c: CallbackQuery, state: FSMContext):
    await db.delete_promo(c.data.split(":", 2)[2])
    await c.answer("Удалён")
    await cb_promos(c, state)


@router.callback_query(F.data.startswith("pa:give:"))
async def cb_give(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    user = await db.get_user(uid)
    if not user:
        await c.answer("Пользователь не найден", show_alert=True)
        return
    await show(c, f"⭐ <b>Premium для {escape(user.get('full_name') or str(uid))}</b>\n"
                  f"<blockquote>Сейчас: {status_text(user)}</blockquote>",
               InlineKeyboardMarkup(inline_keyboard=[
                   [btn("+7 дней", f"pa:g:{uid}:7"), btn("+30 дней", f"pa:g:{uid}:30"),
                    btn("+365 дней", f"pa:g:{uid}:365")],
                   [btn("👑 Навсегда", f"pa:g:{uid}:0"), btn("❌ Забрать", f"pa:g:{uid}:x")],
                   [btn("◀️ К пользователю", f"adm:user:{uid}")]]))
    await c.answer()


@router.callback_query(F.data.startswith("pa:g:"))
async def cb_grant(c: CallbackQuery):
    _, _, uid, val = c.data.split(":")
    uid = int(uid)
    if val == "x":
        await db.revoke_premium(uid)
        await c.answer("Premium забран", show_alert=True)
    else:
        days = int(val) or None
        await db.extend_premium(uid, days)
        await db.add_purchase(uid, f"grant:{val}", 0, None)
        user = await db.get_user(uid)
        try:
            await c.bot.send_message(uid, f"🎁 <b>Тебе подарили Premium!</b>\n<blockquote>{status_text(user)}"
                                          "</blockquote>\nОткрой ⚙️ Настройки → 🎨 Оформление 😉")
        except TelegramAPIError:
            pass
        await c.answer(f"✅ Выдано: {status_text(user)}", show_alert=True)
    await cb_give(c)
