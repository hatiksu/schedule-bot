"""🔎 Поиск по группам, преподавателям и аудиториям. Также ловит любой текст — «К-11», «Иванов».
Подключается ПОСЛЕДНИМ, чтобы не перехватывать ввод других модулей."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from utils.core import ALL_BUTTONS, BTN_SEARCH, db, now, pick_kb, send_schedule

router = Router(name="search")


class Search(StatesGroup):
    query = State()


async def do_search(m: Message, text: str):
    found = await db.search(text)
    if not found:
        await m.answer("🤔 Ничего не нашёл. Попробуй написать иначе.")
    elif len(found) == 1:
        kind, eid, _ = found[0]
        await send_schedule(m, kind, eid, "d", now().date(), m.from_user.id)
    else:
        await m.answer(f"🔎 Найдено: {len(found)}. Что показать?", reply_markup=pick_kb(found, "v", ":d:t"))


@router.message(F.text == BTN_SEARCH)
async def search_start(m: Message, state: FSMContext):
    await state.set_state(Search.query)
    await m.answer("🔎 Кого ищем?\n<blockquote>группу, фамилию преподавателя или аудиторию</blockquote>")


@router.message(Search.query, F.text, ~F.text.in_(ALL_BUTTONS))
async def search_query(m: Message, state: FSMContext):
    await state.clear()
    await do_search(m, m.text)


@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_(ALL_BUTTONS))
async def fallback_search(m: Message):
    await do_search(m, m.text)
