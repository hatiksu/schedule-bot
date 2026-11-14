from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from utils.core import ALL_BUTTONS, BTN_WHERE, btn, db, now
from utils.formatting import format_where

router = Router(name="where")
NOT_BUTTON = ~F.text.in_(ALL_BUTTONS)


class WhereState(StatesGroup):
    query = State()


async def where_view(eid: int) -> tuple[str, InlineKeyboardMarkup]:
    n = now()
    today = n.date()
    name = await db.entity_name("t", eid) or "?"
    rows = await db.lessons("t", eid, today.isoformat(), today.isoformat())
    next_day, next_rows = None, []
    max_date = await db.max_date()
    d = today
    for _ in range(14):
        d += timedelta(days=1)
        if max_date and d.isoformat() > max_date:
            break
        found = await db.lessons("t", eid, d.isoformat(), d.isoformat())
        if found:
            next_day, next_rows = d, found
            break
    text = format_where(name, n, rows, next_day, next_rows)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔄 Обновить", f"wh:{eid}"), btn("📅 Расписание", f"v:t:{eid}:d:t")],
    ])
    return text, kb


@router.message(F.text == BTN_WHERE)
async def where_cmd(m: Message, state: FSMContext):
    await state.set_state(WhereState.query)
    await m.answer("📍 <b>Где сейчас преподаватель?</b>\n<blockquote>Напиши фамилию</blockquote>")


@router.message(WhereState.query, F.text, NOT_BUTTON)
async def where_query(m: Message, state: FSMContext):
    found = await db.search(m.text, kinds=("t",), limit=10)
    if not found:
        await m.answer("🤔 Не нашёл такого преподавателя. Попробуй ещё раз.")
        return
    await state.clear()
    if len(found) == 1:
        text, kb = await where_view(found[0][1])
        await m.answer(text, reply_markup=kb)
    else:
        rows = [[btn(f"👤 {n}", f"wh:{i}")] for _, i, n in found]
        await m.answer("Кого ищем?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("wh:"))
async def cb_where(c: CallbackQuery):
    text, kb = await where_view(int(c.data.split(":")[1]))
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await c.answer("Обновлено")
