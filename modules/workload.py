"""📊 Нагрузка: пары, академ. часы, время — за неделю или месяц, по предметам и группам."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from utils.core import ALL_BUTTONS, BTN_LOAD, btn, db, now, require_user
from utils.formatting import KIND_ICON, format_workload, week_start

router = Router(name="workload")
NOT_BUTTON = ~F.text.in_(ALL_BUTTONS)


class LoadState(StatesGroup):
    query = State()


PERIODS = {"w0": "Эта неделя", "w1": "След. неделя", "m0": "Этот месяц", "m-1": "Прошлый месяц"}


def _period(code: str) -> tuple[date, date]:
    today = now().date()
    if code.startswith("w"):
        start = week_start(today) + timedelta(days=7 * int(code[1:]))
        return start, start + timedelta(days=6)
    shift = int(code[1:])
    y, mth = today.year, today.month + shift
    while mth < 1:
        mth += 12
        y -= 1
    return date(y, mth, 1), date(y, mth, calendar.monthrange(y, mth)[1])


async def load_view(kind: str, eid: int, code: str) -> tuple[str, InlineKeyboardMarkup]:
    d1, d2 = _period(code)
    rows = await db.lessons(kind, eid, d1.isoformat(), d2.isoformat())
    name = await db.entity_name(kind, eid) or "?"
    text = format_workload(kind, name, PERIODS[code], d1, d2, rows, await db.max_date())
    buttons = [btn(("• " if c == code else "") + label, f"ld:{kind}:{eid}:{c}") for c, label in PERIODS.items()]
    kb = InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:],
                                               [btn("👤 Другой преподаватель / группа", "ld:other")]])
    return text, kb


@router.message(F.text == BTN_LOAD)
async def load_cmd(m: Message, state: FSMContext):
    await state.clear()
    user = await require_user(m)
    if user:
        text, kb = await load_view(user["kind"], user["target_id"], "w0")
        await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ld:other")
async def cb_load_other(c: CallbackQuery, state: FSMContext):
    await state.set_state(LoadState.query)
    await c.message.answer("📊 Чью нагрузку посмотреть?\n<blockquote>Напиши фамилию или группу</blockquote>")
    await c.answer()


@router.message(LoadState.query, F.text, NOT_BUTTON)
async def load_query(m: Message, state: FSMContext):
    found = await db.search(m.text, kinds=("t", "g"), limit=10)
    if not found:
        await m.answer("🤔 Не нашёл. Попробуй ещё раз.")
        return
    await state.clear()
    if len(found) == 1:
        k, i, _ = found[0]
        text, kb = await load_view(k, i, "w0")
        await m.answer(text, reply_markup=kb)
    else:
        rows = [[btn(f"{KIND_ICON[k]} {n}", f"ld:{k}:{i}:w0")] for k, i, n in found]
        await m.answer("Кого показать?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("ld:"))
async def cb_load(c: CallbackQuery):
    _, kind, eid, code = c.data.split(":")
    text, kb = await load_view(kind, int(eid), code)
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await c.answer()
