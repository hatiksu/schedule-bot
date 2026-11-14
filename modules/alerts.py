"""🚨 Алерты админам: сайт колледжа не отвечает, пар подозрительно мало, ошибки в коде бота."""
from __future__ import annotations

import time
import traceback
from html import escape

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from config import ADMIN_IDS
from utils.core import log

_last: dict[str, float] = {}  # ключ алерта → когда отправляли (чтобы не спамить)


async def alert(bot: Bot, text: str, key: str | None = None, cooldown: int = 600) -> None:
    if key:
        if time.time() - _last.get(key, 0) < cooldown:
            return
        _last[key] = time.time()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            pass


async def on_error(event: ErrorEvent, bot: Bot) -> None:
    exc = event.exception
    log.exception("Ошибка при обработке апдейта", exc_info=exc)
    where = ""
    tb = traceback.extract_tb(exc.__traceback__)
    if tb:
        last = next((f for f in reversed(tb) if "/modules/" in f.filename or "/utils/" in f.filename), tb[-1])
        where = f"{last.filename.split('/')[-1]}:{last.lineno} в {last.name}()"
    upd = event.update
    kind = upd.event_type if upd else "?"
    detail = ""
    if upd and upd.callback_query:
        detail = f"\nкнопка: <code>{escape(upd.callback_query.data or '')}</code>"
    elif upd and upd.message:
        detail = f"\nсообщение: <code>{escape((upd.message.text or '')[:80])}</code>"
    await alert(bot, f"💥 <b>Ошибка в боте</b>\n<blockquote><code>{escape(type(exc).__name__)}: "
                     f"{escape(str(exc)[:300])}</code>\n📍 {escape(where)}\n🧩 {kind}{detail}</blockquote>",
                key=f"err:{type(exc).__name__}:{where}", cooldown=900)


def setup(dp: Dispatcher) -> None:
    dp.errors.register(on_error)
