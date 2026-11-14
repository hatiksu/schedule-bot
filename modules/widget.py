from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from modules.appearance import show
from utils.core import btn, db, log, now
from utils.formatting import KIND_ICON, WD_SHORT, _merge, _times, fmt_minutes, minutes_between, study_day
from utils.premium import PAYWALL_KB, is_premium, paywall

router = Router(name="widget")


def _round5(m: int) -> int:
    return max(5, (m + 4) // 5 * 5)


async def widget_text(user: dict, n: datetime) -> str:
    kind, eid = user["kind"], user["target_id"]
    name = escape(await db.entity_name(kind, eid) or user.get("target_name") or "?")
    d = n.date()
    head = f"📌 <b>{KIND_ICON[kind]} {name}</b> · {WD_SHORT[d.weekday()]} {d:%d.%m}"
    items = [] if d.weekday() == 6 else _merge(await db.lessons(kind, eid, d.isoformat(), d.isoformat()))
    t = n.time()
    lines, status = [], ""
    for r in items:
        tt = _times(r["time"])
        meta = f" · {escape(r['rooms'])}" if r["rooms"] and kind != "r" else ""
        line = f"{r['pair']}  {tt[0]:%H:%M}  {escape(r['subject'])}{meta}" if tt else f"{r['pair']}  {escape(r['subject'])}"
        if tt and t > tt[1]:
            lines.append(f"✔️ <s>{line}</s>")
        elif tt and tt[0] <= t <= tt[1]:
            lines.append(f"🟢 <b>{line}</b>")
            status = f"🟢 Идёт {r['pair']} пара · ещё ~{fmt_minutes(_round5(minutes_between(t, tt[1])))}"
        else:
            if not status and tt:
                status = f"⏳ Следующая — {r['pair']} пара через ~{fmt_minutes(_round5(minutes_between(t, tt[0])))}"
            lines.append(f"▫️ {line}")
    if items and not status:
        status = "🌙 Пары на сегодня закончились"
    if not items:
        status = "🌤 Сегодня выходной" if d.weekday() == 6 else "😌 Сегодня пар нет"
    body = f"\n<blockquote>{chr(10).join(lines)}</blockquote>" if lines else ""
    tail = ""
    if not items or status.startswith("🌙"):
        nd = study_day(d, 1)
        nitems = _merge(await db.lessons(kind, eid, nd.isoformat(), nd.isoformat()))
        if nitems:
            r = nitems[0]
            tt = _times(r["time"])
            tail = (f"\n\n➡️ <b>{WD_SHORT[nd.weekday()]} {nd:%d.%m}</b>: {len(nitems)} пар(ы), "
                    f"первая — {r['pair']} пара{f' в {tt[0]:%H:%M}' if tt else ''}, {escape(r['subject'])}")
    return f"{head}\n{status}{body}{tail}\n\n<i>📌 Обновляется само</i>"


async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid) or {}
    on = bool(user.get("widget_msg_id"))
    text = ("📱 <b>Виджет дня</b>\n<blockquote>Закреплённое сообщение вверху чата с ботом. Само обновляется "
            "весь день: что прошло, что идёт и сколько осталось, что дальше. Вечером показывает завтра.</blockquote>"
            f"\n\nСейчас: <b>{'включён' if on else 'выключен'}</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔕 Выключить виджет" if on else "📌 Включить виджет", "wg:off" if on else "wg:on")],
        [btn("◀️ К настройкам", "st:home")]])
    return text, kb


@router.message(Command("widget"))
async def cmd_widget(m: Message):
    if not is_premium(await db.get_user(m.from_user.id)):
        await m.answer(paywall("Виджет дня"), reply_markup=PAYWALL_KB)
        return
    text, kb = await menu_view(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "wg:menu")
async def cb_menu(c: CallbackQuery):
    if not is_premium(await db.get_user(c.from_user.id)):
        await show(c, paywall("Виджет дня"), PAYWALL_KB)
        await c.answer()
        return
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data == "wg:on")
async def cb_on(c: CallbackQuery):
    user = await db.get_user(c.from_user.id)
    if not is_premium(user) or not user.get("kind"):
        await show(c, paywall("Виджет дня"), PAYWALL_KB)
        await c.answer()
        return
    text = await widget_text(user, now())
    msg = await c.bot.send_message(c.from_user.id, text)
    try:
        await c.bot.pin_chat_message(c.from_user.id, msg.message_id, disable_notification=True)
    except TelegramAPIError:
        pass
    await db.set_pref(c.from_user.id, "widget_msg_id", msg.message_id)
    await db.set_pref(c.from_user.id, "widget_hash", hashlib.md5(text.encode()).hexdigest())
    await c.answer("📌 Виджет закреплён вверху чата")
    t, kb = await menu_view(c.from_user.id)
    await show(c, t, kb)


@router.callback_query(F.data == "wg:off")
async def cb_off(c: CallbackQuery):
    user = await db.get_user(c.from_user.id) or {}
    if user.get("widget_msg_id"):
        try:
            await c.bot.unpin_chat_message(c.from_user.id, message_id=user["widget_msg_id"])
        except TelegramAPIError:
            pass
    await db.set_pref(c.from_user.id, "widget_msg_id", None)
    await c.answer("Виджет выключен")
    t, kb = await menu_view(c.from_user.id)
    await show(c, t, kb)


async def loop(bot: Bot) -> None:
    while True:
        try:
            n = now()
            for user in await db.widget_users(n.strftime("%Y-%m-%d %H:%M:%S")):
                text = await widget_text(user, n)
                h = hashlib.md5(text.encode()).hexdigest()
                if h == user.get("widget_hash"):
                    continue
                try:
                    await bot.edit_message_text(text, chat_id=user["user_id"], message_id=user["widget_msg_id"])
                    await db.set_pref(user["user_id"], "widget_hash", h)
                except TelegramBadRequest as e:
                    if "not modified" in str(e):
                        await db.set_pref(user["user_id"], "widget_hash", h)
                    else:
                        await db.set_pref(user["user_id"], "widget_msg_id", None)
                except TelegramAPIError:
                    await db.set_pref(user["user_id"], "widget_msg_id", None)
                await asyncio.sleep(0.05)
        except Exception:
            log.exception("Ошибка виджета")
        await asyncio.sleep(60)


