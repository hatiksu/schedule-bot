"""⏰ Авторассылка расписания: 🌙 вечером — на завтра, ☀️ утром — на сегодня, 🗓 в воскресенье — неделя.
Без Premium — одна рассылка (вечерняя или утренняя). В Premium — обе и ещё недельная."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from modules.appearance import show
from utils.core import btn, db, log, now, render, runtime
from utils.formatting import human_date, study_day, week_start
from utils.premium import PAYWALL_KB, is_premium, paywall

router = Router(name="digest")

SLOTS = {  # код: (поле, название, варианты времени)
    "e": ("digest_evening", "🌙 Вечером — на завтра", ["18:00", "19:00", "20:00", "21:00", "22:00"]),
    "m": ("digest_morning", "☀️ Утром — на сегодня", ["6:00", "6:30", "7:00", "7:30", "8:00"]),
    "w": ("digest_week", "🗓 В воскресенье — вся неделя", ["10:00", "12:00", "16:00", "18:00", "20:00"]),
}
WINDOW_MIN = 45  # если бот был выключен, догоняем рассылку в течение 45 минут, а не шлём ночью


def describe(user: dict) -> str:
    parts = []
    if user.get("digest_evening"):
        parts.append(f"вечером в {user['digest_evening']}")
    if user.get("digest_morning"):
        parts.append(f"утром в {user['digest_morning']}")
    if user.get("digest_week"):
        parts.append(f"неделя по вс в {user['digest_week']}")
    return ", ".join(parts) or "выключена"


async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid) or {}
    prem = is_premium(user)
    lines = []
    rows = []
    for code, (field, title, _) in SLOTS.items():
        val = user.get(field)
        lock = " ⭐" if code == "w" and not prem else ""
        lines.append(f"{title}{lock}: <b>{val or 'выкл'}</b>")
        rows.append([btn(f"{title.split(' — ')[0]}: {val or 'выкл'}{lock}", f"dg:slot:{code}")])
    rows.append([btn("◀️ К настройкам", "st:home")])
    text = ("⏰ <b>Рассылки расписания</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>\n\n"
            "Пришлю расписание с твоими заметками." +
            ("" if prem else "\n<i>Без Premium — одна рассылка: вечерняя или утренняя. "
                             "В ⭐ Premium — обе и ещё недельная.</i>"))
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "dg:menu")
async def cb_menu(c: CallbackQuery):
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()


OLD = {"evening": "e", "morning": "m"}  # кнопки от прошлой версии бота


@router.callback_query(F.data == "dg:off")
async def cb_off_old(c: CallbackQuery):
    for field in ("digest_evening", "digest_morning"):
        await db.set_pref(c.from_user.id, field, None)
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer("Рассылка выключена")


@router.callback_query(F.data.startswith("dg:slot:") | F.data.startswith("dg:mode:"))
async def cb_slot(c: CallbackQuery):
    code = OLD.get(c.data.split(":")[2], c.data.split(":")[2])
    if code not in SLOTS:
        await c.answer()
        return
    field, title, times = SLOTS[code]
    if code == "w" and not is_premium(await db.get_user(c.from_user.id)):
        await show(c, paywall("Расписание на неделю в воскресенье"), PAYWALL_KB)
        await c.answer()
        return
    rows, row = [], []
    for t in times:
        row.append(btn(t, f"dg:set:{code}:{t}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows += [[btn("🔕 Выключить", f"dg:set:{code}:-")], [btn("◀️ Назад", "dg:menu")]]
    await show(c, f"{title}\n\nВо сколько присылать?", InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("dg:set:"))
async def cb_set(c: CallbackQuery):
    _, _, code, t = c.data.split(":", 3)
    code = OLD.get(code, code)
    if code not in SLOTS:
        await c.answer()
        return
    uid = c.from_user.id
    user = await db.get_user(uid) or {}
    prem = is_premium(user)
    field = SLOTS[code][0]
    note = "Сохранено"
    if t == "-":
        await db.set_pref(uid, field, None)
    else:
        if code == "w" and not prem:
            await show(c, paywall("Расписание на неделю"), PAYWALL_KB)
            await c.answer()
            return
        other = {"e": "m", "m": "e"}.get(code)
        if other and not prem and user.get(SLOTS[other][0]):
            await db.set_pref(uid, SLOTS[other][0], None)  # без Premium — только одна рассылка
            note = ("Без Premium — одна рассылка, поэтому "
                    + ("утренняя" if other == "m" else "вечерняя") + " выключена. В ⭐ Premium можно обе")
        await db.set_pref(uid, field, t)
        hh, mm = map(int, t.split(":"))
        n = now()
        if n.hour * 60 + n.minute >= hh * 60 + mm:  # время сегодня уже прошло — не шлём задним числом
            await db.mark_slot(uid, code, n.date().isoformat())
    text, kb = await menu_view(uid)
    await show(c, text, kb)
    await c.answer(note, show_alert=note != "Сохранено")


# ---------- отправка ----------
async def send_digest(bot: Bot, user: dict, code: str, n: datetime) -> None:
    today = n.date()
    kind, eid, uid = user["kind"], user["target_id"], user["user_id"]
    max_date = await db.max_date()
    if code == "w":
        monday = week_start(today) + timedelta(days=7)
        if max_date and monday.isoformat() > max_date:
            await bot.send_message(uid, "🗓 <b>Расписание на неделю</b>\n<blockquote>🕸 На следующую неделю "
                                        "ещё не выложили — пришлю, как только появится.</blockquote>")
            return
        chunks, kb = await render(kind, eid, "w", monday, uid=uid)
        title = "🗓 <b>Расписание на неделю</b>"
    else:
        if code == "e":
            d = today + timedelta(days=1)
            if d.weekday() == 6:  # в субботу вечером — на понедельник
                d = study_day(d, 1)
            title = "🌙 <b>Расписание на завтра</b>" if d == today + timedelta(days=1) \
                else f"🌙 <b>Расписание на {human_date(d).lower()}</b>"
        else:
            d = today
            title = "☀️ <b>Доброе утро!</b> Расписание на сегодня"
        if max_date and d.isoformat() > max_date:
            await bot.send_message(uid, f"{title}\n<blockquote>🕸 Расписание на {d:%d.%m} ещё не выложили — "
                                        "пришлю, как только появится.</blockquote>")
            return
        chunks, kb = await render(kind, eid, "d", d, uid=uid)
    chunks[0] = f"{title}\n\n{chunks[0]}"
    for i, chunk in enumerate(chunks):
        await bot.send_message(uid, chunk, reply_markup=kb if i == len(chunks) - 1 else None)


def _allowed(user: dict) -> list[str]:
    if is_premium(user):
        return ["e", "m", "w"]
    # без Premium — одна: вечерняя важнее (если обе остались после окончания Premium)
    return ["e"] if user.get("digest_evening") else ["m"]


async def loop(bot: Bot) -> None:
    while True:
        try:
            if not runtime["maintenance"]:
                n = now()
                today = n.date().isoformat()
                cur = n.hour * 60 + n.minute
                for user in await db.digest_slot_users():
                    for code in _allowed(user):
                        t = user.get(SLOTS[code][0])
                        if not t or user.get(f"last_digest_{code}") == today:
                            continue
                        if code == "w" and n.weekday() != 6 or code == "m" and n.weekday() == 6:
                            continue
                        hh, mm = map(int, t.split(":"))
                        if not 0 <= cur - (hh * 60 + mm) <= WINDOW_MIN:
                            continue
                        await db.mark_slot(user["user_id"], code, today)
                        try:
                            await send_digest(bot, user, code, n)
                            await db.inc_digests(user["user_id"])
                            from modules.achievements import check
                            await check(bot, user["user_id"])
                        except TelegramForbiddenError:
                            pass
                        except TelegramAPIError as e:
                            log.warning("Рассылка %s: %s", user["user_id"], e)
                        await asyncio.sleep(0.05)
        except Exception:
            log.exception("Ошибка авторассылки")
        await asyncio.sleep(30)
