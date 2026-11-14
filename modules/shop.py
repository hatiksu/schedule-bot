"""⭐ Premium: витрина, оплата Telegram Stars, пробный период, промокоды, донаты.

Оплата — встроенная в Telegram (валюта XTR), без ИП и эквайринга.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery)

from config import ADMIN_IDS
from utils.core import ALL_BUTTONS, btn, db, log, now
from utils.premium import (DONATES, FEATURES, FOREVER, PLANS, THEMES, TRIAL_DAYS, is_forever,
                           is_premium, status_text)

router = Router(name="premium")


class PromoState(StatesGroup):
    code = State()


def price_of(product: str) -> int | None:
    """Сколько звёзд стоит товар (для проверки перед оплатой)."""
    kind, _, value = product.partition(":")
    if kind == "plan" and value in PLANS:
        return PLANS[value][1]
    if kind == "theme" and value in THEMES and THEMES[value][2] > 0:
        return THEMES[value][2]
    if kind == "gift" and value in PLANS:
        return PLANS[value][1]
    if kind == "donate" and value.isdigit() and int(value) in DONATES:
        return int(value)
    return None


def _until_human(until: str) -> str:
    if until == FOREVER:
        return "навсегда 👑"
    return "до " + datetime.strptime(until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")


# ---------- витрина ----------
async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid) or {}
    active = is_premium(user)
    status = status_text(user)
    text = (
        f"⭐ <b>Premium</b>\n<blockquote>Статус: <b>{status}</b></blockquote>\n\n"
        f"<b>Что даёт Premium:</b>\n<blockquote>{FEATURES}</blockquote>\n\n"
        "Базовое расписание всегда бесплатное — Premium добавляет красоту и удобство 💙"
    )
    rows = []
    if not user.get("trial_used") and not user.get("premium_until"):
        rows.append([btn(f"🎁 Попробовать {TRIAL_DAYS} дня бесплатно", "pm:trial")])
    if not is_forever(user):
        month, year, forever = PLANS["month"], PLANS["year"], PLANS["forever"]
        save = round(100 - year[1] / (month[1] * 12) * 100)
        verb = "Продлить" if active else "Купить"
        rows += [
            [btn(f"{verb} на месяц — {month[1]} ⭐", "pm:buy:month")],
            [btn(f"{verb} на год — {year[1]} ⭐ (−{save}%)", "pm:buy:year")],
            [btn(f"👑 Навсегда — {forever[1]} ⭐", "pm:buy:forever")],
        ]
    rows += [
        [btn("🎨 Темы по отдельности", "ap:themes"), btn("🎁 Подарить другу", "gf:menu")],
        [btn("🤝 Получить бесплатно", "ref:menu")],
        [btn("🎟 Промокод", "pm:promo"), btn("💝 Поддержать", "pm:donate")],
        [btn("◀️ К настройкам", "st:home")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("premium"))
async def cmd_premium(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await menu_view(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "pm:menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await menu_view(c.from_user.id)
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except TelegramAPIError:  # если это было фото (превью темы) — шлём новым сообщением
        await c.message.answer(text, reply_markup=kb)
    await c.answer()


# ---------- пробный период ----------
@router.callback_query(F.data == "pm:trial")
async def cb_trial(c: CallbackQuery):
    user = await db.get_user(c.from_user.id) or {}
    if user.get("trial_used") or user.get("premium_until"):
        await c.answer("Пробный период уже был 🙂", show_alert=True)
        return
    until = await db.extend_premium(c.from_user.id, TRIAL_DAYS)
    await db.mark_trial(c.from_user.id)
    await db.add_purchase(c.from_user.id, "trial", 0, None)
    await c.answer("🎁 Premium включён!")
    await c.message.edit_text(
        f"🎁 <b>Premium на {TRIAL_DAYS} дня включён!</b>\n"
        f"<blockquote>Действует {_until_human(until)}. Попробуй всё:</blockquote>",
        reply_markup=_after_kb())


def _after_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🎨 Темы и оформление", "ap:menu")],
        [btn("⏳ Напоминание перед парой", "rm:menu"), btn("⭐ Избранное", "fav:list")],
        [btn("⏰ Рассылки", "dg:menu")],
    ])


# ---------- оплата ----------
async def send_invoice(message: Message, product: str, title: str, description: str) -> None:
    price = price_of(product)
    await message.answer_invoice(
        title=title,
        description=description,
        payload=product,
        currency="XTR",                       # Telegram Stars
        prices=[LabeledPrice(label=title, amount=price)],
    )


@router.callback_query(F.data.startswith("pm:buy:"))
async def cb_buy(c: CallbackQuery):
    plan = c.data.split(":")[2]
    if plan not in PLANS:
        await c.answer()
        return
    title, stars, days = PLANS[plan]
    period = "навсегда" if days is None else ("на месяц" if days == 30 else "на год")
    await send_invoice(c.message, f"plan:{plan}", title,
                       f"Все функции Premium {period}: темы, напоминания, избранное, рассылки и не только.")
    await c.answer()


@router.callback_query(F.data == "pm:donate")
async def cb_donate(c: CallbackQuery):
    rows, row = [], []
    for n in DONATES:
        row.append(btn(f"{n} ⭐", f"pm:don:{n}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("◀️ Назад", "pm:menu")])
    await c.message.edit_text(
        "💝 <b>Поддержать бота</b>\n<blockquote>Бот бесплатный и работает на энтузиазме. "
        "Звёзды помогают оплачивать сервер и добавлять новое. Спасибо! 🙏</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("pm:don:"))
async def cb_donate_pay(c: CallbackQuery):
    n = c.data.split(":")[2]
    await send_invoice(c.message, f"donate:{n}", f"💝 Поддержка бота · {n} ⭐", "Спасибо, что помогаешь боту жить!")
    await c.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    expected = price_of(q.invoice_payload)
    if expected is None or q.total_amount != expected or q.currency != "XTR":
        await q.answer(ok=False, error_message="Цена изменилась — открой меню Premium заново 🙏")
        return
    await q.answer(ok=True)


async def apply_purchase(uid: int, product: str) -> str:
    """Выдаёт купленное. Возвращает текст для пользователя."""
    kind, _, value = product.partition(":")
    if kind == "plan":
        until = await db.extend_premium(uid, PLANS[value][2])
        return f"⭐ <b>Premium активен {_until_human(until)}</b>"
    if kind == "theme":
        await db.add_theme(uid, value)
        await db.set_pref(uid, "theme", value)
        name, emoji, _ = THEMES[value]
        return f"🎨 Тема <b>{emoji} {name}</b> твоя навсегда — и уже включена"
    return "💝 <b>Спасибо за поддержку!</b> Это очень помогает боту 🙏"


@router.message(F.successful_payment)
async def got_payment(m: Message):
    sp = m.successful_payment
    product = sp.invoice_payload
    await db.add_purchase(m.from_user.id, product, sp.total_amount, sp.telegram_payment_charge_id)
    if product.startswith("gift:"):
        from modules.gifts import after_purchase
        await after_purchase(m, product.split(":")[1])
    else:
        text = await apply_purchase(m.from_user.id, product)
        kb = _after_kb() if not product.startswith("donate") else None
        await m.answer(f"🎉 Оплата прошла!\n<blockquote>{text}</blockquote>", reply_markup=kb)
    from modules.achievements import check
    await check(m.bot, m.from_user.id)
    user = await db.get_user(m.from_user.id) or {}
    who = escape(user.get("full_name") or str(m.from_user.id))
    uname = f" @{escape(user['username'])}" if user.get("username") else ""
    for admin_id in ADMIN_IDS:
        try:
            await m.bot.send_message(admin_id, f"💰 <b>+{sp.total_amount} ⭐</b> · {escape(product)}\n"
                                               f"от {who}{uname} · <code>{m.from_user.id}</code>",
                                     disable_notification=True)
        except TelegramAPIError:
            pass


# ---------- промокод ----------
@router.callback_query(F.data == "pm:promo")
async def cb_promo(c: CallbackQuery, state: FSMContext):
    await state.set_state(PromoState.code)
    await c.message.edit_text("🎟 Отправь промокод сообщением",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("◀️ Назад", "pm:menu")]]))
    await c.answer()


@router.message(PromoState.code, F.text, ~F.text.in_(ALL_BUTTONS))
async def got_promo(m: Message, state: FSMContext):
    result = await db.redeem_promo(m.from_user.id, m.text)
    if isinstance(result, str):
        await m.answer(f"🎟 {result}")
        return
    await state.clear()
    until = await db.extend_premium(m.from_user.id, result or None)
    await db.add_purchase(m.from_user.id, f"promo:{m.text.strip().upper()}", 0, None)
    await m.answer(f"🎉 Промокод активирован!\n<blockquote>⭐ Premium {_until_human(until)}</blockquote>",
                   reply_markup=_after_kb())


# ---------- предупреждение об окончании ----------
async def loop(bot: Bot) -> None:
    while True:
        try:
            n = now()
            for user in await db.premium_expiring(n.strftime("%Y-%m-%d %H:%M:%S"),
                                                  (n + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")):
                await db.mark_warned(user["user_id"])
                until = datetime.strptime(user["premium_until"], "%Y-%m-%d %H:%M:%S")
                try:
                    await bot.send_message(
                        user["user_id"],
                        f"⭐ <b>Premium заканчивается {until:%d.%m в %H:%M}</b>\n"
                        "<blockquote>Темы, напоминания и избранное останутся настроенными — "
                        "продли, чтобы они продолжили работать.</blockquote>",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("⭐ Продлить", "pm:menu")]]))
                except TelegramAPIError:
                    pass
                await asyncio.sleep(0.05)
        except Exception:
            log.exception("Ошибка проверки Premium")
        await asyncio.sleep(1800)
