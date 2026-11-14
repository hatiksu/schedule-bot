from __future__ import annotations

import asyncio
import csv
import io
import re
import tempfile
from html import escape
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from config import ADMIN_IDS, BACKUP_KEEP, BACKUP_TIME
from utils import backup
from utils.core import btn, db, log, now, runtime
from utils.db import norm
from utils.filters import IsAdmin

router = Router(name="backup")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

ID_RE = re.compile(r"(?<!\d)\d{5,15}(?!\d)")
BACK = [btn("◀️ К бэкапам", "bk:menu")]
TO_ADMIN = [btn("◀️ В админку", "adm:home")]


class ImportState(StatesGroup):
    wait = State()


@router.callback_query(F.data == "bk:menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    items = backup.list_backups()
    last = backup.describe(items[0]) if items else "ещё не было"
    s = await db.stats()
    await c.message.edit_text(
        "💾 <b>Бэкапы и импорт</b>\n\n"
        "<blockquote>"
        f"🗂 Последний бэкап: <b>{escape(last)}</b>\n"
        f"📦 Копий на сервере: <b>{len(items)}</b>\n"
        f"⏰ Автобэкап: каждый день в <b>{BACKUP_TIME}</b>, храню {BACKUP_KEEP} последних\n\n"
        f"👥 Сейчас в базе: <b>{s['total']}</b> пользователей</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("📤 Сделать бэкап сейчас", "bk:now")],
            [btn("♻️ Восстановить из бэкапа", "bk:list")],
            [btn("📥 Импорт пользователей", "bk:imp")],
            TO_ADMIN,
        ]))
    await c.answer()


async def _send_backup(bot: Bot, chat_id: int, path: Path, title: str, silent: bool = False) -> None:
    s = await db.stats()
    await bot.send_document(
        chat_id, FSInputFile(path, filename=path.name),
        caption=f"💾 <b>{title}</b> · {escape(backup.describe(path))}\n"
                f"<blockquote>👥 Пользователей: <b>{s['total']}</b> · 🎓 {s['students']} · "
                f"👨‍🏫 {s['teachers']}</blockquote>",
        disable_notification=silent)


@router.callback_query(F.data == "bk:now")
async def cb_now(c: CallbackQuery):
    await c.answer("Делаю бэкап…")
    path = await backup.make_backup(db, "manual")
    await _send_backup(c.bot, c.from_user.id, path, "Бэкап базы")


def _name(path: Path) -> str:
    return path.stem.removeprefix("schedule_")


def _find(name: str) -> Path | None:
    return next((p for p in backup.list_backups() if _name(p) == name), None)


@router.callback_query(F.data == "bk:list")
async def cb_list(c: CallbackQuery):
    items = backup.list_backups()
    if not items:
        await c.answer("Бэкапов пока нет — сделай первый кнопкой «Сделать бэкап сейчас»", show_alert=True)
        return
    rows = [[btn(f"🗂 {backup.describe(p)}", f"bk:r:{_name(p)}")] for p in items[:12]]
    await c.message.edit_text(
        "♻️ <b>Восстановление</b>\n<blockquote>Выбери копию. Текущая база перед восстановлением "
        "сохранится отдельно — откатиться можно в любой момент.</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows + [BACK]))
    await c.answer()


@router.callback_query(F.data.startswith("bk:r:"))
async def cb_pick(c: CallbackQuery):
    name = c.data.removeprefix("bk:r:")
    path = _find(name)
    if not path:
        await c.answer("Файл не найден", show_alert=True)
        return
    await c.message.edit_text(
        f"♻️ Восстановить базу из копии\n<blockquote>🗂 <b>{escape(backup.describe(path))}</b></blockquote>\n\n"
        "⚠️ Все изменения после этой копии пропадут (новые пользователи, заметки).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("✅ Да, восстановить", f"bk:rr:{name}")],
            [btn("⬇️ Скачать этот файл", f"bk:dl:{name}")],
            BACK]))
    await c.answer()


@router.callback_query(F.data.startswith("bk:dl:"))
async def cb_download(c: CallbackQuery):
    path = _find(c.data.removeprefix("bk:dl:"))
    if not path:
        await c.answer("Файл не найден", show_alert=True)
        return
    await c.answer()
    await _send_backup(c.bot, c.from_user.id, path, "Копия базы")


async def _do_restore(source: Path) -> str:
    safety = await backup.restore(db, source)
    runtime["maintenance"] = await db.get_meta("maintenance") == "1"
    s = await db.stats()
    return (f"✅ <b>База восстановлена</b>\n<blockquote>👥 Пользователей: <b>{s['total']}</b> · "
            f"🎓 {s['students']} · 👨‍🏫 {s['teachers']}\n"
            f"🛟 Прежняя база сохранена: {escape(backup.describe(safety))}</blockquote>")


@router.callback_query(F.data.startswith("bk:rr:"))
async def cb_restore(c: CallbackQuery):
    path = _find(c.data.removeprefix("bk:rr:"))
    if not path:
        await c.answer("Файл не найден", show_alert=True)
        return
    await c.answer("Восстанавливаю…")
    try:
        text = await _do_restore(path)
    except Exception as e:
        text = f"❌ Не удалось восстановить\n<blockquote><code>{escape(str(e))}</code></blockquote>"
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))


@router.callback_query(F.data == "bk:imp")
async def cb_import(c: CallbackQuery, state: FSMContext):
    await state.set_state(ImportState.wait)
    await c.message.edit_text(
        "📥 <b>Импорт пользователей</b>\n\n"
        "Пришли одно из трёх:\n"
        "<blockquote>🗄 <b>schedule.db</b> — старая база (вернутся и группы, и настройки, и заметки)\n\n"
        "📄 <b>users.csv</b> — файл из «📥 Экспорт CSV»\n\n"
        "🔢 <b>список «ID группа»</b> — прямо сообщением или файлом .txt, по одному на строку:\n"
        "<code>123456789 К-11\n987654321 А-1\n555444333 Костюк</code>\n"
        "(для преподавателя — фамилия). Можно и просто ID без группы.</blockquote>\n\n"
        "Имена и @юзернеймы подтяну из Telegram сам. "
        "Тех, кто уже выбрал группу сам, не затираю — только дополняю пустые поля. "
        "Перед импортом сохраню копию текущей базы.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))
    await c.answer()


def _result(stats: dict, title: str) -> str:
    lines = [f"✅ <b>{title}</b>", "<blockquote>"
             f"➕ Добавлено: <b>{stats.get('added', 0)}</b>"]
    if "updated" in stats:
        lines.append(f"🔄 Дополнено: <b>{stats['updated']}</b>")
    lines.append(f"▫️ Уже были: <b>{stats.get('skipped', 0)}</b>")
    if stats.get("notes"):
        lines.append(f"📝 Заметок перенесено: <b>{stats['notes']}</b>")
    if "with_group" in stats:
        lines.append(f"👥 С группой / преподавателем: <b>{stats['with_group']}</b>")
    if stats.get("unresolved"):
        lines.append(f"❔ Группа не найдена на сайте у <b>{stats['unresolved']}</b> — им нужно выбрать заново")
    text = "\n".join(lines) + "</blockquote>"
    bad = stats.get("unresolved_list") or []
    if bad:
        shown = "\n".join(escape(x) for x in bad[:20]) + (f"\n…и ещё {len(bad) - 20}" if len(bad) > 20 else "")
        text += ("\n\n❔ <b>Не понял группу</b> (добавил без неё — проверь написание и пришли эти строки ещё раз):"
                 f"\n<blockquote>{shown}</blockquote>")
    if stats.get("ids"):
        text += "\n\n<i>Имена и юзернеймы подтягиваю из Telegram в фоне…</i>"
    return text


LINE_RE = re.compile(r"^\s*(\d{5,15})\s*[:;,|\t\-–—]?\s*(.*?)\s*$")


async def _resolve(name: str) -> tuple[str, int, str] | None:
    found = await db.search(name, kinds=("g", "t"), limit=10)
    exact = [f for f in found if norm(f[2]) == norm(name)]
    if len(exact) == 1:
        return exact[0]
    if len(found) == 1:
        return found[0]
    return None


async def _import_ids_text(text: str) -> dict | None:
    users, plain_ids, unresolved = [], [], []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if m and m.group(2) and not re.fullmatch(r"[\d\s,;]+", m.group(2)):
            uid, name = int(m.group(1)), m.group(2)
            target = await _resolve(name)
            if target:
                kind, eid, tname = target
                users.append({"user_id": uid, "kind": kind, "target_id": eid, "target_name": tname})
            else:
                users.append({"user_id": uid})
                unresolved.append(f"{uid} {name}")
        else:
            plain_ids += [int(x) for x in ID_RE.findall(line)]
    users += [{"user_id": uid} for uid in plain_ids]
    if not users:
        return None
    await backup.make_backup(db, "before-import")
    merged: dict[int, dict] = {}
    for u in users:
        if u["user_id"] not in merged or u.get("kind"):
            merged[u["user_id"]] = u
    stats = await db.import_users(list(merged.values()))
    stats["with_group"] = sum(1 for u in merged.values() if u.get("kind"))
    stats["unresolved_list"] = unresolved
    stats["ids"] = list(merged)
    return stats


async def _import_csv(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    delim = ";" if first.count(";") >= first.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    if not rows or "user_id" not in rows[0]:
        raise ValueError("в CSV нет колонки user_id")
    kinds = {"студент": "g", "g": "g", "преподаватель": "t", "t": "t"}
    users, unresolved = [], 0
    for r in rows:
        if not (r.get("user_id") or "").strip().isdigit():
            continue
        kind = kinds.get((r.get("kind") or "").strip().lower())
        target_id = int(r["target_id"]) if (r.get("target_id") or "").strip().isdigit() else None
        if kind and not target_id:
            target_id = await db.resolve_target(kind, (r.get("target_name") or "").strip())
            if not target_id:
                unresolved += 1
        users.append({
            "user_id": int(r["user_id"]), "username": r.get("username") or None,
            "full_name": r.get("full_name") or None,
            "kind": kind if target_id else None, "target_id": target_id,
            "target_name": r.get("target_name") or None,
            "notify": r.get("notify") or 1, "banned": r.get("banned") or 0,
            "registered_at": r.get("registered_at") or None, "last_seen": r.get("last_seen") or None,
        })
    await backup.make_backup(db, "before-import")
    stats = await db.import_users(users)
    stats["unresolved"] = unresolved
    return stats


@router.message(ImportState.wait, F.document)
async def got_file(m: Message, state: FSMContext):
    doc = m.document
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await m.answer("Файл больше 20 МБ — Telegram не даст боту его скачать 😔")
        return
    tmp = Path(tempfile.gettempdir()) / f"import_{m.from_user.id}_{doc.file_unique_id}"
    await m.bot.download(doc, destination=tmp)
    name = (doc.file_name or "").lower()
    try:
        if backup.is_sqlite(tmp):
            await state.update_data(path=str(tmp))
            await m.answer(
                "🗄 Это файл базы. Что сделать?\n<blockquote>"
                "🔀 <b>Добавить пользователей</b> — перенесу пользователей и заметки, текущие данные останутся.\n\n"
                "♻️ <b>Заменить базу целиком</b> — бот станет ровно как в этом файле "
                "(текущая база сохранится в бэкапах).</blockquote>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [btn("🔀 Добавить пользователей", "bk:mg")],
                    [btn("♻️ Заменить базу целиком", "bk:rp")],
                    BACK]))
            return
        raw = tmp.read_bytes()
        if name.endswith(".csv") or raw[:40].decode("utf-8-sig", "ignore").lower().startswith("user_id"):
            stats = await _import_csv(raw)
            title = "Импорт из CSV завершён"
        else:
            stats = await _import_ids_text(raw.decode("utf-8", "ignore"))
            title = "Импорт завершён"
            if stats is None:
                await m.answer("🤔 Не нашёл в файле ни одного ID. Пришли .db, .csv или список «ID группа».")
                return
            asyncio.create_task(fill_profiles(m.bot, stats["ids"], m.chat.id))
        tmp.unlink(missing_ok=True)
    except Exception as e:
        log.exception("Импорт")
        await m.answer(f"❌ Не удалось импортировать\n<blockquote><code>{escape(str(e))}</code></blockquote>")
        return
    await state.clear()
    await m.answer(_result(stats, title), reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))


async def fill_profiles(bot: Bot, ids: list[int], admin_chat: int) -> None:
    ok = fail = 0
    for uid in ids:
        try:
            chat = await bot.get_chat(uid)
            full = " ".join(x for x in (chat.first_name, chat.last_name) if x) or None
            await db.fill_profile(uid, chat.username, full)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    try:
        await bot.send_message(admin_chat, f"👤 Профили подтянуты: <b>{ok}</b>"
                               + (f" · не удалось: <b>{fail}</b> (остальное заполнится, когда они зайдут в бота)"
                                  if fail else ""))
    except TelegramAPIError:
        pass


@router.message(ImportState.wait, F.text)
async def got_ids(m: Message, state: FSMContext):
    stats = await _import_ids_text(m.text)
    if stats is None:
        await m.answer("🤔 Не вижу ни одного ID. Пример:\n<code>123456789 К-11\n987654321 Костюк</code>")
        return
    await state.clear()
    await m.answer(_result(stats, "Импорт завершён"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))
    asyncio.create_task(fill_profiles(m.bot, stats["ids"], m.chat.id))


@router.callback_query(F.data.in_({"bk:mg", "bk:rp"}))
async def cb_db_file(c: CallbackQuery, state: FSMContext):
    path = (await state.get_data()).get("path")
    if not path or not Path(path).exists():
        await c.answer("Файл потерялся — пришли его ещё раз", show_alert=True)
        return
    await state.clear()
    await c.answer("Секунду…")
    try:
        if c.data == "bk:mg":
            await backup.make_backup(db, "before-import")
            text = _result(await db.merge_from_db(path), "Пользователи перенесены")
        else:
            text = await _do_restore(Path(path))
    except Exception as e:
        log.exception("Импорт базы")
        text = f"❌ Не получилось\n<blockquote><code>{escape(str(e))}</code></blockquote>"
    finally:
        Path(path).unlink(missing_ok=True)
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))


async def loop(bot: Bot) -> None:
    hh, mm = map(int, BACKUP_TIME.split(":"))
    while True:
        try:
            n = now()
            today = n.date().isoformat()
            late = (n.hour * 60 + n.minute) - (hh * 60 + mm)
            if 0 <= late <= 180 and await db.get_meta("last_backup_date") != today:
                path = await backup.make_backup(db, "auto")
                await db.set_meta("last_backup_date", today)
                log.info("Автобэкап: %s", path)
                for admin_id in ADMIN_IDS:
                    try:
                        await _send_backup(bot, admin_id, path, "Ежедневный бэкап", silent=True)
                    except TelegramAPIError as e:
                        log.warning("Бэкап админу %s не отправлен: %s", admin_id, e)
        except Exception:
            log.exception("Ошибка автобэкапа")
        await asyncio.sleep(60)


