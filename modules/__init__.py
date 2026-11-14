import asyncio

from aiogram import Bot, Dispatcher

from modules import (achievements, admin, admin_premium, admin_stats, alerts, appearance, backup, bells, commands,
                     digest, favorites, feedback, gifts, homewidget, images, inline, middleware, notes, referral, reminders,
                     shop, widget,
                     rooms, schedule, search, settings, start, updater, where, workload)
from utils.core import db, runtime

ROUTERS = [
    admin.router,
    admin_premium.router,
    admin_stats.router,
    backup.router,
    shop.router,
    appearance.router,
    reminders.router,
    favorites.router,
    gifts.router,
    referral.router,
    achievements.router,
    widget.router,
    homewidget.router,
    feedback.router,
    notes.router,
    digest.router,
    where.router,
    workload.router,
    rooms.router,
    images.router,
    start.router,
    settings.router,
    schedule.router,
    bells.router,
    inline.router,
    search.router,
]

_tasks: list[asyncio.Task] = []


def setup(dp: Dispatcher) -> None:
    middleware.setup(dp)
    alerts.setup(dp)
    dp.include_routers(*ROUTERS)


async def on_startup(bot: Bot) -> None:
    await db.connect()
    runtime["maintenance"] = await db.get_meta("maintenance") == "1"
    runtime["bot_username"] = (await bot.get_me()).username
    await commands.setup(bot)
    _tasks.append(asyncio.create_task(updater.loop(bot)))
    _tasks.append(asyncio.create_task(digest.loop(bot)))
    _tasks.append(asyncio.create_task(backup.loop(bot)))
    _tasks.append(asyncio.create_task(reminders.loop(bot)))
    _tasks.append(asyncio.create_task(shop.loop(bot)))
    _tasks.append(asyncio.create_task(shop.payments_loop(bot)))
    _tasks.append(asyncio.create_task(widget.loop(bot)))
    await homewidget.start_server()
