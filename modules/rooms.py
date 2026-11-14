from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from utils.core import BTN_ROOMS, btn, db, now
from utils.formatting import _times, format_free_rooms, short_date, study_day

router = Router(name="rooms")

async def _bells_parsed(d: date) -> dict[int, tuple]:
    return {p: tt for p, s in (await db.bells(d.isoformat())).items() if (tt := _times(s))}


async def _default_slot() -> tuple[date, int]:
    n = now()
    d = n.date()
    bells = await _bells_parsed(d)
    if d.weekday() != 6 and bells:
        t = n.time()
        for p in sorted(bells):
            if t <= bells[p][1]:
                return d, p
    nd = study_day(d, 1)
    nb = await _bells_parsed(nd)
    return nd, min(nb) if nb else 1


async def rooms_view(d: date, pair: int) -> tuple[str, InlineKeyboardMarkup]:
    rooms = await db.rooms()
    busy = await db.busy_rooms(d.isoformat(), pair)
    free = [name for rid, name in rooms if rid not in busy]
    bells = await _bells_parsed(d)
    tt = bells.get(pair)
    time_ = f"{tt[0]:%H:%M}–{tt[1]:%H:%M}" if tt else None
    text = format_free_rooms(d, pair, time_, free, len(rooms), now())

    pairs = sorted(bells) or list(range(1, 7))
    rows, row = [], []
    for p in pairs:
        row.append(btn(f"• {p} •" if p == pair else str(p), f"fr:{d}:{p}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn(f"◀️ {short_date(study_day(d, -1))}", f"fr:{study_day(d, -1)}:{pair}"),
                 btn("🕐 Сейчас", "fr:now"),
                 btn(f"{short_date(study_day(d, 1))} ▶️", f"fr:{study_day(d, 1)}:{pair}")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == BTN_ROOMS)
async def rooms_cmd(m: Message, state: FSMContext):
    await state.clear()
    d, p = await _default_slot()
    text, kb = await rooms_view(d, p)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("fr:"))
async def cb_rooms(c: CallbackQuery):
    if c.data == "fr:now":
        d, p = await _default_slot()
    else:
        _, raw, p = c.data.split(":")
        d, p = date.fromisoformat(raw), int(p)
    text, kb = await rooms_view(d, p)
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await c.answer()
