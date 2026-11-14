"""⚙️ Настройки: смена группы/препода, уведомления о заменах, вход в авторассылку и обратную связь."""
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from modules import digest
from utils.core import BTN_SETTINGS, ROLE_KB, btn, chosen_name, db, require_user
from utils.premium import is_premium, status_text

router = Router(name="settings")


async def settings_view(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    name = escape(await chosen_name(user))
    on = bool(user["notify"])
    if user["kind"] == "t":
        who = f"👨‍🏫 Роль: <b>преподаватель</b>\n👤 Преподаватель: <b>{name}</b>"
        change = "✏️ Сменить преподавателя"
    else:
        who = f"🎓 Роль: <b>студент</b>\n👥 Группа: <b>{name}</b>"
        change = "✏️ Сменить группу"
    bell = "🔔 Уведомления о заменах: <b>включены</b>" if on else "🔕 Уведомления о заменах: <b>выключены</b>"
    prem = is_premium(user)
    badge = f"\n\n{status_text(user)}" if prem else ""
    text = (f"⚙️ <b>Настройки</b>\n\n<blockquote>{who}\n\n{bell}\n"
            f"⏰ Авторассылка: <b>{digest.describe(user)}</b>{badge}</blockquote>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn(change, "st:change")],
        [btn("🔕 Выключить уведомления" if on else "🔔 Включить уведомления", "st:notify")],
        [btn("⏰ Рассылки", "dg:menu"), btn("⏳ Напоминания" + ("" if prem else " ⭐"), "rm:menu")],
        [btn("🎨 Оформление", "ap:menu"), btn("⭐ Избранное" + ("" if prem else " ⭐"), "fav:list")],
        [btn("📱 Виджет в чате" + ("" if prem else " ⭐"), "wg:menu"),
         btn("📲 Виджет на экран" + ("" if prem else " ⭐"), "hw:menu")],
        [btn("🏆 Достижения", "ach:list")],
        [btn("👑 Мой Premium" if prem else "⭐ Premium", "pm:menu"), btn("🤝 Пригласить друзей", "ref:menu")],
        [btn("✉️ Сообщить об ошибке / идея", "fb:new")],
    ])
    return text, kb


@router.message(F.text == BTN_SETTINGS)
@router.message(Command("settings"))
async def settings(m: Message, state: FSMContext):
    await state.clear()
    user = await require_user(m)
    if user:
        text, kb = await settings_view(user)
        await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "st:home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(c.from_user.id)
    if user and user["kind"]:
        text, kb = await settings_view(user)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except TelegramAPIError:  # если это было фото — шлём новым сообщением
            await c.message.answer(text, reply_markup=kb)
    await c.answer()


@router.callback_query(F.data == "st:change")
async def cb_change(c: CallbackQuery):
    await c.message.edit_text("Кто ты?", reply_markup=ROLE_KB)
    await c.answer()


@router.callback_query(F.data == "st:notify")
async def cb_notify(c: CallbackQuery):
    on = await db.toggle_notify(c.from_user.id)
    user = await db.get_user(c.from_user.id)
    text, kb = await settings_view(user)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer("🔔 Уведомления включены" if on else "🔕 Уведомления выключены")
