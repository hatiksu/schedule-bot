from __future__ import annotations

import asyncio
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto

from modules.appearance import show
from utils.charts import chart
from utils.core import btn, db, now
from utils.filters import IsAdmin

router = Router(name="admin_stats")
router.callback_query.filter(IsAdmin())

LABELS = {
    "schedule": "📅 Расписание", "img": "🖼 Картинки", "notes": "📝 Заметки", "rooms": "🏫 Аудитории",
    "where": "📍 Где препод", "workload": "📊 Нагрузка", "digest": "⏰ Рассылки (настройка)",
    "appearance": "🎨 Оформление", "premium": "⭐ Premium (меню)", "favorites": "⭐ Избранное",
    "reminders": "⏳ Напоминания", "bells": "⏰ Звонки", "settings": "⚙️ Настройки", "feedback": "✉️ Обратная связь",
    "gifts": "🎁 Подарки", "referral": "🤝 Приглашения", "achievements": "🏆 Достижения", "widget": "📱 Виджет",
    "setup": "👋 Выбор группы", "inline": "💬 Inline-режим", "search": "🔎 Поиск (кнопка)",
    "text": "🔎 Поиск текстом", "payment": "💰 Оплаты",
}


def label(name: str) -> str:
    if name.startswith("cmd:"):
        return f"⌨️ /{name[4:]}"
    return LABELS.get(name, name)


@router.callback_query(F.data.startswith("adm:fs"))
async def cb_features(c: CallbackQuery):
    days = 30 if c.data == "adm:fs:30" else 7
    n = now()
    since = (n.date() - timedelta(days=days - 1)).isoformat()
    stats = await db.feature_stats(since)
    usage = await db.usage_counts(n.strftime("%Y-%m-%d %H:%M:%S"))
    total = sum(r["c"] for r in stats) or 1
    lines = [f"{label(r['name'])} — <b>{r['c']}</b> · {r['u']} чел. · {r['c'] * 100 // total}%"
             for r in stats[:18] if r["name"] != "other"]
    inviters = await db.top_inviters(3)
    top_inv = "\n".join(f"{i}. {u['full_name'] or u['user_id']} — {u['c']}" for i, u in enumerate(inviters, 1))
    text = (
        f"📊 <b>Статистика фич</b> · {days} дней\n\n"
        "<b>Что жмут</b>\n<blockquote>" + ("\n".join(lines) or "пока нет данных") + "</blockquote>\n"
        "<b>Сколько человек пользуется</b>\n<blockquote>"
        f"⏰ авторассылкой: <b>{usage['digest']}</b>\n"
        f"⏳ напоминаниями: <b>{usage['remind']}</b> · 📱 виджетом: <b>{usage['widget']}</b>\n"
        f"📝 заметками: <b>{usage['notes_users']}</b> · ⭐ избранным: <b>{usage['fav_users']}</b>\n"
        f"🎨 своей темой: <b>{usage['themed']}</b>\n"
        f"🔕 выключили уведомления о заменах: <b>{usage['notify_off']}</b></blockquote>"
        + (f"\n<b>🤝 Топ приглашающих</b>\n<blockquote>{top_inv}</blockquote>" if inviters else "")
    )
    await show(c, text, InlineKeyboardMarkup(inline_keyboard=[
        [btn("• 7 дней" if days == 7 else "7 дней", "adm:fs:7"), btn("• 30 дней" if days == 30 else "30 дней", "adm:fs:30")],
        [btn("📈 Графики", "adm:charts")], [btn("◀️ В админку", "adm:home")]]))
    await c.answer()


@router.callback_query(F.data == "adm:charts")
async def cb_charts(c: CallbackQuery):
    await c.answer("📈 Рисую графики…")
    n = now()
    days = [n.date() - timedelta(days=i) for i in range(29, -1, -1)]
    s = await db.daily_series(days[0].isoformat())
    keys = [d.isoformat() for d in days]
    labels = [f"{d:%d.%m}" for d in days]
    new = [s["new"].get(k, 0) for k in keys]
    cum, acc = [], s["base"]
    for v in new:
        acc += v
        cum.append(acc)
    dau = [s["dau"].get(k, 0) for k in keys]
    stars = [s["stars"].get(k, 0) for k in keys]
    rub = [s.get("rub", {}).get(k, 0) for k in keys]
    jobs = [
        asyncio.to_thread(chart, "Пользователи", f"всего {cum[-1]} · за 30 дней +{sum(new)}", labels,
                          bars=new, line=cum, bar_name="новые за день", line_name="всего"),
        asyncio.to_thread(chart, "Активность", f"в среднем {sum(dau) / 30:.0f} человек в день", labels,
                          bars=dau, bar_color=(255, 154, 60), bar_name="активных за день"),
        asyncio.to_thread(chart, "Выручка", f"за 30 дней {sum(stars)} ⭐", labels,
                          bars=stars, bar_color=(255, 210, 63), bar_name="звёзд за день"),
    ]
    names = ["users", "activity", "revenue"]
    if sum(rub):
        jobs.append(asyncio.to_thread(chart, "Выручка в рублях", f"за 30 дней {sum(rub)} ₽", labels,
                                      bars=rub, bar_color=(61, 220, 132), bar_name="₽ за день"))
        names.append("revenue-rub")
    charts = await asyncio.gather(*jobs)
    media = [InputMediaPhoto(media=BufferedInputFile(png, f"{nm}.png"),
                             caption="📈 <b>Графики за 30 дней</b>" if i == 0 else None)
             for i, (png, nm) in enumerate(zip(charts, names, strict=False))]
    await c.message.answer_media_group(media)
