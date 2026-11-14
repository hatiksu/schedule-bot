import asyncio
import time
from html import escape
from collections import defaultdict
from datetime import date

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from config import ALERT_AFTER, UPDATE_INTERVAL
from modules.alerts import alert
from utils.core import btn, db, log, nav_kb, now
from utils.formatting import format_changes, short_date, split_text
from utils.site_parser import fetch_all, fetch_updated

update_lock = asyncio.Lock()


async def run_update(bot: Bot, force: bool = False) -> int | None:
    async with update_lock:
        stamp = now().strftime("%d.%m %H:%M")
        t0 = time.monotonic()

        def ms() -> int:
            return int((time.monotonic() - t0) * 1000)

        try:
            stored = await db.get_meta("site_updated")
            if not force and stored:
                remote = await fetch_updated()
                if remote and remote == stored:
                    await db.set_meta("last_update_at", stamp)
                    await db.set_meta("last_update_ok", "1")
                    await db.log_update(True, force, None, None, ms())
                    return None
            snap = await fetch_all()
            changes, old_max = await db.replace_snapshot(snap, now().date().isoformat())
            await db.set_meta("site_updated", snap.updated or "")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            await db.set_meta("last_update_at", stamp)
            await db.set_meta("last_update_ok", "0")
            await db.set_meta("last_update_error", err)
            await db.log_update(False, force, None, None, ms(), err)
            streak = int(await db.get_meta("fail_streak") or 0) + 1
            await db.set_meta("fail_streak", str(streak))
            if streak == ALERT_AFTER:
                await alert(bot, f"🚨 <b>Сайт колледжа не отвечает</b>\n<blockquote>{streak} неудачных проверок "
                                 f"подряд.\n<code>{escape(err[:300])}</code></blockquote>\n"
                                 "Пользователи видят последнее загруженное расписание.")
            raise
        streak = int(await db.get_meta("fail_streak") or 0)
        if streak >= ALERT_AFTER:
            await alert(bot, f"✅ <b>Сайт снова доступен</b>\n<blockquote>после {streak} неудачных проверок</blockquote>")
        if streak:
            await db.set_meta("fail_streak", "0")
        prev = int(await db.get_meta("last_update_count") or 0)
        if prev and len(snap.lessons) < prev * 0.5:
            await alert(bot, f"⚠️ <b>Подозрительно мало пар</b>\n<blockquote>было {prev}, стало {len(snap.lessons)}."
                             "\nВозможно, на сайте сменилась вёрстка или расписание выложено частично.</blockquote>",
                        key="few_lessons", cooldown=6 * 3600)
        await db.set_meta("last_update_at", stamp)
        await db.set_meta("last_update_ok", "1")
        await db.set_meta("last_update_count", str(len(snap.lessons)))
        changed_days = len([k for k in changes if k[0] == "g"])
        await db.log_update(True, force, len(snap.lessons), changed_days, ms())
        log.info("Расписание обновлено: %s пар, изменений: %s", len(snap.lessons), len(changes))
        if stored is not None:
            await notify(bot, changes, old_max, snap.groups)
        return len(snap.lessons)


async def notify(bot: Bot, changes: dict, old_max: str | None, group_names: dict[int, str]) -> None:
    by_target: dict[tuple, dict] = defaultdict(dict)
    for (kind, eid, d), pair in changes.items():
        by_target[(kind, eid)][d] = pair
    for (kind, eid), days in by_target.items():
        users = await db.users_for(kind, eid)
        if not users:
            continue
        name = await db.entity_name(kind, eid) or "?"
        built = format_changes(kind, name, days, old_max, group_names)
        if not built:
            continue
        text, first = built
        nav = nav_kb(kind, eid, "d", date.fromisoformat(first))
        kb = InlineKeyboardMarkup(inline_keyboard=[[btn(f"👀 Смотреть {short_date(first)}",
                                                        f"v:{kind}:{eid}:d:{first}")]] + nav.inline_keyboard)
        chunks = split_text(text)
        for uid in users:
            try:
                for i, chunk in enumerate(chunks):
                    await bot.send_message(uid, chunk, reply_markup=kb if i == len(chunks) - 1 else None)
            except TelegramForbiddenError:
                pass
            except TelegramAPIError as e:
                log.warning("Не отправил %s: %s", uid, e)
            await asyncio.sleep(0.05)


async def loop(bot: Bot) -> None:
    while True:
        try:
            await run_update(bot)
        except Exception:
            log.exception("Ошибка обновления расписания")
        await asyncio.sleep(UPDATE_INTERVAL)
