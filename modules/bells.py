"""⏰ Звонки: сетка звонков, таймер до звонка, что у тебя сейчас и дальше."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from utils.core import BTN_BELLS, btn, db, now
from utils.formatting import format_bells

router = Router(name="bells")
REFRESH_KB = InlineKeyboardMarkup(inline_keyboard=[[btn("🔄 Обновить", "bells")]])


async def bells_text(uid: int) -> str:
    n = now()
    today = n.date().isoformat()
    user = await db.get_user(uid)
    my_rows, kind = None, None
    if user and user["kind"]:
        kind = user["kind"]
        my_rows = await db.lessons(kind, user["target_id"], today, today)
    return format_bells(await db.bells(today), n.date(), n, my_rows, kind)


@router.message(F.text == BTN_BELLS)
@router.message(Command("bells"))
async def bells(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(await bells_text(m.from_user.id), reply_markup=REFRESH_KB)


@router.callback_query(F.data == "bells")
async def cb_bells(c: CallbackQuery):
    try:
        await c.message.edit_text(await bells_text(c.from_user.id), reply_markup=REFRESH_KB)
    except TelegramBadRequest:
        pass
    await c.answer("Обновлено")
