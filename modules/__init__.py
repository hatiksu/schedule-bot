"""Все модули бота. Каждый — отдельный файл со своим роутером.

Порядок подключения важен: модули, которые ждут ввода текста (заметка, поиск препода,
обращение…), идут раньше общего поиска, а search — самым последним.
"""
import asyncio

from aiogram import Bot, Dispatcher

from modules import (achievements, admin, admin_premium, admin_stats, alerts, appearance, backup, bells, commands,
                     digest, favorites, feedback, gifts, homewidget, images, inline, middleware, notes, referral, reminders,
                     shop, widget,
                     rooms, schedule, search, settings, start, updater, where, workload)
from utils.core import db, runtime

ROUTERS = [
    admin.router,      # 🛠 админ-панель
    admin_premium.router,  # ⭐ продажи, промокоды, выдача Premium
    admin_stats.router,  # 📊 статистика фич и 📈 графики
    backup.router,     # 💾 бэкапы и импорт
    shop.router,       # ⭐ Premium, оплата звёздами
    appearance.router,  # 🎨 оформление и темы
    reminders.router,  # ⏳ напоминания перед парой
    favorites.router,  # ⭐ избранное
    gifts.router,      # 🎁 подарить Premium
    referral.router,   # 🤝 пригласить друзей
    achievements.router,  # 🏆 достижения
    widget.router,     # 📱 виджет дня
    homewidget.router,  # 📲 виджет на рабочий стол телефона
    feedback.router,   # ✉️ обратная связь
    notes.router,      # 📝 заметки к парам
    digest.router,     # ⏰ авторассылка
    where.router,      # 📍 где препод
    workload.router,   # 📊 нагрузка
    rooms.router,      # 🏫 свободные аудитории
    images.router,     # 🖼 картинка-расписание
    start.router,      # 👋 /start, выбор группы
    settings.router,   # ⚙️ настройки
    schedule.router,   # 📅 расписание
    bells.router,      # ⏰ звонки
    inline.router,     # 💬 inline-режим
    search.router,     # 🔎 поиск — ПОСЛЕДНИМ
]

_tasks: list[asyncio.Task] = []


def setup(dp: Dispatcher) -> None:
    middleware.setup(dp)
    alerts.setup(dp)    # 🚨 ошибки в коде — админам
    dp.include_routers(*ROUTERS)


async def on_startup(bot: Bot) -> None:
    await db.connect()
    runtime["maintenance"] = await db.get_meta("maintenance") == "1"
    runtime["bot_username"] = (await bot.get_me()).username
    await commands.setup(bot)
    _tasks.append(asyncio.create_task(updater.loop(bot)))   # 🔄 проверка сайта
    _tasks.append(asyncio.create_task(digest.loop(bot)))    # ⏰ авторассылка
    _tasks.append(asyncio.create_task(backup.loop(bot)))    # 💾 ежедневный бэкап
    _tasks.append(asyncio.create_task(reminders.loop(bot)))  # ⏳ напоминания
    _tasks.append(asyncio.create_task(shop.loop(bot)))      # ⭐ «Premium скоро закончится»
    _tasks.append(asyncio.create_task(widget.loop(bot)))    # 📱 обновление виджетов
    await homewidget.start_server()                         # 📲 картинки для виджетов на экран
