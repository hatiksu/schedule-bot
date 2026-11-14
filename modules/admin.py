"""🛠 Админ-панель: /admin

📊 Статистика · 🔄 Обновить расписание · 📢 Рассылка · 👤 Пользователи · 📥 Экспорт CSV

Доступ — только ID из ADMIN_IDS (.env). db и run_update приходят из Dispatcher(...).
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from datetime import date, datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from config import ADMIN_IDS
from utils.db import DB
from utils.core import runtime
from utils.premium import status_text
from utils.filters import IsAdmin

log = logging.getLogger("schedule_bot.admin")
router = Router(name="admin")


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class Broadcast(StatesGroup):
    target_query = State()   # ввод группы / фамилии для адресной рассылки
    content = State()        # ждём сообщение для рассылки


class FindUser(StatesGroup):
    query = State()


class HolidayState(StatesGroup):
    text = State()


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


BACK = [btn("◀️ В админку", "adm:home")]
KIND_ICON = {"g": "👥", "t": "👤"}


# ---------- главная ----------
async def home_view(db: DB) -> tuple[str, InlineKeyboardMarkup]:
    s = await db.stats()
    last = await db.get_meta("last_update_at") or "—"
    ok = await db.get_meta("last_update_ok")
    count = await db.get_meta("last_update_count")
    err = await db.get_meta("last_update_error")
    status = "✅" if ok == "1" else "❌" if ok == "0" else "⏳"
    lines = [
        "🛠 <b>Админ-панель</b>\n",
        "<blockquote>"
        f"👥 Пользователей: <b>{s['total']}</b>  (сегодня +{s['new_today']})\n"
        f"🔥 Активных сегодня: <b>{s['active_today']}</b>\n\n"
        f"🔄 Последняя проверка сайта: {escape(last)} {status}"
        + (f"\n📚 Пар в выгрузке: <b>{count}</b>" if count else "")
        + f"\n🌐 Сайт обновлён: {escape(await db.get_meta('site_updated') or '—')}"
        + "</blockquote>",
    ]
    if ok == "0" and err:
        lines.append(f"\n⚠️ Ошибка: <code>{escape(err[:300])}</code>")
    maint = await db.get_meta("maintenance") == "1"
    if maint:
        lines.append("\n🛠 <b>Включён режим техработ</b> — пользователи видят заглушку")
    fb = await db.count_open_feedback()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("📊 Статистика", "adm:stats"), btn("🔄 Обновить расписание", "adm:update")],
        [btn("📈 Фичи и графики", "adm:fs")],
        [btn("📢 Рассылка", "adm:bc"), btn("👤 Пользователи", "adm:find")],
        [btn(f"✉️ Обращения ({fb})" if fb else "✉️ Обращения", "adm:fb"),
         btn("📜 Журнал обновлений", "adm:log:all")],
        [btn("🏖 Каникулы", "adm:hol"), btn("📥 Экспорт CSV", "adm:export")],
        [btn("⭐ Premium и продажи", "pa:menu"), btn("💾 Бэкапы и импорт", "bk:menu")],
        [btn("✅ Выключить техработы" if maint else "🛠 Включить техработы", "adm:maint")],
    ])
    return "\n".join(lines), kb


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext, db: DB):
    await state.clear()
    text, kb = await home_view(db)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:home")
async def cb_home(c: CallbackQuery, state: FSMContext, db: DB):
    await state.clear()
    text, kb = await home_view(db)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()


# ---------- статистика ----------
@router.callback_query(F.data == "adm:stats")
async def cb_stats(c: CallbackQuery, db: DB):
    s = await db.stats()
    groups = await db.top_targets("g")
    teachers = await db.top_targets("t")
    top_g = "\n".join(f"{i}. {escape(n)} — {cnt}" for i, (n, cnt) in enumerate(groups, 1)) or "—"
    top_t = "\n".join(f"{i}. {escape(n)} — {cnt}" for i, (n, cnt) in enumerate(teachers, 1)) or "—"
    text = (
        "📊 <b>Статистика</b>\n\n"
        "<blockquote>"
        f"👥 Всего: <b>{s['total']}</b>\n"
        f"🎓 Студентов: <b>{s['students']}</b>\n"
        f"👨‍🏫 Преподавателей: <b>{s['teachers']}</b>\n"
        f"❔ Не выбрали группу: <b>{s['no_choice']}</b>\n"
        f"🔕 Выключили уведомления: <b>{s['notify_off']}</b>\n"
        f"🚫 Заблокированы: <b>{s['banned']}</b>"
        "</blockquote>\n"
        "<blockquote>"
        f"🆕 Новых: сегодня <b>{s['new_today']}</b> · за 7 дней <b>{s['new_week']}</b>\n"
        f"🔥 Активных: сегодня <b>{s['active_today']}</b> · за 7 дней <b>{s['active_week']}</b>"
        "</blockquote>\n"
        f"<b>Топ групп</b>\n<blockquote>{top_g}</blockquote>\n"
        f"<b>Топ преподавателей</b>\n<blockquote>{top_t}</blockquote>"
    )
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔄 Обновить", "adm:stats")], BACK]))
    await c.answer()


# ---------- обновление расписания ----------
@router.callback_query(F.data == "adm:update")
async def cb_update(c: CallbackQuery, db: DB, run_update):
    await c.answer("Запускаю обновление…")
    await c.message.edit_text("⏳ Обновляю расписание с сайта…")
    try:
        count = await run_update(c.bot, force=True)
        text = f"✅ Расписание обновлено\n<blockquote>📚 Пар в базе: <b>{count}</b></blockquote>"
    except Exception as e:
        text = f"❌ Не удалось обновить\n<blockquote><code>{escape(str(e)[:500])}</code></blockquote>"
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))


# ---------- экспорт ----------
@router.callback_query(F.data == "adm:export")
async def cb_export(c: CallbackQuery, db: DB):
    users = await db.all_users()
    buf = io.StringIO()
    fields = ["user_id", "username", "full_name", "kind", "target_id", "target_name", "notify",
              "banned", "registered_at", "last_seen"]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", delimiter=";")
    w.writeheader()
    for u in users:
        u = dict(u)
        u["kind"] = {"g": "студент", "t": "преподаватель"}.get(u["kind"], "")
        w.writerow(u)
    data = buf.getvalue().encode("utf-8-sig")  # BOM — чтобы Excel правильно открыл кириллицу
    await c.message.answer_document(BufferedInputFile(data, filename="users.csv"),
                                    caption=f"📥 Пользователей: <b>{len(users)}</b>")
    await c.answer()


# ---------- пользователи ----------
def user_card(u: dict) -> tuple[str, InlineKeyboardMarkup]:
    role = {"g": "🎓 студент", "t": "👨‍🏫 преподаватель"}.get(u["kind"], "❔ не выбрал")
    target = f"\n{KIND_ICON.get(u['kind'], '')} {escape(u['target_name'] or '—')}" if u["kind"] else ""
    uname = f"@{escape(u['username'])}" if u["username"] else "без юзернейма"
    text = (
        f"👤 <b>{escape(u['full_name'] or 'Без имени')}</b>\n"
        "<blockquote>"
        f"🆔 <code>{u['user_id']}</code> · {uname}\n"
        f"{role}{target}\n"
        f"{'🔔 уведомления включены' if u['notify'] else '🔕 уведомления выключены'}\n\n"
        f"📅 Регистрация: {escape(u['registered_at'] or '—')}\n"
        f"🕓 Был в боте: {escape(u['last_seen'] or '—')}\n"
        f"⭐ {status_text(u)}"
        + ("\n\n🚫 <b>Заблокирован</b>" if u["banned"] else "")
        + "</blockquote>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("✅ Разблокировать", f"adm:unban:{u['user_id']}") if u["banned"]
         else btn("🚫 Заблокировать", f"adm:ban:{u['user_id']}"),
         btn("⭐ Premium", f"pa:give:{u['user_id']}")],
        [InlineKeyboardButton(text="💬 Открыть профиль", url=f"tg://user?id={u['user_id']}")],
        [btn("🔎 Найти другого", "adm:find")], BACK,
    ])
    return text, kb


@router.callback_query(F.data == "adm:find")
async def cb_find(c: CallbackQuery, state: FSMContext):
    await state.set_state(FindUser.query)
    await c.message.edit_text(
        "🔎 <b>Поиск пользователя</b>\n<blockquote>Напиши ID, @юзернейм, имя или группу</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))
    await c.answer()


@router.message(FindUser.query, F.text)
async def find_query(m: Message, state: FSMContext, db: DB):
    users = await db.find_users(m.text)
    if not users:
        await m.answer("🤔 Никого не нашёл. Попробуй иначе или вернись в админку.",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))
        return
    await state.clear()
    if len(users) == 1:
        text, kb = user_card(users[0])
        await m.answer(text, reply_markup=kb)
        return
    rows = [[btn(f"{u['full_name'] or u['user_id']}"
                 + (f" (@{u['username']})" if u["username"] else "")
                 + (f" · {u['target_name']}" if u["target_name"] else ""),
                 f"adm:user:{u['user_id']}")] for u in users]
    await m.answer(f"🔎 Найдено: <b>{len(users)}</b>",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=rows + [BACK]))


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_user(c: CallbackQuery, db: DB):
    u = await db.get_user(int(c.data.split(":")[2]))
    if not u:
        await c.answer("Пользователь не найден", show_alert=True)
        return
    text, kb = user_card(u)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()


@router.callback_query(F.data.startswith("adm:ban:") | F.data.startswith("adm:unban:"))
async def cb_ban(c: CallbackQuery, db: DB):
    _, action, uid = c.data.split(":")
    uid = int(uid)
    if action == "ban" and uid in ADMIN_IDS:
        await c.answer("Админа заблокировать нельзя", show_alert=True)
        return
    await db.set_banned(uid, action == "ban")
    u = await db.get_user(uid)
    text, kb = user_card(u)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer("🚫 Заблокирован" if action == "ban" else "✅ Разблокирован")


# ---------- рассылка ----------
@router.callback_query(F.data == "adm:bc")
async def cb_bc(c: CallbackQuery, state: FSMContext, db: DB):
    await state.clear()
    s = await db.stats()
    active = s["total"] - s["banned"]
    await c.message.edit_text(
        "📢 <b>Рассылка</b>\n<blockquote>Кому отправляем?</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn(f"👥 Всем ({active})", "adm:bc:all")],
            [btn(f"🎓 Студентам ({s['students']})", "adm:bc:g"),
             btn(f"👨‍🏫 Преподавателям ({s['teachers']})", "adm:bc:t")],
            [btn("🎯 Одной группе / преподавателю", "adm:bc:one")],
            BACK,
        ]))
    await c.answer()


async def ask_content(message: Message, state: FSMContext, label: str, count: int, edit: bool):
    await state.set_state(Broadcast.content)
    await state.update_data(label=label)
    text = (f"📢 Рассылка: <b>{escape(label)}</b> · получателей: <b>{count}</b>\n\n"
            "<blockquote>Отправь сообщение для рассылки — текст, фото, видео, файл, "
            "с форматированием. Разошлю его в точности как есть.</blockquote>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn("❌ Отмена", "adm:home")]])
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.in_({"adm:bc:all", "adm:bc:g", "adm:bc:t"}))
async def cb_bc_segment(c: CallbackQuery, state: FSMContext, db: DB):
    seg = c.data.split(":")[2]
    kind = None if seg == "all" else seg
    label = {"all": "всем", "g": "студентам", "t": "преподавателям"}[seg]
    await state.update_data(kind=kind, target_id=None)
    await ask_content(c.message, state, label, len(await db.audience(kind)), edit=True)
    await c.answer()


@router.callback_query(F.data == "adm:bc:one")
async def cb_bc_one(c: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.target_query)
    await c.message.edit_text(
        "🎯 Напиши группу или фамилию преподавателя",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("❌ Отмена", "adm:home")]]))
    await c.answer()


@router.message(Broadcast.target_query, F.text)
async def bc_target_query(m: Message, db: DB):
    found = await db.search(m.text, kinds=("g", "t"), limit=12)
    if not found:
        await m.answer("🤔 Не нашёл. Попробуй ещё раз.")
        return
    rows = [[btn(f"{KIND_ICON[k]} {n}", f"adm:bct:{k}:{i}")] for k, i, n in found]
    await m.answer("Кому отправляем?", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=rows + [[btn("❌ Отмена", "adm:home")]]))


@router.callback_query(F.data.startswith("adm:bct:"))
async def cb_bc_target(c: CallbackQuery, state: FSMContext, db: DB):
    _, _, kind, eid = c.data.split(":")
    eid = int(eid)
    name = await db.entity_name(kind, eid) or "?"
    await state.update_data(kind=kind, target_id=eid)
    await ask_content(c.message, state, name, len(await db.audience(kind, eid)), edit=True)
    await c.answer()


@router.message(Broadcast.content)
async def bc_content(m: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    count = len(await db.audience(data.get("kind"), data.get("target_id")))
    await state.update_data(chat_id=m.chat.id, message_id=m.message_id)
    await m.answer("👆 Так увидят сообщение получатели.")
    await m.bot.copy_message(m.chat.id, m.chat.id, m.message_id)
    await m.answer(
        f"Отправить <b>{escape(data['label'])}</b> — <b>{count}</b> чел.?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn(f"✅ Отправить ({count})", "adm:bc:go")],
            [btn("✏️ Другое сообщение", "adm:bc:redo"), btn("❌ Отмена", "adm:home")],
        ]))


@router.callback_query(F.data == "adm:bc:redo")
async def cb_bc_redo(c: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.content)
    await c.message.edit_text("Отправь новое сообщение для рассылки 👇")
    await c.answer()


@router.callback_query(F.data == "adm:bc:go")
async def cb_bc_go(c: CallbackQuery, state: FSMContext, db: DB):
    data = await state.get_data()
    await state.clear()
    if "message_id" not in data:
        await c.answer("Сообщение не найдено, начни заново", show_alert=True)
        return
    users = await db.audience(data.get("kind"), data.get("target_id"))
    await c.answer("Рассылка запущена")
    progress = await c.message.edit_text(f"📤 Рассылка: 0 / {len(users)}")
    # в фоне, чтобы бот не «зависал» на время рассылки
    asyncio.create_task(run_broadcast(c.bot, db, users, data["chat_id"], data["message_id"],
                                      progress, data["label"]))


async def run_broadcast(bot: Bot, db: DB, users: list[int], from_chat: int, msg_id: int,
                        progress: Message, label: str) -> None:
    sent = blocked = failed = 0
    for i, uid in enumerate(users, 1):
        try:
            await bot.copy_message(uid, from_chat, msg_id)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramForbiddenError:
            blocked += 1  # пользователь удалил / заблокировал бота
        except TelegramAPIError:
            failed += 1
        if i % 25 == 0:
            try:
                await progress.edit_text(f"📤 Рассылка: {i} / {len(users)}")
            except TelegramAPIError:
                pass
        await asyncio.sleep(0.05)  # ~20 сообщений в секунду — в пределах лимитов Telegram
    report = (
        f"✅ <b>Рассылка завершена</b> · {escape(label)}\n"
        "<blockquote>"
        f"📨 Доставлено: <b>{sent}</b>\n"
        f"🚷 Заблокировали бота: <b>{blocked}</b>\n"
        f"⚠️ Ошибки: <b>{failed}</b>"
        "</blockquote>"
    )
    try:
        await progress.edit_text(report, reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))
    except TelegramAPIError:
        await bot.send_message(from_chat, report)
    log.info("Рассылка «%s»: доставлено %s, заблокировали %s, ошибок %s", label, sent, blocked, failed)


# ---------- режим техработ ----------
@router.callback_query(F.data == "adm:maint")
async def cb_maint(c: CallbackQuery, db: DB):
    on = await db.get_meta("maintenance") != "1"
    await db.set_meta("maintenance", "1" if on else "0")
    runtime["maintenance"] = on
    await c.answer("🛠 Техработы включены — пользователи видят заглушку" if on
                   else "✅ Техработы выключены", show_alert=True)
    text, kb = await home_view(db)
    await c.message.edit_text(text, reply_markup=kb)


# ---------- журнал обновлений ----------
@router.callback_query(F.data.startswith("adm:log:"))
async def cb_log(c: CallbackQuery, db: DB):
    only_events = c.data.endswith("events")
    entries = await db.update_log(20, only_events)
    lines = []
    for e in entries:
        try:
            at = datetime.strptime(e["at"], "%Y-%m-%d %H:%M:%S").strftime("%d.%m %H:%M")
        except (TypeError, ValueError):
            at = e["at"] or "?"
        sec = f"{(e['duration_ms'] or 0) / 1000:.1f} с"
        force = " · вручную" if e["forced"] else ""
        if not e["ok"]:
            lines.append(f"❌ <b>{at}</b> · {sec}{force}\n      <code>{escape((e['error'] or '')[:120])}</code>")
        elif e["lessons"] is None:
            lines.append(f"▫️ {at} · без изменений на сайте")
        else:
            ch = f" · замены в {e['changes']} дн." if e["changes"] else " · без замен"
            lines.append(f"✅ <b>{at}</b> · {e['lessons']} пар{ch} · {sec}{force}")
    body = "\n".join(lines) or "Записей пока нет"
    title = "только загрузки и ошибки" if only_events else "все проверки"
    await c.message.edit_text(
        f"📜 <b>Журнал обновлений</b> · {title}\n\n<blockquote>{body}</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("Все проверки", "adm:log:all"), btn("Только события", "adm:log:events")],
            [btn("🔄 Обновить", c.data)], BACK]))
    await c.answer()


# ---------- каникулы ----------
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


@router.callback_query(F.data == "adm:hol")
async def cb_holiday(c: CallbackQuery, state: FSMContext, db: DB):
    start, end, name = (await db.get_meta("holiday_start"), await db.get_meta("holiday_end"),
                        await db.get_meta("holiday_name"))
    cur = "не заданы"
    if start:
        cur = f"{date.fromisoformat(start):%d.%m.%Y}" + (f" – {date.fromisoformat(end):%d.%m.%Y}" if end else "") \
              + f" · «до {escape(name or 'каникул')}»"
    await state.set_state(HolidayState.text)
    rows = [[btn("🗑 Убрать каникулы", "adm:hol:del")]] if start else []
    await c.message.edit_text(
        "🏖 <b>Каникулы</b>\n"
        f"<blockquote>Сейчас: {cur}</blockquote>\n\n"
        "Пользователи увидят в расписании «🏖 До зимних каникул: 12 дней».\n"
        "Напиши даты и (по желанию) название в родительном падеже:\n"
        "<code>29.12.2026 – 11.01.2027 зимних каникул</code>\n"
        "или просто <code>29.12.2026</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows + [BACK]))
    await c.answer()


@router.callback_query(F.data == "adm:hol:del")
async def cb_holiday_del(c: CallbackQuery, state: FSMContext, db: DB):
    await state.clear()
    for key in ("holiday_start", "holiday_end", "holiday_name"):
        await db.set_meta(key, "")
    await c.answer("Каникулы убраны")
    text, kb = await home_view(db)
    await c.message.edit_text(text, reply_markup=kb)


@router.message(HolidayState.text, F.text)
async def holiday_text(m: Message, state: FSMContext, db: DB):
    dates = DATE_RE.findall(m.text)
    try:
        parsed = [date(int(y), int(mo), int(d)) for d, mo, y in dates]
    except ValueError:
        parsed = []
    if not parsed:
        await m.answer("🤔 Не вижу дату. Пример: <code>29.12.2026 – 11.01.2027 зимних каникул</code>")
        return
    name = DATE_RE.sub("", m.text).replace("–", " ").replace("-", " ").strip() or "каникул"
    await state.clear()
    await db.set_meta("holiday_start", parsed[0].isoformat())
    await db.set_meta("holiday_end", parsed[1].isoformat() if len(parsed) > 1 else "")
    await db.set_meta("holiday_name", name)
    period = f"{parsed[0]:%d.%m.%Y}" + (f" – {parsed[1]:%d.%m.%Y}" if len(parsed) > 1 else "")
    await m.answer(f"✅ Каникулы сохранены\n<blockquote>{period} · «до {escape(name)}»</blockquote>",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))
