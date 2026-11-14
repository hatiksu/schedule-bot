from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import ADMIN_IDS
from utils.core import ALL_BUTTONS, btn, db, log
from utils.filters import IsAdmin

router = Router(name="feedback")


class FeedbackState(StatesGroup):
    text = State()


class ReplyState(StatesGroup):
    text = State()


CANCEL = InlineKeyboardMarkup(inline_keyboard=[[btn("❌ Отмена", "fb:cancel")]])


def _who(u: dict | None, uid: int) -> str:
    if not u:
        return f"<code>{uid}</code>"
    name = escape(u.get("full_name") or "Без имени")
    uname = f" · @{escape(u['username'])}" if u.get("username") else ""
    target = f" · {escape(u['target_name'])}" if u.get("target_name") else ""
    return f"<b>{name}</b>{uname}{target} · <code>{uid}</code>"


async def _start(message: Message, state: FSMContext):
    await state.set_state(FeedbackState.text)
    await message.answer(
        "✉️ <b>Сообщить об ошибке или предложить идею</b>\n\n"
        "<blockquote>Опиши, что не так: неверная пара, не та аудитория, бот завис — или что "
        "добавить. Можно приложить скриншот.</blockquote>",
        reply_markup=CANCEL)


@router.message(Command("feedback"))
async def cmd_feedback(m: Message, state: FSMContext):
    await _start(m, state)


@router.callback_query(F.data == "fb:new")
async def cb_feedback(c: CallbackQuery, state: FSMContext):
    await _start(c.message, state)
    await c.answer()


@router.callback_query(F.data == "fb:cancel")
async def cb_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("Отменено 👌")
    await c.answer()


@router.message(FeedbackState.text, ~F.text.in_(ALL_BUTTONS))
async def got_feedback(m: Message, state: FSMContext):
    text = m.text or m.caption or "[вложение без текста]"
    await state.clear()
    fid = await db.add_feedback(m.from_user.id, text)
    user = await db.get_user(m.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn("💬 Ответить", f"fbr:{fid}"), btn("✅ Закрыть", f"fbx:{fid}")]])
    for admin_id in ADMIN_IDS:
        try:
            await m.bot.send_message(admin_id, f"✉️ <b>Обращение #{fid}</b>\nот {_who(user, m.from_user.id)}")
            await m.copy_to(admin_id, reply_markup=kb)
        except TelegramAPIError as e:
            log.warning("Не доставил обращение админу %s: %s", admin_id, e)
    await m.answer(f"✅ Отправлено! Номер обращения: <b>#{fid}</b>\n"
                   "<blockquote>Ответ придёт сюда, в этот чат.</blockquote>")


@router.callback_query(F.data == "adm:fb", IsAdmin())
async def cb_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    items = await db.open_feedback(15)
    if not items:
        text = "✉️ <b>Обращения</b>\n<blockquote>Новых обращений нет 🎉</blockquote>"
        rows = []
    else:
        text = f"✉️ <b>Обращения</b> · без ответа: <b>{await db.count_open_feedback()}</b>"
        rows = [[btn(f"#{f['id']} · {(f['full_name'] or f['user_id'])}: {f['text'][:28]}", f"fbo:{f['id']}")]
                for f in items]
    rows.append([btn("◀️ В админку", "adm:home")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("fbo:"), IsAdmin())
async def cb_open(c: CallbackQuery):
    fid = int(c.data.split(":")[1])
    f = await db.get_feedback(fid)
    if not f:
        await c.answer("Не найдено", show_alert=True)
        return
    user = await db.get_user(f["user_id"])
    await c.message.edit_text(
        f"✉️ <b>Обращение #{fid}</b> · {escape(f['created_at'] or '')}\nот {_who(user, f['user_id'])}\n\n"
        f"<blockquote>{escape(f['text'])}</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("💬 Ответить", f"fbr:{fid}"), btn("✅ Закрыть", f"fbx:{fid}")],
            [btn("◀️ К обращениям", "adm:fb")]]))
    await c.answer()


@router.callback_query(F.data.startswith("fbr:"), IsAdmin())
async def cb_reply(c: CallbackQuery, state: FSMContext):
    fid = int(c.data.split(":")[1])
    f = await db.get_feedback(fid)
    if not f:
        await c.answer("Не найдено", show_alert=True)
        return
    await state.set_state(ReplyState.text)
    await state.update_data(fid=fid)
    await c.message.answer(f"💬 Напиши ответ на обращение <b>#{fid}</b> — текст, фото, что угодно.",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("❌ Отмена", "fb:cancel")]]))
    await c.answer()


@router.message(ReplyState.text, IsAdmin())
async def got_reply(m: Message, state: FSMContext):
    fid = (await state.get_data())["fid"]
    await state.clear()
    f = await db.get_feedback(fid)
    try:
        await m.bot.send_message(f["user_id"], f"💬 <b>Ответ на твоё обращение #{fid}</b>")
        await m.copy_to(f["user_id"])
    except TelegramForbiddenError:
        await m.answer("🚷 Пользователь заблокировал бота — ответ не доставлен.")
        return
    except TelegramAPIError as e:
        await m.answer(f"⚠️ Не удалось отправить: <code>{escape(str(e))}</code>")
        return
    await db.answer_feedback(fid, m.text or m.caption or "[вложение]")
    await m.answer(f"✅ Ответ на #{fid} отправлен",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("✉️ К обращениям", "adm:fb")]]))


@router.callback_query(F.data.startswith("fbx:"), IsAdmin())
async def cb_close(c: CallbackQuery):
    fid = int(c.data.split(":")[1])
    await db.answer_feedback(fid, None)
    await c.answer(f"✅ Обращение #{fid} закрыто")
    try:
        await c.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn(f"✅ #{fid} закрыто", "adm:fb")]]))
    except TelegramAPIError:
        pass
