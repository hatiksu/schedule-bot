"""🖼 Расписание картинкой (PNG) — день в формате сторис или вся неделя."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from html import escape

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from utils import image
from modules.appearance import bg_photo, theme_for, watermark
from utils.core import db, now
from utils.formatting import KIND_ICON, _times, short_date, week_start

router = Router(name="images")

@router.callback_query(F.data.startswith("img:"))
async def cb_image(c: CallbackQuery):
    _, kind, eid, scope, raw = c.data.split(":")
    eid, d = int(eid), date.fromisoformat(raw)
    await c.answer("🎨 Рисую…")
    name = await db.entity_name(kind, eid) or "?"
    user = await db.get_user(c.from_user.id)
    theme = theme_for(user, await db.owned_themes(c.from_user.id))
    mark = watermark(user)
    updated = await db.get_meta("site_updated")
    short_upd = None
    if updated:  # «23.10.2026 в 13:46» → «23.10 13:46»
        short_upd = updated.replace(" в ", " ")
        if len(short_upd) > 10 and short_upd[5] == ".":
            short_upd = short_upd[:5] + short_upd[10:]
    if scope == "d":
        rows = await db.lessons(kind, eid, raw, raw)
        notes = {p: t for (_, p), t in (await db.notes(c.from_user.id, kind, eid, raw, raw)).items()}
        now_pair = None
        n = now()
        if d == n.date():
            for r in rows:
                tt = _times(r["time"])
                if tt and tt[0] <= n.time() <= tt[1]:
                    now_pair = r["pair"]
        png = await asyncio.to_thread(image.render_day, kind, name, d, rows, notes,
                                      mark, short_upd, now_pair, theme, bg_photo(user))
        caption = f"{KIND_ICON[kind]} <b>{escape(name)}</b> · {short_date(d)}"
        fname = f"{name}_{d:%d-%m}.png"
    else:
        monday = week_start(d)
        end = (monday + timedelta(days=6)).isoformat()
        rows = await db.lessons(kind, eid, monday.isoformat(), end)
        notes = await db.notes(c.from_user.id, kind, eid, monday.isoformat(), end)
        png = await asyncio.to_thread(image.render_week, kind, name, monday, rows, notes,
                                      mark, short_upd, theme, bg_photo(user))
        caption = f"{KIND_ICON[kind]} <b>{escape(name)}</b> · неделя с {short_date(monday)}"
        fname = f"{name}_week_{monday:%d-%m}.png"
    await c.message.answer_photo(BufferedInputFile(png, filename=fname), caption=caption)
