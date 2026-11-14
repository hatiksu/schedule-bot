from __future__ import annotations

import asyncio
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from modules.appearance import show
from utils.core import btn, db, log, now
from utils.formatting import _merge, _times
from utils.premium import PAYWALL_KB, icons_for, is_premium, paywall

router = Router(name="reminders")
OPTIONS = [5, 10, 15, 30]
NOTE_TIME = (7, 0)


async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid) or {}
    before = user.get("remind_before")
    first = bool(user.get("remind_first_only"))
    notes_on = bool(user.get("note_remind", 1))
    state = f"за <b>{before} мин</b> до {'первой пары' if first else 'каждой пары'}" if before else "<b>выключено</b>"
    text = ("⏳ <b>Напоминания</b>\n\n<blockquote>"
            f"🔔 Перед парой: {state}\n"
            f"📝 О заметках утром ({NOTE_TIME[0]}:{NOTE_TIME[1]:02d}): <b>{'включено' if notes_on else 'выключено'}</b>"
            "</blockquote>\n\nПришлю предмет, аудиторию и твою заметку к паре.")
    row = [btn(("✅ " if before == m else "") + f"{m} мин", f"rm:b:{m}") for m in OPTIONS]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        row,
        [btn(("✅ " if not before else "") + "🔕 Не напоминать", "rm:b:0")],
        [btn(("☑️" if first else "✅") + " Каждая пара", "rm:f:0"),
         btn(("✅" if first else "☑️") + " Только первая", "rm:f:1")],
        [btn(("🔕 Не напоминать о заметках" if notes_on else "🔔 Напоминать о заметках"), "rm:n")],
        [btn("◀️ К настройкам", "st:home")],
    ])
    return text, kb


@router.callback_query(F.data == "rm:menu")
async def cb_menu(c: CallbackQuery):
    user = await db.get_user(c.from_user.id)
    if not is_premium(user):
        await show(c, paywall("Напоминание перед парой"), PAYWALL_KB)
        await c.answer()
        return
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("rm:"))
async def cb_set(c: CallbackQuery):
    if not is_premium(await db.get_user(c.from_user.id)):
        await show(c, paywall("Напоминания"), PAYWALL_KB)
        await c.answer()
        return
    parts = c.data.split(":")
    if parts[1] == "b":
        await db.set_pref(c.from_user.id, "remind_before", int(parts[2]) or None)
    elif parts[1] == "f":
        await db.set_pref(c.from_user.id, "remind_first_only", int(parts[2]))
    elif parts[1] == "n":
        user = await db.get_user(c.from_user.id)
        await db.set_pref(c.from_user.id, "note_remind", 0 if user.get("note_remind", 1) else 1)
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer("Сохранено")


_sent: set[tuple] = set()


async def _pair_reminders(bot: Bot, n: datetime) -> None:
    today = n.date().isoformat()
    cache: dict[tuple, list] = {}
    for user in await db.reminder_users(n.strftime("%Y-%m-%d %H:%M:%S")):
        key = (user["kind"], user["target_id"])
        if key not in cache:
            cache[key] = _merge(await db.lessons(*key, today, today))
        items = cache[key][:1] if user["remind_first_only"] else cache[key]
        for r in items:
            tt = _times(r["time"])
            if not tt:
                continue
            start = datetime.combine(n.date(), tt[0])
            left = (start - n).total_seconds() / 60
            mark = (user["user_id"], today, r["pair"])
            if not (user["remind_before"] - 1.5 < left <= user["remind_before"]) or mark in _sent:
                continue
            _sent.add(mark)
            icons = icons_for(user)
            ic = lambda k, icons=icons: f"{icons.get(k)} " if icons.get(k) else ""
            meta = []
            if r["rooms"] and user["kind"] != "r":
                meta.append(f"{ic('room')}<b>{escape(r['rooms'])}</b>")
            groups = sorted({g for g in r["groups"] if g})
            if user["kind"] == "t" and groups:
                meta.append(ic("group") + escape(", ".join(groups)))
            if user["kind"] == "g" and r["teachers"]:
                meta.append(f"{ic('teacher')}{escape(r['teachers'])}")
            note = (await db.notes(user["user_id"], user["kind"], user["target_id"], today, today)).get(
                (today, r["pair"]))
            text = (f"⏳ <b>Через {round(left)} мин</b> — {r['pair']} пара · {tt[0]:%H:%M}\n"
                    f"<blockquote>{ic('subj')}<b>{escape(r['subject'])}</b>"
                    + (f"\n{'  ·  '.join(meta)}" if meta else "")
                    + (f"\n{ic('note')}<i>{escape(note)}</i>" if note else "") + "</blockquote>")
            try:
                await bot.send_message(user["user_id"], text)
            except TelegramAPIError as e:
                log.debug("Напоминание %s: %s", user["user_id"], e)
            await asyncio.sleep(0.05)
    if len(_sent) > 20000:
        _sent.clear()


async def _note_reminders(bot: Bot, n: datetime) -> None:
    if (n.hour, n.minute) < NOTE_TIME or n.hour > NOTE_TIME[0] + 2:
        return
    today = n.date().isoformat()
    by_user: dict[int, list] = {}
    for note in await db.notes_to_remind(today, n.strftime("%Y-%m-%d %H:%M:%S")):
        by_user.setdefault(note["user_id"], []).append(note)
    for uid, notes in by_user.items():
        await db.mark_notes_reminded(uid, today)
        lines = "\n".join(f"<b>{x['pair']} пара</b> — {escape(x['text'])}" for x in notes)
        try:
            await bot.send_message(uid, f"📝 <b>Не забудь сегодня</b>\n<blockquote>{lines}</blockquote>")
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)


async def loop(bot: Bot) -> None:
    while True:
        try:
            n = now()
            if n.weekday() != 6:
                await _pair_reminders(bot, n)
                await _note_reminders(bot, n)
        except Exception:
            log.exception("Ошибка напоминаний")
        await asyncio.sleep(20)
