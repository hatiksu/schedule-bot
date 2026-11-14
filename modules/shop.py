"""⭐ Premium: витрина, оплата Telegram Stars или картой/СБП через ЮKassa, пробный период, промокоды, донаты.

Звёзды (валюта XTR) — встроенная оплата Telegram, без ИП и эквайринга.
Рубли (RUB) — Telegram Payments с провайдером ЮKassa: токен из @BotFather → Payments, без своего сервера.
Если токена ЮKassa нет, бот работает как раньше — только звёзды.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery)

from config import ADMIN_IDS, YOOKASSA_RECEIPT, YOOKASSA_TOKEN, YOOKASSA_VAT_CODE
from utils.core import ALL_BUTTONS, btn, db, log, now
from utils.premium import (DONATES, FEATURES, FOREVER, PLANS, RUB, RUB_DONATES, STARS, THEMES, TRIAL_DAYS,
                           fmt_price, is_forever, is_premium, price, price_label, product_title, receipt,
                           status_text)

router = Router(name="premium")


class PromoState(StatesGroup):
    code = State()


def price_of(product: str) -> int | None:
    """Сколько звёзд стоит товар (для проверки перед оплатой)."""
    return price(product, STARS)


def rub_enabled() -> bool:
    """Подключена ли оплата картой через ЮKassa."""
    return bool(YOOKASSA_TOKEN)


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
        month, year = PLANS["month"], PLANS["year"]
        save = round(100 - year[1] / (month[1] * 12) * 100)
        verb = "Продлить" if active else "Купить"
        rub = rub_enabled()
        rows += [
            [btn(f"{verb} на месяц — {price_label('plan:month', rub)}", "pm:buy:month")],
            [btn(f"{verb} на год — {price_label('plan:year', rub)} (−{save}%)", "pm:buy:year")],
            [btn(f"👑 Навсегда — {price_label('plan:forever', rub)}", "pm:buy:forever")],
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
async def send_invoice(message: Message, product: str, currency: str | None = None) -> None:
    """Счёт на товар. Без валюты и с подключённой ЮKassa — сначала спрашиваем способ оплаты."""
    if currency is None:
        if rub_enabled() and price(product, RUB):
            await ask_method(message, product)
            return
        currency = STARS
    amount = price(product, currency)
    if amount is None:
        await message.answer("Этот товар сейчас нельзя купить таким способом 🙏")
        return
    title, description = product_title(product)
    if currency == STARS:
        await message.answer_invoice(title=title, description=description, payload=product, currency=STARS,
                                     prices=[LabeledPrice(label=title, amount=amount)])
        return
    # ЮKassa: сумма в копейках; чек — если продавец работает с онлайн-кассой
    extra = {}
    if YOOKASSA_RECEIPT:
        extra = {"need_email": True, "send_email_to_provider": True,
                 "provider_data": json.dumps(receipt(product, amount, YOOKASSA_VAT_CODE), ensure_ascii=False)}
    await message.answer_invoice(title=title, description=description, payload=product, currency=RUB,
                                 provider_token=YOOKASSA_TOKEN,
                                 prices=[LabeledPrice(label=title, amount=amount * 100)], **extra)


async def ask_method(message: Message, product: str) -> None:
    title, _ = product_title(product)
    stars, rubles = price(product, STARS), price(product, RUB)
    rows = []
    if stars:
        rows.append([btn(f"⭐ Звёздами — {fmt_price(stars)}", f"pay:xtr:{product}")])
    rows.append([btn(f"💳 Картой или СБП — {fmt_price(rubles, RUB)}", f"pay:rub:{product}")])
    await message.answer(f"<b>{title}</b>\n<blockquote>Как удобнее оплатить?</blockquote>",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(c: CallbackQuery):
    _, method, product = c.data.split(":", 2)
    currency = RUB if method == "rub" else STARS
    if currency == RUB and not rub_enabled():
        await c.answer("Оплата картой сейчас недоступна — можно звёздами ⭐", show_alert=True)
        return
    await send_invoice(c.message, product, currency)
    await c.answer()


@router.callback_query(F.data.startswith("pm:buy:"))
async def cb_buy(c: CallbackQuery):
    plan = c.data.split(":")[2]
    if plan not in PLANS:
        await c.answer()
        return
    await send_invoice(c.message, f"plan:{plan}")
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
    if rub_enabled():
        rows.append([btn(f"💳 {n} ₽", f"pm:donr:{n}") for n in RUB_DONATES[:3]])
        rows.append([btn(f"💳 {n} ₽", f"pm:donr:{n}") for n in RUB_DONATES[3:]])
    rows.append([btn("◀️ Назад", "pm:menu")])
    await c.message.edit_text(
        "💝 <b>Поддержать бота</b>\n<blockquote>Бот бесплатный и работает на энтузиазме. "
        "Звёзды помогают оплачивать сервер и добавлять новое. Спасибо! 🙏</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("pm:don:"))
async def cb_donate_pay(c: CallbackQuery):
    n = c.data.split(":")[2]
    await send_invoice(c.message, f"donate:{n}", STARS)
    await c.answer()


@router.callback_query(F.data.startswith("pm:donr:"))
async def cb_donate_rub(c: CallbackQuery):
    await send_invoice(c.message, f"donate:{c.data.split(':')[2]}", RUB)
    await c.answer()


def expected_total(product: str, currency: str) -> int | None:
    """Сколько должен заплатить пользователь в единицах Telegram: звёзды или копейки."""
    if currency == RUB and not rub_enabled():
        return None
    amount = price(product, currency) if currency in (STARS, RUB) else None
    if amount is None:
        return None
    return amount * 100 if currency == RUB else amount


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    expected = expected_total(q.invoice_payload, q.currency)
    if expected is None or q.total_amount != expected:
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
    currency = RUB if sp.currency == RUB else STARS
    amount = sp.total_amount // 100 if currency == RUB else sp.total_amount
    await db.add_purchase(m.from_user.id, product, amount, sp.telegram_payment_charge_id,
                          currency=currency, provider_charge_id=sp.provider_payment_charge_id or None)
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
            await m.bot.send_message(admin_id, f"💰 <b>+{fmt_price(amount, currency)}</b> · {escape(product)}\n"
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
