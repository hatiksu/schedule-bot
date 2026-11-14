"""Общее для всех модулей: база, время, клавиатуры, показ расписания."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

from config import DB_PATH, TZ
from utils.db import DB
from utils.formatting import (KIND_ICON, days_word, format_day, format_week, short_date, split_text,
                        study_day, week_start)

log = logging.getLogger("schedule_bot")
db = DB(DB_PATH, TZ)
runtime = {"maintenance": False, "bot_username": None}  # быстрые флаги без запроса к БД


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


# ---------- кнопки меню ----------
BTN_TODAY, BTN_TOMORROW = "📅 Сегодня", "➡️ Завтра"
BTN_WEEK, BTN_NEXT = "🗓 Неделя", "⏭ След. неделя"
BTN_SEARCH, BTN_ROOMS, BTN_BELLS = "🔎 Поиск", "🏫 Аудитории", "⏰ Звонки"
BTN_WHERE, BTN_LOAD, BTN_SETTINGS = "📍 Где препод", "📊 Нагрузка", "⚙️ Настройки"
MENU_BUTTONS = {BTN_TODAY, BTN_TOMORROW, BTN_WEEK, BTN_NEXT}
ALL_BUTTONS = MENU_BUTTONS | {BTN_SEARCH, BTN_ROOMS, BTN_BELLS, BTN_WHERE, BTN_LOAD, BTN_SETTINGS}

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW)],
        [KeyboardButton(text=BTN_WEEK), KeyboardButton(text=BTN_NEXT)],
        [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_ROOMS), KeyboardButton(text=BTN_BELLS)],
        [KeyboardButton(text=BTN_WHERE), KeyboardButton(text=BTN_LOAD), KeyboardButton(text=BTN_SETTINGS)],
    ],
    resize_keyboard=True,
    input_field_placeholder="Группа, фамилия или аудитория…",
)
ROLE_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🎓 Я студент", callback_data="role:g"),
    InlineKeyboardButton(text="👨‍🏫 Я преподаватель", callback_data="role:t"),
]])


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


# ---------- навигация под расписанием ----------
# v:<kind>:<id>:<d|w>:<YYYY-MM-DD | t>   («t» = сегодня)
def nav_kb(kind: str, eid: int, scope: str, d: date, private: bool = True,
           fav: bool | None = None) -> InlineKeyboardMarkup:
    """fav: None — кнопку избранного не показываем (своё расписание), True/False — в избранном или нет."""
    base = f"v:{kind}:{eid}"
    if scope == "d":
        prev, nxt = study_day(d, -1), study_day(d, 1)
        rows = [[btn(f"◀️ {short_date(prev)}", f"{base}:d:{prev}"),
                 btn(f"{short_date(nxt)} ▶️", f"{base}:d:{nxt}")]]
    else:
        rows = [[btn("◀️ Пред. неделя", f"{base}:w:{d - timedelta(days=7)}"),
                 btn("След. неделя ▶️", f"{base}:w:{d + timedelta(days=7)}")]]
    rows.append([btn("📅 Сегодня", f"{base}:d:t"), btn("🗓 Неделя", f"{base}:w:{week_start(d)}")])
    if private:  # в чужих чатах (inline-режим) заметки и картинки не показываем
        extra = [btn("🖼 Картинкой", f"img:{kind}:{eid}:{scope}:{d}")]
        if scope == "d":
            extra.insert(0, btn("📝 Заметка", f"nt:{kind}:{eid}:{d}"))
        if fav is not None:
            extra.append(btn("★" if fav else "☆", f"fav:t:{kind}:{eid}:{scope}:{d}"))
        rows.append(extra)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_kb(found: list[tuple], prefix: str, suffix: str = "") -> InlineKeyboardMarkup:
    rows, row = [], []
    for kind, eid, name in found:
        row.append(btn(f"{KIND_ICON[kind]} {name}", f"{prefix}:{kind}:{eid}{suffix}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def chosen_name(user: dict) -> str:
    """Название группы / ФИО препода: с сайта, а если его там уже нет — из сохранённого в БД."""
    return (await db.entity_name(user["kind"], user["target_id"])
            or user.get("target_name") or "не найдено на сайте")


async def require_user(m: Message) -> dict | None:
    user = await db.get_user(m.from_user.id)
    if not user or not user["kind"]:
        await m.answer("Сначала выбери группу или преподавателя — /start")
        return None
    return user


# ---------- отсчёты: выходные, каникулы, «завтра пар нет» ----------
async def holiday() -> tuple[date, date | None, str] | None:
    start = await db.get_meta("holiday_start")
    if not start:
        return None
    end = await db.get_meta("holiday_end")
    return (date.fromisoformat(start), date.fromisoformat(end) if end else None,
            await db.get_meta("holiday_name") or "каникул")


async def day_extras(kind: str, eid: int, d: date) -> list[str]:
    today = now().date()
    lines = []
    if d == today:
        tomorrow = today + timedelta(days=1)
        max_date = await db.max_date()
        if tomorrow.weekday() == 6:
            lines.append("🌤 <b>Завтра выходной</b> 🎉")
        elif max_date and tomorrow.isoformat() <= max_date and not await db.lessons(
                kind, eid, tomorrow.isoformat(), tomorrow.isoformat()):
            lines.append("🎉 <b>Завтра пар нет!</b>")
        elif today.weekday() < 5:
            lines.append(f"🌤 До выходного: {days_word(6 - today.weekday())}")
    h = await holiday()
    if h:
        start, end, name = h
        if d < start:
            lines.append(f"🏖 До {name}: <b>{days_word((start - d).days)}</b>")
        elif end is None or d <= end:
            lines.append(f"🏖 Сейчас {name}" + (f" — до {end:%d.%m}" if end else ""))
    return lines


# ---------- показ расписания ----------
async def render(kind: str, eid: int, scope: str, d: date, uid: int | None = None,
                 private: bool = True) -> tuple[list[str], InlineKeyboardMarkup]:
    from utils.premium import icons_for, style_for  # здесь, чтобы не было циклического импорта
    n = now()
    name = await db.entity_name(kind, eid) or "?"
    updated = await db.get_meta("site_updated")
    max_date = await db.max_date()
    user = await db.get_user(uid) if uid and private else None
    icons, style = icons_for(user), style_for(user)
    fav = None
    if user and user.get("kind") and (user["kind"], user["target_id"]) != (kind, eid):
        fav = await db.is_favorite(uid, kind, eid)
    if scope == "d":
        rows = await db.lessons(kind, eid, d.isoformat(), d.isoformat())
        notes = {}
        if user:
            notes = {p: t for (_, p), t in (await db.notes(uid, kind, eid, d.isoformat(), d.isoformat())).items()}
        text = format_day(kind, name, d, rows, n, updated, max_date, notes, await day_extras(kind, eid, d),
                          style, icons)
    else:
        d = week_start(d)
        end = (d + timedelta(days=6)).isoformat()
        rows = await db.lessons(kind, eid, d.isoformat(), end)
        notes = await db.notes(uid, kind, eid, d.isoformat(), end) if user else {}
        text = format_week(kind, name, d, rows, n, updated, max_date, notes, icons)
    return split_text(text), nav_kb(kind, eid, scope, d, private, fav)


async def send_schedule(message: Message, kind: str, eid: int, scope: str, d: date,
                        uid: int | None = None) -> None:
    chunks, kb = await render(kind, eid, scope, d, uid)
    for i, chunk in enumerate(chunks):
        await message.answer(chunk, reply_markup=kb if i == len(chunks) - 1 else None)


def resolve(mode: str) -> tuple[str, date]:
    today = now().date()
    if mode == BTN_TODAY:
        return "d", today
    if mode == BTN_TOMORROW:
        return "d", study_day(today, 1)
    monday = week_start(today)
    if today.weekday() == 6:  # в воскресенье «неделя» — уже следующая
        monday += timedelta(days=7)
    if mode == BTN_NEXT:
        monday += timedelta(days=7)
    return "w", monday
