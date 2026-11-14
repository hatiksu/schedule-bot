"""⭐ Premium: витрина, оплата Telegram Stars или рублями через ЮKassa, пробный период, промокоды, донаты.

Звёзды (валюта XTR) — встроенная оплата Telegram, без ИП и эквайринга.
Рубли (RUB) — платёж по ссылке через API ЮKassa (карта, СБП, ЮMoney), минимум 1 ₽: бот создаёт платёж,
показывает кнопку «Оплатить» и сам проверяет статус в фоне — вебхуки и свой сервер не нужны.
Если ключей ЮKassa нет, бот работает как раньше — только звёзды.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
import httpx
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery)

from config import ADMIN_IDS, YOOKASSA_RECEIPT, YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID, YOOKASSA_VAT_CODE
from utils.core import ALL_BUTTONS, btn, db, log, now, runtime
from utils.premium import (DONATE_MIN, DONATES, FEATURES, FOREVER, PLANS, RUB, RUB_DONATES, STARS, THEMES,
                           TRIAL_DAYS, fmt_price, is_forever, is_premium, price, price_label, product_title,
                           status_text)
from utils.yookassa import YooKassa, YooKassaError, receipt_for

router = Router(name="premium")
yookassa = YooKassa(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
PENDING_TTL_HOURS = 24  # столько ждём оплату по ссылке ЮKassa


class PromoState(StatesGroup):
    code = State()


def price_of(product: str) -> int | None:
    """Сколько звёзд стоит товар (для проверки перед оплатой)."""
    return price(product, STARS)


def rub_enabled() -> bool:
    """Подключена ли оплата в рублях через API ЮKassa."""
    return yookassa.enabled


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
async def send_invoice(message: Message, product: str, currency: str | None = None, uid: int | None = None) -> None:
    """Оплата товара. Без валюты и с подключённой ЮKassa — сначала спрашиваем способ оплаты.

    uid — кто покупает (у сообщения бота from_user — сам бот, поэтому id передаём явно)."""
    if currency is None:
        if rub_enabled() and price(product, RUB):
            await ask_method(message, product)
            return
        currency = STARS
    amount = price(product, currency)
    if amount is None:
        await message.answer("Этот товар сейчас нельзя купить таким способом 🙏")
        return
    if currency == RUB:
        await start_rub_payment(message, uid or message.chat.id, product, amount)
        return
    title, description = product_title(product)
    try:
        await message.answer_invoice(title=title, description=description, payload=product, currency=STARS,
                                     prices=[LabeledPrice(label=title, amount=amount)])
    except TelegramBadRequest:
        # Например, слишком большая сумма для одного платежа звёздами
        await message.answer(f"Telegram не принимает {fmt_price(amount)} одним платежом — попробуй сумму поменьше 🙏")


async def ask_method(message: Message, product: str) -> None:
    title, _ = product_title(product)
    stars, rubles = price(product, STARS), price(product, RUB)
    rows = []
    if stars:
        rows.append([btn(f"⭐ Звёздами — {fmt_price(stars)}", f"pay:xtr:{product}")])
    rows.append([btn(f"💳 Картой, СБП или ЮMoney — {fmt_price(rubles, RUB)}", f"pay:rub:{product}")])
    await message.answer(f"<b>{title}</b>\n<blockquote>Как удобнее оплатить?</blockquote>",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(c: CallbackQuery, state: FSMContext):
    _, method, rest = c.data.split(":", 2)
    if method == "chk":
        await check_rub_payment(c, rest)
        return
    currency = RUB if method == "rub" else STARS
    if currency == RUB and not rub_enabled():
        await c.answer("Оплата картой сейчас недоступна — можно звёздами ⭐", show_alert=True)
        return
    if currency == RUB and YOOKASSA_RECEIPT and not await receipt_email(c.from_user.id):
        await ask_email(c, state, rest)
        return
    await send_invoice(c.message, rest, currency, uid=c.from_user.id)
    await c.answer()


# ---------- 💳 рубли через API ЮKassa ----------
class EmailState(StatesGroup):
    email = State()


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


async def receipt_email(uid: int) -> str | None:
    user = await db.get_user(uid) or {}
    return user.get("receipt_email")


async def ask_email(c: CallbackQuery, state: FSMContext, product: str) -> None:
    await state.set_state(EmailState.email)
    await state.update_data(product=product)
    await c.message.answer("🧾 Куда прислать чек? Отправь почту сообщением — спрошу только один раз.")
    await c.answer()


@router.message(EmailState.email, F.text, ~F.text.in_(ALL_BUTTONS))
async def got_email(m: Message, state: FSMContext):
    email = m.text.strip()
    if not EMAIL_RE.match(email) or len(email) > 100:
        await m.answer("Похоже, это не почта 🙂 Пример: name@mail.ru")
        return
    product = (await state.get_data()).get("product", "")
    await state.clear()
    await db.set_pref(m.from_user.id, "receipt_email", email)
    await send_invoice(m, product, RUB, uid=m.from_user.id)


async def start_rub_payment(message: Message, uid: int, product: str, amount: int) -> None:
    title, _ = product_title(product)
    extra = None
    if YOOKASSA_RECEIPT:
        email = await receipt_email(uid)
        if not email:
            await message.answer("🧾 Сначала нужна почта для чека — нажми кнопку оплаты ещё раз.")
            return
        extra = receipt_for(title, amount, email, YOOKASSA_VAT_CODE)
    bot_link = f"https://t.me/{runtime['bot_username']}" if runtime.get("bot_username") else "https://t.me"
    try:
        payment = await yookassa.create_payment(amount, title, bot_link, {"user_id": uid, "product": product}, extra)
    except (YooKassaError, httpx.HTTPError) as e:
        log.warning("ЮKassa: не удалось создать платёж: %s", e)
        await message.answer("Не получилось создать платёж 😔 Попробуй ещё раз чуть позже или оплати звёздами ⭐")
        return
    await db.add_pending(payment.id, uid, product, amount, message.chat.id)
    await message.answer(
        f"💳 <b>{title} — {fmt_price(amount, RUB)}</b>\n<blockquote>Оплата на странице ЮKassa: карта, СБП или ЮMoney. "
        "Как только деньги придут, я сам всё включу — обычно это занимает до минуты.</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {fmt_price(amount, RUB)}", url=payment.confirmation_url)],
            [btn("🔄 Я оплатил — проверить", f"pay:chk:{payment.id}")],
        ]))


async def settle(bot: Bot, pending: dict, status: str) -> bool:
    """Закрывает платёж ЮKassa по его статусу. True — если платёж завершён (успешно или нет)."""
    if status == "succeeded":
        if not await db.finish_pending(pending["id"], "succeeded"):
            return True  # уже выдали (например, проверка из кнопки и из фона одновременно)
        await fulfill(bot, pending["user_id"], pending["chat_id"], pending["product"], pending["amount"], RUB,
                      charge_id=pending["id"], provider_charge_id=pending["id"])
        return True
    if status == "canceled":
        if await db.finish_pending(pending["id"], "canceled"):
            try:
                await bot.send_message(pending["chat_id"], "💳 Платёж отменён или не прошёл — деньги не списаны. "
                                                           "Можно попробовать ещё раз 🙏")
            except TelegramAPIError:
                pass
        return True
    return False


async def check_rub_payment(c: CallbackQuery, payment_id: str) -> None:
    pending = await db.get_pending(payment_id)
    if not pending or pending["user_id"] != c.from_user.id:
        await c.answer("Платёж не найден", show_alert=True)
        return
    if pending["status"] == "succeeded":
        await c.answer("✅ Уже оплачено — всё включено", show_alert=True)
        return
    try:
        payment = await yookassa.get_payment(payment_id)
    except (YooKassaError, httpx.HTTPError):
        await c.answer("ЮKassa не отвечает — проверю сам чуть позже", show_alert=True)
        return
    if not await settle(c.bot, pending, payment.status):
        await c.answer("⏳ Оплата ещё не пришла. Если уже заплатил — подожди минуту, я проверю сам.", show_alert=True)
        return
    await c.answer()


async def payments_loop(bot: Bot) -> None:
    """Фоновая проверка неоплаченных платежей ЮKassa: выдаём покупку, как только деньги пришли."""
    if not rub_enabled():
        return
    while True:
        try:
            for pending in await db.pending_payments():
                age = now().replace(tzinfo=None) - datetime.strptime(pending["created_at"], "%Y-%m-%d %H:%M:%S")
                try:
                    payment = await yookassa.get_payment(pending["id"])
                except (YooKassaError, httpx.HTTPError) as e:
                    log.warning("ЮKassa: статус %s: %s", pending["id"], e)
                    continue
                if not await settle(bot, pending, payment.status) and age > timedelta(hours=PENDING_TTL_HOURS):
                    await db.finish_pending(pending["id"], "expired")  # ссылку так и не оплатили
                await asyncio.sleep(0.3)
        except Exception:
            log.exception("Ошибка проверки платежей ЮKassa")
        await asyncio.sleep(20)


# ---------- витрина покупок ----------
@router.callback_query(F.data.startswith("pm:buy:"))
async def cb_buy(c: CallbackQuery):
    plan = c.data.split(":")[2]
    if plan not in PLANS:
        await c.answer()
        return
    await send_invoice(c.message, f"plan:{plan}", uid=c.from_user.id)
    await c.answer()


@router.callback_query(F.data == "pm:donate")
async def cb_donate(c: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = [[btn(f"{n} ⭐", f"pm:don:{n}") for n in DONATES[:3]], [btn(f"{n} ⭐", f"pm:don:{n}") for n in DONATES[3:]]]
    if rub_enabled():
        rows.append([btn(f"💳 {n} ₽", f"pm:donr:{n}") for n in RUB_DONATES[:3]])
        rows.append([btn(f"💳 {n} ₽", f"pm:donr:{n}") for n in RUB_DONATES[3:]])
    rows.append([btn("✍️ Своя сумма", "pm:donc")])
    rows.append([btn("◀️ Назад", "pm:menu")])
    rub = " или от 1 ₽ картой" if rub_enabled() else ""
    await c.message.edit_text(
        "💝 <b>Поддержать бота</b>\n<blockquote>Бот бесплатный и работает на энтузиазме. "
        "Любая сумма помогает оплачивать сервер и добавлять новое. Спасибо! 🙏</blockquote>\n"
        f"От 1 ⭐{rub} — сколько не жалко.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


class DonateState(StatesGroup):
    amount = State()


@router.callback_query(F.data == "pm:donc")
async def cb_donate_custom(c: CallbackQuery, state: FSMContext):
    await state.set_state(DonateState.amount)
    hint = "например <code>7</code> — звёзды, <code>150 р</code> — рубли" if rub_enabled() else "например <code>7</code>"
    await c.message.edit_text(f"✍️ Напиши сумму сообщением — любую, от 1 ({hint})",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("◀️ Назад", "pm:donate")]]))
    await c.answer()


def parse_donation(text: str, rub_allowed: bool) -> tuple[int, str] | None:
    """«50» → (50, звёзды); «150 р», «150₽», «150 руб» → (150, рубли). None — не сумма."""
    m = re.fullmatch(r"\s*(\d{1,9})\s*(⭐|звезд\w*|зв|stars?|₽|р|р\.|руб\w*|rub)?\s*", text.lower().replace("ё", "е"))
    if not m or int(m.group(1)) < DONATE_MIN:
        return None
    unit = m.group(2) or ""
    is_rub = unit.startswith(("₽", "р", "rub"))
    if is_rub and not rub_allowed:
        return None
    return int(m.group(1)), RUB if is_rub else STARS


@router.message(DonateState.amount, F.text, ~F.text.in_(ALL_BUTTONS))
async def got_donation(m: Message, state: FSMContext):
    parsed = parse_donation(m.text, rub_enabled())
    if not parsed:
        await m.answer("Нужно целое число от 1 🙂" + (" Для рублей добавь «р»: <code>150 р</code>" if rub_enabled() else ""))
        return
    await state.clear()
    amount, currency = parsed
    await send_invoice(m, f"donate:{amount}", currency, uid=m.from_user.id)


@router.callback_query(F.data.startswith("pm:don:"))
async def cb_donate_pay(c: CallbackQuery):
    await send_invoice(c.message, f"donate:{c.data.split(':')[2]}", STARS, uid=c.from_user.id)
    await c.answer()


@router.callback_query(F.data.startswith("pm:donr:"))
async def cb_donate_rub(c: CallbackQuery, state: FSMContext):
    product = f"donate:{c.data.split(':')[2]}"
    if YOOKASSA_RECEIPT and not await receipt_email(c.from_user.id):
        await ask_email(c, state, product)
        return
    await send_invoice(c.message, product, RUB, uid=c.from_user.id)
    await c.answer()


# ---------- звёзды: проверка и зачисление ----------
def expected_total(product: str, currency: str) -> int | None:
    """Сколько звёзд должен заплатить пользователь (счета Telegram у нас только в звёздах)."""
    return price(product, STARS) if currency == STARS else None


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


async def fulfill(bot: Bot, uid: int, chat_id: int, product: str, amount: int, currency: str,
                  charge_id: str, provider_charge_id: str | None = None) -> None:
    """Общее для звёзд и рублей: записать покупку, выдать товар, поблагодарить, сообщить админам."""
    await db.add_purchase(uid, product, amount, charge_id, currency=currency, provider_charge_id=provider_charge_id)
    if product.startswith("gift:"):
        from modules.gifts import after_purchase
        await after_purchase(bot, chat_id, uid, product.split(":")[1])
    else:
        text = await apply_purchase(uid, product)
        kb = _after_kb() if not product.startswith("donate") else None
        await bot.send_message(chat_id, f"🎉 Оплата прошла!\n<blockquote>{text}</blockquote>", reply_markup=kb)
    from modules.achievements import check
    await check(bot, uid)
    user = await db.get_user(uid) or {}
    who = escape(user.get("full_name") or str(uid))
    uname = f" @{escape(user['username'])}" if user.get("username") else ""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"💰 <b>+{fmt_price(amount, currency)}</b> · {escape(product)}\n"
                                             f"от {who}{uname} · <code>{uid}</code>", disable_notification=True)
        except TelegramAPIError:
            pass


@router.message(F.successful_payment)
async def got_payment(m: Message):
    sp = m.successful_payment
    await fulfill(m.bot, m.from_user.id, m.chat.id, sp.invoice_payload, sp.total_amount, STARS,
                  charge_id=sp.telegram_payment_charge_id)


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
