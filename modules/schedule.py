"""📅 Расписание: кнопки «Сегодня / Завтра / Неделя / След. неделя» и листание ◀️ ▶️."""
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from utils.core import MENU_BUTTONS, now, render, require_user, resolve, send_schedule

router = Router(name="schedule")


@router.message(F.text.in_(MENU_BUTTONS))
async def my_schedule(m: Message, state: FSMContext):
    await state.clear()
    user = await require_user(m)
    if user:
        scope, d = resolve(m.text)
        await send_schedule(m, user["kind"], user["target_id"], scope, d, m.from_user.id)


# v:<kind>:<id>:<d|w>:<YYYY-MM-DD | t>
@router.callback_query(F.data.startswith("v:"))
async def cb_view(c: CallbackQuery):
    try:
        _, kind, eid, scope, raw = c.data.split(":")
    except ValueError:  # кнопки от старой версии бота
        await c.answer("Кнопка устарела, нажми «📅 Сегодня» внизу", show_alert=True)
        return
    d = now().date() if raw == "t" else date.fromisoformat(raw)
    if c.inline_message_id:  # сообщение отправлено через inline-режим в чужой чат
        chunks, kb = await render(kind, int(eid), scope, d, private=False)
        try:
            await c.bot.edit_message_text(chunks[0], inline_message_id=c.inline_message_id, reply_markup=kb)
        except TelegramBadRequest:
            pass
        await c.answer()
        return
    chunks, kb = await render(kind, int(eid), scope, d, uid=c.from_user.id)
    if len(chunks) == 1:
        try:
            await c.message.edit_text(chunks[0], reply_markup=kb)
        except TelegramBadRequest:
            pass  # «message is not modified»
    else:
        await send_schedule(c.message, kind, int(eid), scope, d, c.from_user.id)
    await c.answer()
