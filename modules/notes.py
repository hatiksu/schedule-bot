"""Заметки к парам: «📝 Заметка» под расписанием дня → выбор пары → текст.
Заметка видна в расписании этого дня, в неделе, на картинке и в авторассылке."""
from __future__ import annotations

from datetime import date
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from utils.core import ALL_BUTTONS, btn, db, now, send_schedule
from utils.formatting import _merge, human_date
from utils.premium import FREE_NOTES, PAYWALL_KB, is_premium

router = Router(name="notes")
MAX_LEN = 300


class NoteState(StatesGroup):
    text = State()


def _back(kind: str, eid: str, d: str):
    return [btn("◀️ К расписанию", f"v:{kind}:{eid}:d:{d}")]


@router.callback_query(F.data.startswith("nt:"))
async def cb_pick_pair(c: CallbackQuery, state: FSMContext):
    await state.clear()
    _, kind, eid, d = c.data.split(":")
    items = _merge(await db.lessons(kind, int(eid), d, d))
    if not items:
        await c.answer("В этот день пар нет — заметку не к чему привязать", show_alert=True)
        return
    existing = await db.notes(c.from_user.id, kind, int(eid), d, d)
    rows = []
    for r in items:
        mark = "✏️ " if (d, r["pair"]) in existing else ""
        rows.append([btn(f"{mark}{r['pair']} пара · {r['subject'][:40]}", f"ntp:{kind}:{eid}:{d}:{r['pair']}")])
    rows.append(_back(kind, eid, d))
    await c.message.edit_text(
        f"📝 <b>Заметка к паре</b>\n📅 {human_date(date.fromisoformat(d))}\n\n"
        "<blockquote>Выбери пару — например, чтобы не забыть «принести реферат».\n"
        "✏️ — уже есть заметка</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


async def _ask_text(c: CallbackQuery, state: FSMContext, kind: str, eid: str, d: str, pair: int):
    await state.set_state(NoteState.text)
    await state.update_data(kind=kind, eid=int(eid), date=d, pair=pair)
    await c.message.edit_text(
        f"📝 Напиши заметку к <b>{pair} паре</b>, {human_date(date.fromisoformat(d)).lower()}\n"
        f"<blockquote>до {MAX_LEN} символов</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_back(kind, eid, d)]))


@router.callback_query(F.data.startswith("ntp:"))
async def cb_pair(c: CallbackQuery, state: FSMContext):
    _, kind, eid, d, pair = c.data.split(":")
    pair = int(pair)
    existing = (await db.notes(c.from_user.id, kind, int(eid), d, d)).get((d, pair))
    if not existing:
        user = await db.get_user(c.from_user.id)
        if not is_premium(user) and await db.count_future_notes(c.from_user.id, now().date().isoformat()) >= FREE_NOTES:
            await c.message.edit_text(
                f"📝 Без Premium можно держать до <b>{FREE_NOTES}</b> заметок на будущие пары.\n"
                "<blockquote>Удали ненужную или открой ⭐ Premium — безлимит заметок "
                "и напоминание о них утром.</blockquote>", reply_markup=PAYWALL_KB)
            await c.answer()
            return
        await _ask_text(c, state, kind, eid, d, pair)
    else:
        await c.message.edit_text(
            f"📝 <b>Заметка к {pair} паре</b>\n<blockquote>{escape(existing)}</blockquote>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("✏️ Изменить", f"ntw:{kind}:{eid}:{d}:{pair}"),
                 btn("🗑 Удалить", f"ntd:{kind}:{eid}:{d}:{pair}")],
                _back(kind, eid, d)]))
    await c.answer()


@router.callback_query(F.data.startswith("ntw:"))
async def cb_edit(c: CallbackQuery, state: FSMContext):
    _, kind, eid, d, pair = c.data.split(":")
    await _ask_text(c, state, kind, eid, d, int(pair))
    await c.answer()


@router.callback_query(F.data.startswith("ntd:"))
async def cb_delete(c: CallbackQuery, state: FSMContext):
    _, kind, eid, d, pair = c.data.split(":")
    await state.clear()
    await db.delete_note(c.from_user.id, kind, int(eid), d, int(pair))
    await c.answer("🗑 Заметка удалена")
    try:
        await c.message.delete()
    except TelegramBadRequest:
        pass
    await send_schedule(c.message, kind, int(eid), "d", date.fromisoformat(d), c.from_user.id)


@router.message(NoteState.text, F.text, ~F.text.in_(ALL_BUTTONS))
async def note_text(m: Message, state: FSMContext):
    data = await state.get_data()
    text = m.text.strip()[:MAX_LEN]
    await state.clear()
    await db.set_note(m.from_user.id, data["kind"], data["eid"], data["date"], data["pair"], text)
    await m.answer("✅ Заметка сохранена")
    await send_schedule(m, data["kind"], data["eid"], "d", date.fromisoformat(data["date"]), m.from_user.id)


@router.message(NoteState.text, ~F.text)
async def note_not_text(m: Message):
    await m.answer("Заметка может быть только текстом ✍️")
