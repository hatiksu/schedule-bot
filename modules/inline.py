"""💬 Inline-режим: «@бот К-11» в любом чате → расписание на сегодня / завтра / неделю."""
from datetime import timedelta

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import (InlineQuery, InlineQueryResultArticle, InlineQueryResultsButton,
                           InputTextMessageContent)

from utils.core import KIND_ICON, chosen_name, db, now, render
from utils.formatting import day_summary, short_date, study_day, week_start

router = Router(name="inline")


@router.inline_query()
async def inline_query(q: InlineQuery):
    text = q.query.strip()
    if text:
        found = await db.search(text, limit=5)
    else:  # пустой запрос — своё расписание
        user = await db.get_user(q.from_user.id)
        found = [(user["kind"], user["target_id"], await chosen_name(user))] if user and user["kind"] else []
    if not found:
        await q.answer([], cache_time=30, is_personal=True, button=InlineQueryResultsButton(
            text="Выбрать группу в боте", start_parameter="inline"))
        return

    today = now().date()
    variants = [("d", today, "Сегодня"), ("d", study_day(today, 1), "Завтра"),
                ("w", week_start(today) + timedelta(days=7 if today.weekday() == 6 else 0), "Неделя")]
    results = []
    for kind, eid, name in found:
        for scope, d, label in variants:
            chunks, kb = await render(kind, eid, scope, d, private=False)
            if scope == "d":
                desc = f"{short_date(d)} · {day_summary(await db.lessons(kind, eid, d.isoformat(), d.isoformat()))}"
            else:
                desc = f"с {short_date(d)} · вся неделя"
            results.append(InlineQueryResultArticle(
                id=f"{kind}{eid}:{scope}:{d}",
                title=f"{KIND_ICON[kind]} {name} — {label}",
                description=desc,
                input_message_content=InputTextMessageContent(message_text=chunks[0], parse_mode=ParseMode.HTML),
                reply_markup=kb,
            ))
    await q.answer(results[:50], cache_time=60, is_personal=not text)
