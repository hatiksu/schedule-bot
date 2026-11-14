from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from modules import achievements, gifts, referral
from utils.core import (ALL_BUTTONS, KIND_ICON, MAIN_KB, ROLE_KB, chosen_name, db, now, pick_kb,
                        runtime, send_schedule)
from utils.db import norm
from utils.formatting import KIND_TITLE

router = Router(name="start")

WELCOME = (
    "👋 <b>Привет!</b> Я бот расписания колледжа.\n\n"
    "<blockquote>📅 Расписание на день и на неделю\n"
    "🟢 Покажу, какая пара идёт и сколько до звонка\n"
    "🔔 Сообщу о заменах — что именно поменялось\n"
    "⏰ Пришлю расписание вечером или утром\n"
    "🏫 Найду свободную аудиторию и преподавателя\n"
    "📝 Заметки к парам и 🖼 расписание картинкой</blockquote>\n\n"
    "Для начала скажи, кто ты:"
)
HELP = (
    "ℹ️ <b>Как пользоваться</b>\n\n"
    "<blockquote><b>Кнопки внизу</b> — расписание, аудитории, звонки, преподаватели.\n"
    "<b>◀️ ▶️</b> под расписанием — листать дни и недели.\n"
    "<b>📝 Заметка</b> — запиши к паре «принести реферат».\n"
    "<b>🖼 Картинкой</b> — расписание PNG для беседы или сторис.\n"
    "<b>Просто напиши</b> группу, фамилию или аудиторию (например <code>К-11</code>, "
    "<code>Иванов</code>, <code>2-25</code>) — покажу их расписание.</blockquote>\n\n"
    "<blockquote><b>В любом чате</b> напиши <code>@{bot} К-11</code> — и отправь расписание "
    "прямо в беседу. Без текста после имени бота — твоё расписание.</blockquote>\n\n"
    "/settings — группа, уведомления, авторассылка\n"
    "/feedback — сообщить об ошибке или предложить идею"
)


class Setup(StatesGroup):
    query = State()


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext, command: CommandObject, is_new_user: bool = False):
    await state.clear()
    payload = (command.args or "").strip()
    if payload.startswith("gift_"):
        await gifts.redeem(m, payload)
    elif payload.startswith("ref_"):
        await referral.remember_inviter(m.from_user.id, payload, is_new_user)
    user = await db.get_user(m.from_user.id)
    if user and user["kind"]:
        who = "Группа" if user["kind"] == "g" else "Преподаватель"
        await m.answer(
            "👋 <b>С возвращением!</b>\n\n"
            f"<blockquote>{KIND_ICON[user['kind']]} {who}: <b>{escape(await chosen_name(user))}</b></blockquote>\n"
            "Сменить можно в ⚙️ Настройках.",
            reply_markup=MAIN_KB,
        )
        await send_schedule(m, user["kind"], user["target_id"], "d", now().date(), m.from_user.id)
        return
    await m.answer(WELCOME, reply_markup=ROLE_KB)


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(HELP.replace("{bot}", runtime["bot_username"] or "bot"))


@router.callback_query(F.data.startswith("role:"))
async def cb_role(c: CallbackQuery, state: FSMContext):
    kind = c.data.split(":")[1]
    await state.set_state(Setup.query)
    await state.update_data(kind=kind)
    prompt = ("🎓 Напиши название своей группы\n<blockquote>например: <code>К-11</code></blockquote>"
              if kind == "g" else
              "👨‍🏫 Напиши свою фамилию\n<blockquote>например: <code>Иванов</code></blockquote>")
    await c.message.edit_text(prompt)
    await c.answer()


async def finish_setup(message: Message, state: FSMContext, uid: int, kind: str, eid: int):
    await db.set_user(uid, kind, eid)
    await state.clear()
    name = await db.entity_name(kind, eid) or "?"
    await message.answer(
        f"✅ Готово! {KIND_TITLE[kind]}: <b>{escape(name)}</b>\n"
        "<blockquote>Кнопки внизу — твоё расписание. Изменения пришлю сам 🔔\n"
        "В ⚙️ Настройках можно включить рассылку расписания на вечер или утро.</blockquote>",
        reply_markup=MAIN_KB,
    )
    await send_schedule(message, kind, eid, "d", now().date(), uid)
    await referral.reward_inviter(message.bot, uid)
    await achievements.check(message.bot, uid)


@router.message(Setup.query, F.text, ~F.text.in_(ALL_BUTTONS))
async def setup_query(m: Message, state: FSMContext):
    kind = (await state.get_data())["kind"]
    found = await db.search(m.text, kinds=(kind,))
    exact = [f for f in found if norm(f[2]) == norm(m.text)]
    if len(exact) == 1 or len(found) == 1:
        k, eid, _ = (exact or found)[0]
        await finish_setup(m, state, m.from_user.id, k, eid)
    elif found:
        await m.answer("🔎 Нашёл несколько вариантов, выбери:", reply_markup=pick_kb(found, "set"))
    else:
        await m.answer("🤔 Не нашёл. Проверь написание и попробуй ещё раз.")


@router.callback_query(F.data.startswith("set:"))
async def cb_set(c: CallbackQuery, state: FSMContext):
    _, kind, eid = c.data.split(":")
    await c.message.delete()
    await finish_setup(c.message, state, c.from_user.id, kind, int(eid))
    await c.answer()
