"""⭐ Избранное (Premium): несколько групп / преподавателей / аудиторий с быстрым переключением.
Добавить — кнопкой ☆ под чужим расписанием (найди через поиск)."""
from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from modules.appearance import show
from utils.core import btn, db, render
from utils.formatting import KIND_ICON
from utils.premium import FAV_LIMIT, PAYWALL_KB, is_premium, paywall

router = Router(name="favorites")


async def list_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    favs = await db.favorites(uid)
    if not favs:
        text = ("⭐ <b>Избранное</b>\n<blockquote>Пока пусто. Найди группу, преподавателя или аудиторию "
                "через 🔎 Поиск и нажми <b>☆</b> под расписанием.</blockquote>")
        rows = []
    else:
        text = (f"⭐ <b>Избранное</b> · {len(favs)}/{FAV_LIMIT}\n"
                "<blockquote>Нажми, чтобы открыть расписание на сегодня. ✖️ — убрать.</blockquote>")
        rows = [[btn(f"{KIND_ICON[k]} {name}", f"v:{k}:{i}:d:t"), btn("✖️", f"fav:x:{k}:{i}")]
                for k, i, name in favs]
    rows.append([btn("◀️ К настройкам", "st:home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("fav"))
async def cmd_fav(m: Message):
    text, kb = await list_view(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "fav:list")
async def cb_list(c: CallbackQuery):
    text, kb = await list_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("fav:x:"))
async def cb_remove(c: CallbackQuery):
    _, _, kind, eid = c.data.split(":")
    await db.remove_favorite(c.from_user.id, kind, int(eid))
    text, kb = await list_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer("Убрано из избранного")


# fav:t:<kind>:<id>:<scope>:<date> — кнопка ☆/★ под расписанием
@router.callback_query(F.data.startswith("fav:t:"))
async def cb_toggle(c: CallbackQuery):
    _, _, kind, eid, scope, raw = c.data.split(":")
    eid = int(eid)
    uid = c.from_user.id
    if await db.is_favorite(uid, kind, eid):
        await db.remove_favorite(uid, kind, eid)
        note = "Убрано из избранного"
    else:
        if not is_premium(await db.get_user(uid)):
            await c.message.answer(paywall("Избранное"), reply_markup=PAYWALL_KB)
            await c.answer()
            return
        if len(await db.favorites(uid)) >= FAV_LIMIT:
            await c.answer(f"В избранном максимум {FAV_LIMIT}. Убери что-нибудь в /fav", show_alert=True)
            return
        await db.add_favorite(uid, kind, eid)
        note = "⭐ Добавлено в избранное — открывай через /fav"
    _, kb = await render(kind, eid, scope, date.fromisoformat(raw), uid=uid)
    try:
        await c.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        pass
    await c.answer(note)
