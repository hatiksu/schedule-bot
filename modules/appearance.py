"""🎨 Оформление: темы картинок (с превью), цвет акцента, фон, подпись бота, стиль сообщений, эмодзи."""
from __future__ import annotations

import asyncio


from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from PIL import Image

from config import DATA_DIR

from modules.shop import send_invoice
from utils import image
from utils.core import btn, db, now, runtime
from utils.formatting import study_day
from utils.premium import (ACCENTS, BACKGROUNDS, EMOJI_SETS, PAYWALL_KB, STYLES, THEMES,
                           can_use_theme, is_premium, paywall)
from utils.themes import build

router = Router(name="appearance")
BACK = [btn("◀️ К оформлению", "ap:menu")]


async def show(c: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    """Редактирует сообщение, а если это фото (превью) — присылает новое."""
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except TelegramAPIError:
        await c.message.answer(text, reply_markup=kb)


def theme_for(user: dict | None, owned: set[str], theme_id: str | None = None):
    """Тема пользователя с учётом доступа: чужие платные темы и цвета без Premium не применяются."""
    user = user or {}
    tid = theme_id or user.get("theme") or "classic"
    if not can_use_theme(user, tid, owned) and theme_id is None:
        tid = "classic"
    prem = is_premium(user)
    acc = ACCENTS.get(user.get("accent") or "", (None, None))[1] if prem else None
    bg = BACKGROUNDS.get(user.get("bg") or "", (None, None))[1] if prem else None
    return build(tid, acc, bg)


def bg_photo(user: dict | None) -> str | None:
    """Путь к своему фото на фоне (только для Premium)."""
    if not is_premium(user) or not (user or {}).get("bg_photo"):
        return None
    path = Path(DATA_DIR) / "bg" / f"{user['user_id']}.jpg"
    return str(path) if path.exists() else None


def watermark(user: dict | None) -> str | None:
    return None if is_premium(user) and (user or {}).get("no_watermark") else runtime["bot_username"]


SAMPLE = [
    dict(date="", pair=1, time="8:00–9:20", subject="История", rooms="2-25", teachers="Костюк Ю.Ю", group_name="А-1"),
    dict(date="", pair=2, time="9:30–10:50", subject="Математика", rooms="2-13", teachers="Киселева И.И.",
         group_name="А-1"),
    dict(date="", pair=4, time="12:50–14:10", subject="Физическая культура", rooms="Спортзал",
         teachers="Петров П.П.", group_name="А-1"),
]


async def preview(uid: int, theme_id: str | None = None) -> bytes:
    user = await db.get_user(uid) or {}
    owned = await db.owned_themes(uid)
    t = theme_for(user, owned, theme_id)
    kind, eid = user.get("kind") or "g", user.get("target_id")
    d = now().date()
    rows, name = [], "Моя группа"
    if eid:
        name = await db.entity_name(kind, eid) or name
        for _ in range(7):  # ближайший день с парами — чтобы превью было «живым»
            rows = await db.lessons(kind, eid, d.isoformat(), d.isoformat())
            if rows:
                break
            d = study_day(d, 1)
    if not rows:
        rows, d = [{**r, "date": d.isoformat()} for r in SAMPLE], d
    return await asyncio.to_thread(image.render_day, kind, name, d, rows, {rows[0]["pair"]: "пример заметки"},
                                   watermark(user), None, rows[min(1, len(rows) - 1)]["pair"], t,
                                   bg_photo(user))


# ---------- главное меню оформления ----------
async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid) or {}
    prem = is_premium(user)
    lock = "" if prem else " ⭐"
    tname, temoji, _ = THEMES.get(user.get("theme") or "classic", THEMES["classic"])
    acc = ACCENTS.get(user.get("accent") or "", ("из темы",))[0]
    bg = BACKGROUNDS.get(user.get("bg") or "", ("из темы",))[0]
    style = STYLES.get(user.get("msg_style") or "normal")
    emoji = EMOJI_SETS.get(user.get("emoji_set") or "classic", EMOJI_SETS["classic"])[0]
    wm = "без подписи" if user.get("no_watermark") else "с подписью бота"
    text = (
        "🎨 <b>Оформление</b>\n\n<blockquote>"
        f"🖼 Тема картинки: <b>{temoji} {tname}</b>\n"
        f"🎨 Акцент: <b>{acc}</b> · 🌗 Фон: <b>{bg}</b>\n"
        f"🖼 Фото на фоне: <b>{'своё' if user.get('bg_photo') else 'нет'}</b> · 🏷 <b>{wm}</b>\n"
        f"💬 Стиль сообщений: <b>{style}</b>\n"
        f"😀 Эмодзи: <b>{emoji}</b></blockquote>"
        + ("" if prem else "\n\n⭐ — доступно в Premium")
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("🖼 Тема картинки", "ap:themes"), btn("👀 Превью", "ap:pv")],
        [btn("🎨 Цвет акцента" + lock, "ap:acc"), btn("🌗 Фон" + lock, "ap:bg")],
        [btn("🖼 Своё фото на фон" + lock, "ap:photo")],
        [btn(("🏷 Вернуть подпись" if user.get("no_watermark") else "🏷 Убрать подпись бота") + lock, "ap:wm")],
        [btn("💬 Стиль сообщений" + lock, "ap:style"), btn("😀 Эмодзи" + lock, "ap:emoji")],
        [btn("◀️ К настройкам", "st:home")],
    ])
    return text, kb


@router.callback_query(F.data == "ap:menu")
async def cb_menu(c: CallbackQuery):
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data == "ap:pv")
async def cb_preview(c: CallbackQuery):
    await c.answer("🎨 Рисую превью…")
    png = await preview(c.from_user.id)
    await c.message.answer_photo(BufferedInputFile(png, "preview.png"), caption="👀 Так выглядит твоя картинка",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[BACK]))


# ---------- темы ----------
@router.callback_query(F.data == "ap:themes")
async def cb_themes(c: CallbackQuery):
    user = await db.get_user(c.from_user.id) or {}
    owned = await db.owned_themes(c.from_user.id)
    current = user.get("theme") or "classic"
    rows = []
    for tid, (name, emoji, price) in THEMES.items():
        if tid == current:
            tag = "✅"
        elif price == 0:
            tag = "бесплатно"
        elif tid in owned:
            tag = "твоя"
        elif is_premium(user):
            tag = "Premium"
        else:
            tag = f"{price} ⭐"
        rows.append([btn(f"{emoji} {name} · {tag}", f"ap:th:{tid}")])
    rows.append(BACK)
    await show(c, "🖼 <b>Тема картинки-расписания</b>\n<blockquote>Нажми на тему — покажу превью "
                  "на твоём расписании. Купленная тема остаётся навсегда, а в Premium открыты все.</blockquote>",
               InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("ap:th:"))
async def cb_theme(c: CallbackQuery):
    tid = c.data.split(":")[2]
    if tid not in THEMES:
        await c.answer()
        return
    await c.answer("🎨 Рисую превью…")
    user = await db.get_user(c.from_user.id) or {}
    owned = await db.owned_themes(c.from_user.id)
    name, emoji, price = THEMES[tid]
    png = await preview(c.from_user.id, tid)
    if can_use_theme(user, tid, owned):
        rows = [[btn("✅ Включить эту тему", f"ap:set:{tid}")]]
    else:
        rows = [[btn(f"⭐ Купить навсегда — {price} ⭐", f"ap:buy:{tid}")],
                [btn("⭐ Все темы в Premium", "pm:menu")]]
    rows.append([btn("◀️ К темам", "ap:themes")])
    await c.message.answer_photo(BufferedInputFile(png, f"{tid}.png"), caption=f"{emoji} <b>{name}</b>",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("ap:set:"))
async def cb_set_theme(c: CallbackQuery):
    tid = c.data.split(":")[2]
    user = await db.get_user(c.from_user.id) or {}
    if not can_use_theme(user, tid, await db.owned_themes(c.from_user.id)):
        await c.answer("Эта тема ещё не куплена", show_alert=True)
        return
    await db.set_pref(c.from_user.id, "theme", tid)
    await c.answer(f"✅ Тема «{THEMES[tid][0]}» включена", show_alert=True)


@router.callback_query(F.data.startswith("ap:buy:"))
async def cb_buy_theme(c: CallbackQuery):
    tid = c.data.split(":")[2]
    name, emoji, price = THEMES.get(tid, ("", "", 0))
    if not price:
        await c.answer()
        return
    await send_invoice(c.message, f"theme:{tid}", f"{emoji} Тема «{name}»",
                       "Тема картинки-расписания — твоя навсегда.")
    await c.answer()


# ---------- Premium-настройки ----------
async def _gate(c: CallbackQuery, feature: str) -> bool:
    user = await db.get_user(c.from_user.id)
    if is_premium(user):
        return True
    await show(c, paywall(feature), PAYWALL_KB)
    await c.answer()
    return False


def _options(prefix: str, items: dict, current: str | None, default_label: str | None = None):
    rows, row = [], []
    for key, val in items.items():
        label = val[0] if isinstance(val, tuple) else val
        row.append(btn(("✅ " if key == current else "") + label, f"{prefix}:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if default_label:
        rows.append([btn(("✅ " if not current else "") + default_label, f"{prefix}:-")])
    rows.append(BACK)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "ap:acc")
async def cb_accent(c: CallbackQuery):
    if await _gate(c, "Свой цвет акцента"):
        user = await db.get_user(c.from_user.id)
        await show(c, "🎨 <b>Цвет акцента</b>\n<blockquote>Полоска, номер текущей пары, подпись</blockquote>",
                   _options("ap:a", ACCENTS, user.get("accent"), "↩️ Как в теме"))
        await c.answer()


@router.callback_query(F.data == "ap:bg")
async def cb_bg(c: CallbackQuery):
    if await _gate(c, "Свой фон"):
        user = await db.get_user(c.from_user.id)
        await show(c, "🌗 <b>Фон картинки</b>\n<blockquote>Цвета текста и карточек подстроятся сами</blockquote>",
                   _options("ap:b", BACKGROUNDS, user.get("bg"), "↩️ Как в теме"))
        await c.answer()


@router.callback_query(F.data.startswith("ap:a:") | F.data.startswith("ap:b:"))
async def cb_color(c: CallbackQuery):
    if not await _gate(c, "Свой цвет и фон"):
        return
    _, which, key = c.data.split(":")
    field = "accent" if which == "a" else "bg"
    await db.set_pref(c.from_user.id, field, None if key == "-" else key)
    await c.answer("🎨 Рисую превью…")
    png = await preview(c.from_user.id)
    await c.message.answer_photo(BufferedInputFile(png, "preview.png"), caption="✅ Сохранено — вот как теперь",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [btn("🎨 Другой цвет" if which == "a" else "🌗 Другой фон",
                                          "ap:acc" if which == "a" else "ap:bg")], BACK]))


@router.callback_query(F.data == "ap:wm")
async def cb_watermark(c: CallbackQuery):
    if not await _gate(c, "Картинка без подписи бота"):
        return
    user = await db.get_user(c.from_user.id)
    await db.set_pref(c.from_user.id, "no_watermark", 0 if user.get("no_watermark") else 1)
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer("Готово")


STYLE_HINTS = {
    "normal": "каждая пара — отдельной цитатой",
    "compact": "все пары одним блоком, по строке на пару",
    "detailed": "плюс длительность пары и перемены",
}


@router.callback_query(F.data == "ap:style")
async def cb_style(c: CallbackQuery):
    if await _gate(c, "Стиль сообщений"):
        user = await db.get_user(c.from_user.id)
        hints = "\n".join(f"<b>{STYLES[k]}</b> — {v}" for k, v in STYLE_HINTS.items())
        await show(c, f"💬 <b>Стиль сообщений</b>\n<blockquote>{hints}</blockquote>",
                   _options("ap:s", STYLES, user.get("msg_style") or "normal"))
        await c.answer()


@router.callback_query(F.data == "ap:emoji")
async def cb_emoji(c: CallbackQuery):
    if await _gate(c, "Наборы эмодзи"):
        user = await db.get_user(c.from_user.id)
        examples = "\n".join(
            f"<b>{name}</b>: {' '.join(v for v in (s['subj'], s['room'], s['teacher'], s['now']) if v)}"
            for name, s in EMOJI_SETS.values())
        await show(c, f"😀 <b>Эмодзи в расписании</b>\n<blockquote>{examples}</blockquote>",
                   _options("ap:e", EMOJI_SETS, user.get("emoji_set") or "classic"))
        await c.answer()


@router.callback_query(F.data.startswith("ap:s:") | F.data.startswith("ap:e:"))
async def cb_style_set(c: CallbackQuery):
    if not await _gate(c, "Стиль и эмодзи"):
        return
    _, which, key = c.data.split(":")
    await db.set_pref(c.from_user.id, "msg_style" if which == "s" else "emoji_set", key)
    from utils.core import render  # показываем сразу, как выглядит
    user = await db.get_user(c.from_user.id)
    await c.answer("✅ Сохранено")
    if user.get("kind"):
        chunks, kb = await render(user["kind"], user["target_id"], "d", now().date(), uid=c.from_user.id)
        await c.message.answer(chunks[0], reply_markup=kb)


# ---------- своё фото на фоне ----------
class PhotoState(StatesGroup):
    wait = State()


@router.callback_query(F.data == "ap:photo")
async def cb_photo(c: CallbackQuery, state: FSMContext):
    if not await _gate(c, "Своё фото на фоне"):
        return
    user = await db.get_user(c.from_user.id)
    await state.set_state(PhotoState.wait)
    rows = [[btn("🗑 Убрать фото", "ap:photo:del")]] if user.get("bg_photo") else []
    await show(c, "🖼 <b>Своё фото на фон</b>\n<blockquote>Пришли фото — любое: котик, вид из окна, "
                  "любимый арт. Я подрежу его под сторис и притемню, чтобы расписание читалось.</blockquote>",
               InlineKeyboardMarkup(inline_keyboard=rows + [BACK]))
    await c.answer()


@router.callback_query(F.data == "ap:photo:del")
async def cb_photo_del(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await db.set_pref(c.from_user.id, "bg_photo", 0)
    (Path(DATA_DIR) / "bg" / f"{c.from_user.id}.jpg").unlink(missing_ok=True)
    text, kb = await menu_view(c.from_user.id)
    await show(c, text, kb)
    await c.answer("Фото убрано")


def _prepare_photo(src: Path, dst: Path) -> None:
    img = Image.open(src).convert("RGB")
    img.thumbnail((1600, 2400))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=85)


@router.message(PhotoState.wait, F.photo | F.document)
async def got_photo(m: Message, state: FSMContext):
    if not is_premium(await db.get_user(m.from_user.id)):
        await state.clear()
        await m.answer(paywall("Своё фото на фоне"), reply_markup=PAYWALL_KB)
        return
    file = m.photo[-1] if m.photo else m.document
    if m.document and not (m.document.mime_type or "").startswith("image/"):
        await m.answer("Это не картинка 🤔 Пришли фото.")
        return
    tmp = Path(DATA_DIR) / "bg" / f"{m.from_user.id}.upload"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    await m.bot.download(file, destination=tmp)
    try:
        await asyncio.to_thread(_prepare_photo, tmp, Path(DATA_DIR) / "bg" / f"{m.from_user.id}.jpg")
    except Exception:
        await m.answer("Не получилось открыть картинку 😔 Попробуй другую.")
        return
    finally:
        tmp.unlink(missing_ok=True)
    await state.clear()
    await db.set_pref(m.from_user.id, "bg_photo", 1)
    png = await preview(m.from_user.id)
    await m.answer_photo(BufferedInputFile(png, "preview.png"), caption="✅ Фото на фоне сохранено — вот как теперь",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [btn("🖼 Другое фото", "ap:photo")], BACK]))
