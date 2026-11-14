"""📲 Виджет на рабочем столе телефона (Premium).

Бот поднимает маленький веб-сервер и по личной секретной ссылке отдаёт картинку с расписанием
на сегодня (вечером — на завтра) в теме пользователя:
    {PUBLIC_URL}/w/<token>.png?size=s|m|l
iPhone показывает её через приложение Scriptable (готовый скрипт присылает бот),
Android — через KWGT или любое приложение «картинка по ссылке».
"""
from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiohttp import web
from PIL import Image, ImageDraw

from config import PUBLIC_URL, TZ, WEB_PORT
from modules.appearance import bg_photo, show, theme_for
from utils.core import btn, db, log, now, runtime
from utils.formatting import WD_SHORT, _merge, _times, pairs_word, relative, study_day
from utils.image import F_BOLD, F_REG
from utils.premium import PAYWALL_KB, is_premium, paywall
from utils.widget_image import SIZES, _status, render_widget

router = Router(name="homewidget")
_cache: dict[tuple, tuple[float, bytes]] = {}


# ======================= картинка =======================
def _message_png(title: str, text: str, size: str = "m") -> bytes:
    W, H = SIZES.get(size, SIZES["m"])
    img = Image.new("RGB", (W, H), (15, 17, 22))
    d = ImageDraw.Draw(img)
    d.text((38, 40), title, font=F_BOLD(34 if size == "s" else 40), fill=(240, 242, 246))
    y = 110
    for line in text.split("\n"):
        d.text((38, y), line, font=F_REG(26 if size == "s" else 30), fill=(146, 152, 166))
        y += 44
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def pick_day(user: dict):
    """Какой день показывать: сегодня, а если пары уже закончились или их нет — ближайший день с парами."""
    n = now()
    kind, eid = user["kind"], user["target_id"]
    d = n.date()
    items = [] if d.weekday() == 6 else _merge(await db.lessons(kind, eid, d.isoformat(), d.isoformat()))
    last = _times(items[-1]["time"]) if items else None
    if not items or (last and n.time() > last[1]):
        nd = d
        for _ in range(7):
            nd = study_day(nd, 1)
            if await db.lessons(kind, eid, nd.isoformat(), nd.isoformat()):
                break
        d = nd
    label = relative(d, n.date()) or WD_SHORT[d.weekday()].lower()
    rows = await db.lessons(kind, eid, d.isoformat(), d.isoformat())
    return n, d, label, rows


async def widget_png(user: dict, size: str) -> bytes:
    n, d, label, rows = await pick_day(user)
    kind, eid = user["kind"], user["target_id"]
    name = await db.entity_name(kind, eid) or user.get("target_name") or "?"
    theme = theme_for(user, await db.owned_themes(user["user_id"]))
    return await asyncio.to_thread(render_widget, size, kind, name, d, rows, n, label, theme, bg_photo(user))


def _plain(title: str, text: str) -> dict:
    return {"l1": title, "l2": text, "l3": "", "inline": f"{title}: {text}", "circle_big": "⭐",
            "circle_small": "", "timer": None, "timer_prefix": ""}


async def widget_json(user: dict) -> dict:
    """Короткие строки для виджетов экрана блокировки (iOS рисует их одним цветом).
    timer — момент звонка; iPhone сам показывает живой обратный отсчёт до него."""
    n, d, label, rows = await pick_day(user)
    kind = user["kind"]
    items = _merge(rows)
    name = await db.entity_name(kind, user["target_id"]) or user.get("target_name") or "?"
    if not items:
        return _plain(name, "Пар нет 😌")
    state, cur, _ = _status(items, n, d == n.date())
    if cur is None:
        state, cur = "next", items[0]
    tt = _times(cur["time"])
    room = cur["rooms"] if cur["rooms"] and kind != "r" else ""
    if kind != "g":  # у препода/аудитории полезнее видеть группу
        room = room or ", ".join(sorted({g for g in cur["groups"] if g}))
    start = f"{tt[0]:%H:%M}" if tt else ""

    def at(t) -> str:
        return datetime.combine(d, t).replace(tzinfo=TZ).isoformat()

    if state == "now":
        l1 = " · ".join(x for x in (f"Сейчас {cur['pair']} пара", room) if x)
        timer, prefix = at(tt[1]), "до звонка "
        inline = " · ".join(x for x in (f"{cur['pair']} пара", cur["subject"], room) if x)
    elif d == n.date():
        l1 = " · ".join(x for x in (f"{cur['pair']} пара", start, room) if x)
        timer, prefix = (at(tt[0]), "через ") if tt else (None, "")
        inline = " · ".join(x for x in (start, cur["subject"], room) if x)
    else:
        l1 = " · ".join(x for x in (label.capitalize(), start, room) if x)
        timer, prefix = None, ""
        inline = " · ".join(x for x in (label.capitalize(), start, cur["subject"]) if x)
    return {"l1": l1, "l2": cur["subject"], "l3": "" if timer else pairs_word(len(items)),
            "inline": inline, "circle_big": str(cur["pair"]), "circle_small": start,
            "timer": timer, "timer_prefix": prefix}


async def handle_json(request: web.Request) -> web.Response:
    user = await db.user_by_home_token(request.match_info["token"])
    if not user:
        data = _plain("Расписание", "ссылка устарела")
    elif not is_premium(user):
        data = _plain("Расписание", "нужен Premium")
    elif not user.get("kind"):
        data = _plain("Расписание", "выбери группу")
    else:
        data = await widget_json(user)
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def handle_png(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    size = request.query.get("size", "m")
    size = size if size in SIZES else "m"
    user = await db.user_by_home_token(token)
    if not user:
        body = _message_png("Ссылка устарела", "Открой бота → ⚙️ Настройки →\n📲 Виджет на экран", size)
    elif not is_premium(user):
        body = _message_png("Виджет — в Premium", "Продли Premium в боте,\nи расписание вернётся", size)
    elif not user.get("kind"):
        body = _message_png("Выбери группу", "Открой бота и нажми /start", size)
    else:
        key = (token, size, int(time.time() // 60))  # не чаще раза в минуту на ссылку
        hit = _cache.get(key)
        if hit:
            body = hit[1]
        else:
            body = await widget_png(user, size)
            if len(_cache) > 500:
                _cache.clear()
            _cache[key] = (time.time(), body)
    return web.Response(body=body, content_type="image/png", headers={"Cache-Control": "no-store"})


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="schedule bot widget server: ok")


async def start_server() -> None:
    if not WEB_PORT:
        log.info("📲 Виджет на экран выключен: не задан WEB_PORT / SERVER_PORT")
        return
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/w/{token}.png", handle_png)
    app.router.add_get("/w/{token}.json", handle_json)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
        log.info("📲 Веб-сервер виджетов: порт %s, адрес %s", WEB_PORT, PUBLIC_URL or "(PUBLIC_URL не задан)")
    except OSError as e:
        log.warning("📲 Веб-сервер виджетов не запустился: %s", e)


# ======================= бот =======================
def _url(token: str, size: str = "m") -> str:
    return f"{PUBLIC_URL}/w/{token}.png?size={size}"


def scriptable_code(token: str, name: str) -> str:
    # метки __ИМЯ__ уникальны: в JS-коде есть ${BASE} и ${BOT}, их трогать нельзя
    return SCRIPT.replace("__NAME__", name).replace("__BASE__", f"{PUBLIC_URL}/w/{token}") \
        .replace("__BOT__", runtime["bot_username"] or "")


SCRIPT = r'''// 📅 Виджет расписания — __NAME__
// Работает и на экране «Домой», и на экране блокировки.
const BASE = "__BASE__";
const BOT = "__BOT__";
const family = config.widgetFamily || "medium";
const size = { small: "s", medium: "m", large: "l", extraLarge: "l" }[family] || "m";

async function get(kind) {
  const req = new Request(`${BASE}.${kind}?size=${size}&t=${Date.now()}`);
  req.allowInsecureRequest = true;
  req.timeoutInterval = 15;
  return kind === "png" ? await req.loadImage() : await req.loadJSON();
}

const w = new ListWidget();
w.url = `tg://resolve?domain=${BOT}`;
let refresh = Date.now() + 5 * 60 * 1000;

if (family.startsWith("accessory")) {
  // ---------- экран блокировки ----------
  let d;
  try { d = await get("json"); }
  catch (e) { d = { l1: "Расписание", l2: "нет связи", l3: "", inline: "Расписание: нет связи",
                    circle_big: "?", circle_small: "", timer: null, timer_prefix: "" }; }
  if (d.timer) refresh = Math.min(refresh, new Date(d.timer).getTime() + 5000);
  if (family === "accessoryInline") {
    w.addText(d.inline);
  } else if (family === "accessoryCircular") {
    w.addAccessoryWidgetBackground = true;
    const big = w.addText(d.circle_big);
    big.font = Font.boldRoundedSystemFont(22);
    big.centerAlignText();
    if (d.timer) {
      const t = w.addDate(new Date(d.timer));
      t.applyTimerStyle();
      t.font = Font.mediumRoundedSystemFont(10);
      t.centerAlignText();
    } else {
      const s = w.addText(d.circle_small);
      s.font = Font.mediumRoundedSystemFont(10);
      s.centerAlignText();
    }
  } else {
    const a = w.addText(d.l1);
    a.font = Font.semiboldSystemFont(12);
    a.textOpacity = 0.75;
    a.lineLimit = 1;
    const b = w.addText(d.l2);
    b.font = Font.boldSystemFont(15);
    b.lineLimit = 1;
    b.minimumScaleFactor = 0.7;
    if (d.timer) {
      const row = w.addStack();
      const p = row.addText(d.timer_prefix);
      p.font = Font.mediumSystemFont(13);
      const t = row.addDate(new Date(d.timer));
      t.applyTimerStyle();
      t.font = Font.mediumMonospacedSystemFont(13);
    } else if (d.l3) {
      const c = w.addText(d.l3);
      c.font = Font.mediumSystemFont(13);
      c.textOpacity = 0.75;
    }
  }
} else {
  // ---------- экран «Домой»: картинка ----------
  w.backgroundColor = new Color("#0f1116");
  try { w.backgroundImage = await get("png"); }
  catch (e) {
    const t = w.addText("Нет связи с ботом расписания");
    t.textColor = Color.white();
    t.font = Font.mediumSystemFont(13);
  }
}

w.refreshAfterDate = new Date(refresh);
if (config.runsInWidget) { Script.setWidget(w); } else { await w.presentMedium(); }
Script.complete();
'''


async def menu_view(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    token = await db.home_token(uid)
    text = (
        "📲 <b>Виджет на экран телефона</b>\n<blockquote>Расписание прямо на рабочем столе — без открытия "
        "Telegram. Текущая пара подсвечена, вечером показывает завтра. В твоей теме оформления.</blockquote>\n\n"
        "Твоя личная ссылка-картинка:\n"
        f"<code>{_url(token)}</code>\n"
        "<i>Размеры: в конце ссылки <code>size=s</code> — маленький, <code>m</code> — широкий, "
        "<code>l</code> — большой.</i>\n\n"
        "🔒 Ссылка личная — не публикуй её. Если засветил — нажми «Новая ссылка»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("📱 iPhone", "hw:ios"), btn("🤖 Android", "hw:android")],
        [btn("👀 Превью", "hw:pv"), btn("🔄 Новая ссылка", "hw:reset")],
        [btn("◀️ К настройкам", "st:home")],
    ])
    return text, kb


async def _gate(c_or_m, uid: int) -> bool:
    if not PUBLIC_URL or not WEB_PORT:
        text = "📲 Виджет на экран пока не настроен администратором бота."
    elif not is_premium(await db.get_user(uid)):
        text = None
    else:
        return True
    if isinstance(c_or_m, CallbackQuery):
        await show(c_or_m, text or paywall("Виджет на экран телефона"), None if text else PAYWALL_KB)
        await c_or_m.answer()
    else:
        await c_or_m.answer(text or paywall("Виджет на экран телефона"), reply_markup=None if text else PAYWALL_KB)
    return False


@router.message(Command("homewidget"))
async def cmd_home(m: Message):
    if await _gate(m, m.from_user.id):
        text, kb = await menu_view(m.from_user.id)
        await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "hw:menu")
async def cb_menu(c: CallbackQuery):
    if await _gate(c, c.from_user.id):
        text, kb = await menu_view(c.from_user.id)
        await show(c, text, kb)
        await c.answer()


@router.callback_query(F.data == "hw:reset")
async def cb_reset(c: CallbackQuery):
    if await _gate(c, c.from_user.id):
        await db.home_token(c.from_user.id, reset=True)
        text, kb = await menu_view(c.from_user.id)
        await show(c, text, kb)
        await c.answer("🔄 Старая ссылка больше не работает — обнови её в виджете", show_alert=True)


@router.callback_query(F.data == "hw:pv")
async def cb_preview(c: CallbackQuery):
    if not await _gate(c, c.from_user.id):
        return
    await c.answer("🎨 Рисую…")
    user = await db.get_user(c.from_user.id)
    if not user.get("kind"):
        await c.message.answer("Сначала выбери группу — /start")
        return
    for size, label in (("s", "маленький"), ("m", "широкий"), ("l", "большой")):
        png = await widget_png(user, size)
        await c.message.answer_photo(BufferedInputFile(png, f"widget_{size}.png"), caption=f"📲 {label}")


@router.callback_query(F.data == "hw:ios")
async def cb_ios(c: CallbackQuery):
    if not await _gate(c, c.from_user.id):
        return
    token = await db.home_token(c.from_user.id)
    user = await db.get_user(c.from_user.id)
    name = await db.entity_name(user["kind"], user["target_id"]) if user.get("kind") else "расписание"
    code = scriptable_code(token, name or "расписание")
    await c.message.answer(
        "📱 <b>Виджет на iPhone</b> — через бесплатное приложение <b>Scriptable</b>\n\n"
        "<b>1️⃣ Установи скрипт</b>\n<blockquote>"
        "• Скачай <b>Scriptable</b> из App Store и открой\n"
        "• Нажми <b>+</b> справа вверху → вставь код из сообщения ниже → нажми <b>Done</b>\n"
        "• Если скрипт уже был — открой его, удали старый код и вставь новый</blockquote>\n\n"
        "<b>2️⃣ На экран «Домой»</b>\n<blockquote>"
        "• Подержи палец на пустом месте экрана, пока иконки не начнут дрожать\n"
        "• Нажми <b>+</b> слева вверху (на iOS 18: «Изменить» → «Добавить виджет»)\n"
        "• Найди <b>Scriptable</b> → выбери размер → <b>Добавить виджет</b> → <b>Готово</b>\n"
        "• Подержи палец на новом виджете → <b>Изменить виджет</b> → <b>Script</b> → выбери скрипт</blockquote>\n\n"
        "<b>3️⃣ На экран блокировки</b> 🔒\n<blockquote>"
        "• Заблокируй телефон, включи экран и разблокируй Face ID, <b>не смахивая</b> вверх\n"
        "• Подержи палец на экране блокировки → <b>Настроить</b> → <b>Экран блокировки</b>\n"
        "• Нажми на поле <b>под часами</b> (или строку <b>над часами</b>) → найди <b>Scriptable</b> → "
        "выбери прямоугольный, круглый или строку\n"
        "• Нажми на добавленный виджет → <b>Script</b> → выбери скрипт → закрой → <b>Готово</b></blockquote>\n\n"
        "На экране блокировки таймер до звонка тикает вживую ⏱. Тап по виджету открывает бота.")
    await c.message.answer_document(BufferedInputFile(code.encode(), "Расписание.js"),
                                    caption="📄 Код для Scriptable")
    await c.message.answer(f"<pre><code class=\"language-javascript\">{escape(code)}</code></pre>")
    await c.answer()


@router.callback_query(F.data == "hw:android")
async def cb_android(c: CallbackQuery):
    if not await _gate(c, c.from_user.id):
        return
    token = await db.home_token(c.from_user.id)
    await c.message.answer(
        "🤖 <b>Виджет на Android</b>\n\n"
        "<b>Способ 1 — KWGT</b> (бесплатный, гибкий)\n<blockquote>"
        "1. Установи <b>KWGT Kustom Widget Maker</b> из Google Play\n"
        "2. На рабочем столе добавь виджет KWGT нужного размера → нажми на него\n"
        "3. В редакторе: <b>+</b> → <b>Изображение</b> → в поле «Растровое изображение / Bitmap» "
        "вставь ссылку ниже\n"
        "4. Растяни картинку на весь виджет, сохрани 💾</blockquote>\n\n"
        "<b>Способ 2 — любое приложение «виджет-картинка по ссылке»</b>\n<blockquote>"
        "Найди в Google Play по запросу <i>image widget url</i>, добавь виджет и вставь ссылку. "
        "Поставь обновление каждые 15–30 минут.</blockquote>\n\n"
        "Ссылки (выбери под размер виджета):\n"
        f"▫️ маленький: <code>{_url(token, 's')}</code>\n"
        f"▫️ широкий: <code>{_url(token, 'm')}</code>\n"
        f"▫️ большой: <code>{_url(token, 'l')}</code>")
    await c.answer()

