"""Бот расписания колледжа — точка входа. Вся логика в modules/, общее — в utils/."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import modules
from config import BOT_TOKEN
from modules.updater import run_update
from utils.core import db


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан — создай .env по примеру .env.example")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(db=db, run_update=run_update)
    modules.setup(dp)
    await modules.on_startup(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
