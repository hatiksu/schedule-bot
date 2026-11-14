"""Оформление сообщений: цитаты (<blockquote>), даты по-русски, «идёт сейчас», окна."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from html import escape

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WD_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
KIND_ICON = {"g": "👥", "t": "👤", "r": "🚪"}
KIND_TITLE = {"g": "Группа", "t": "Преподаватель", "r": "Аудитория"}


# ---------- даты и слова ----------
def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def pairs_word(n: int) -> str:
    return plural(n, "пара", "пары", "пар")


def human_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def short_date(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{WD_SHORT[d.weekday()]} {d:%d.%m}"


def relative(d: date, today: date) -> str:
    return {0: "сегодня", 1: "завтра", -1: "вчера"}.get((d - today).days, "")


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def study_day(d: date, step: int = 1) -> date:
    """Сдвиг на день с пропуском воскресенья."""
    d += timedelta(days=step)
    if d.weekday() == 6:
        d += timedelta(days=step)
    return d


def _times(s: str) -> tuple[time, time] | None:
    try:
        a, b = s.replace("-", "–").split("–")
        h1, m1 = map(int, a.split(":"))
        h2, m2 = map(int, b.split(":"))
        return time(h1, m1), time(h2, m2)
    except (ValueError, AttributeError):
        return None


def minutes_between(a: time, b: time) -> int:
    return (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)


def fmt_minutes(m: int) -> str:
    m = max(m, 0)
    if m < 60:
        return f"{m} мин"
    h, mm = divmod(m, 60)
    return f"{h} ч {mm} мин" if mm else f"{h} ч"


# ---------- подготовка данных ----------
def _merge(rows: list[dict]) -> list[dict]:
    """У препода одна пара может идти сразу у нескольких групп — склеиваем."""
    merged: dict[tuple, dict] = {}
    for r in rows:
        key = (r["date"], r["pair"], r["subject"], r["rooms"], r["teachers"])
        if key in merged:
            merged[key]["groups"].append(r["group_name"])
        else:
            merged[key] = {**r, "groups": [r["group_name"]]}
    return sorted(merged.values(), key=lambda r: (r["date"], r["pair"]))


ICONS = {"subj": "📖", "room": "🚪", "teacher": "👤", "group": "👥", "date": "📅",
         "now": "🟢", "next": "⏳", "gap": "☕", "note": "📝"}


def _ic(icons: dict | None, key: str) -> str:
    """Иконка с пробелом после неё (или пусто, если в наборе её нет)."""
    v = (icons or ICONS).get(key, "")
    return f"{v} " if v else ""


def _meta(r: dict, kind: str, icons: dict | None = None) -> list[str]:
    parts = []
    if kind != "r" and r["rooms"]:
        parts.append(f"{_ic(icons, 'room')}{escape(r['rooms'])}")
    groups = sorted({g for g in r["groups"] if g})
    if kind != "g" and groups:
        parts.append(_ic(icons, "group") + escape(", ".join(groups)))
    if kind != "t" and r["teachers"]:
        parts.append(f"{_ic(icons, 'teacher')}{escape(r['teachers'])}")
    return parts


def _title(kind: str, name: str) -> str:
    return f"{KIND_ICON[kind]} <b>{escape(name)}</b>  <i>· {KIND_TITLE[kind].lower()}</i>"


def _footer(updated: str | None) -> str:
    return f"<i>🕓 Обновлено на сайте: {escape(updated)}</i>" if updated else ""


# ---------- день ----------
def format_day(kind: str, name: str, d: date, rows: list[dict], now: datetime,
               updated: str | None, max_date: str | None,
               notes: dict[int, str] | None = None, extras: list[str] | None = None,
               style: str = "normal", icons: dict | None = None) -> str:
    """notes — заметки {пара: текст}, extras — строки внизу (отсчёты),
    style — normal | compact | detailed, icons — набор эмодзи (Premium)."""
    notes = notes or {}
    ic = lambda k: _ic(icons, k)  # noqa: E731
    extra = ["", *extras] if extras else []
    today = now.date()
    items = _merge(rows)
    rel = relative(d, today)
    head = [_title(kind, name), "", f"{ic('date')}<b>{human_date(d)}</b>" + (f" · {rel}" if rel else "")]

    if not items:
        if max_date is None or d.isoformat() > max_date:
            body = "<blockquote>🕸 Расписание на этот день ещё не выложили</blockquote>"
        elif d.weekday() == 6:
            body = "<blockquote>🌤 Воскресенье — выходной</blockquote>"
        else:
            body = "<blockquote>😌 Пар нет — можно отдыхать</blockquote>"
        return "\n".join(head + [body] + extra + ["", _footer(updated)]).strip()

    first, last = _times(items[0]["time"]), _times(items[-1]["time"])
    summary = pairs_word(len(items))
    if first and last:
        summary += f" · {first[0]:%H:%M} – {last[1]:%H:%M}"
    head.append(f"<i>{summary}</i>")
    head.append("")

    # что идёт сейчас / что следующее (только для сегодняшнего дня)
    status: dict[int, str] = {}
    all_done = False
    if d == today:
        t = now.time()
        nxt_found = False
        for i, r in enumerate(items):
            tt = _times(r["time"])
            if not tt:
                continue
            if tt[0] <= t <= tt[1]:
                status[i] = f"  {ic('now')}<b>идёт · ещё {fmt_minutes(minutes_between(t, tt[1]))}</b>"
            elif t < tt[0] and not nxt_found:
                status[i] = f"  {ic('next')}<i>через {fmt_minutes(minutes_between(t, tt[0]))}</i>"
                nxt_found = True
        last_t = _times(items[-1]["time"])
        all_done = bool(last_t and t > last_t[1])

    body = []
    if style == "compact":  # все пары одной цитатой, по строке на пару
        lines = []
        for i, r in enumerate(items):
            tt = _times(r["time"])
            start = f"{tt[0]:%H:%M}" if tt else ""
            meta = _meta(r, kind, icons)
            line = f"<b>{r['pair']}</b>  {start}  <b>{escape(r['subject'])}</b>" + (
                f"  ·  {meta[0]}" if meta else "") + status.get(i, "")
            lines.append(line)
            if r["pair"] in notes:
                lines.append(f"      {ic('note')}<i>{escape(notes[r['pair']])}</i>")
        body.append("<blockquote>" + "\n".join(lines) + "</blockquote>")
    else:
        prev_pair = None
        for i, r in enumerate(items):
            if prev_pair is not None and r["pair"] - prev_pair > 1:
                gap = r["pair"] - prev_pair - 1
                body.append(f"{ic('gap')}<i>окно — {pairs_word(gap)}</i>")
            prev_pair = r["pair"]
            lines = [f"<b>{r['pair']} пара</b>" + (f"  ·  {r['time']}" if r["time"] else "") + status.get(i, ""),
                     f"{ic('subj')}<b>{escape(r['subject'])}</b>"]
            meta = _meta(r, kind, icons)
            if meta:
                lines.append("  ·  ".join(meta) if style != "detailed" else "\n".join(meta))
            if style == "detailed":
                tt = _times(r["time"])
                nxt = items[i + 1] if i + 1 < len(items) else None
                ntt = _times(nxt["time"]) if nxt else None
                extra_bits = []
                if tt:
                    extra_bits.append(f"⏱ {fmt_minutes(minutes_between(*tt))}")
                if tt and ntt and nxt["pair"] == r["pair"] + 1:
                    extra_bits.append(f"перемена {fmt_minutes(minutes_between(tt[1], ntt[0]))}")
                if extra_bits:
                    lines.append(f"<i>{' · '.join(extra_bits)}</i>")
            if r["pair"] in notes:
                lines.append(f"{ic('note')}<i>{escape(notes[r['pair']])}</i>")
            body.append("<blockquote>" + "\n".join(lines) + "</blockquote>")

    tail = ["", "🎉 <i>На сегодня пары закончились</i>"] if all_done else []
    return "\n".join(head + body + tail + extra + ["", _footer(updated)]).strip()


# ---------- неделя ----------
def format_week(kind: str, name: str, monday: date, rows: list[dict], now: datetime,
                updated: str | None, max_date: str | None,
                notes: dict[tuple[str, int], str] | None = None, icons: dict | None = None) -> str:
    notes = notes or {}
    today = now.date()
    sunday = monday + timedelta(days=6)
    items = _merge(rows)
    label = {0: " · текущая", 7: " · следующая", -7: " · прошлая"}.get((monday - week_start(today)).days, "")
    blocks = [
        f"{_title(kind, name)}\n\n🗓 <b>Неделя {monday.day} {MONTHS[monday.month - 1][:3]}"
        f" – {sunday.day} {MONTHS[sunday.month - 1][:3]}</b>{label}"
        + (f"\n<i>{pairs_word(len(items))} за неделю</i>" if items else "")
    ]

    if not items and (max_date is None or monday.isoformat() > max_date):
        blocks.append("<blockquote>🕸 Расписание на эту неделю ещё не выложили</blockquote>")
        blocks.append(_footer(updated))
        return "\n\n".join(b for b in blocks if b)

    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in items:
        by_day[r["date"]].append(r)

    for i in range(7):
        d = monday + timedelta(days=i)
        day_items = by_day.get(d.isoformat(), [])
        rel = relative(d, today)
        header = f"<b>{WEEKDAYS[d.weekday()]}, {d:%d.%m}</b>" + (f" · {rel}" if rel else "")
        if not day_items:
            if d.weekday() == 6:
                continue
            if max_date and d.isoformat() > max_date:
                blocks.append(f"{header}\n<i>ещё не выложили</i>")
            else:
                blocks.append(f"{header} — <i>пар нет</i>")
            continue
        lines = []
        for r in day_items:
            start = _times(r["time"])
            t = f"{start[0]:%H:%M}" if start else ""
            lines.append(f"{r['pair']}  {t}  <b>{escape(r['subject'])}</b>")
            meta = _meta(r, kind, icons)
            if meta:
                lines.append(f"      <i>{'  ·  '.join(meta)}</i>")
            if (r["date"], r["pair"]) in notes:
                lines.append(f"      {_ic(icons, 'note')}<i>{escape(notes[(r['date'], r['pair'])])}</i>")
        blocks.append(f"{header}\n<blockquote>" + "\n".join(lines) + "</blockquote>")

    blocks.append(_footer(updated))
    return "\n\n".join(b for b in blocks if b)


# ---------- короткое описание дня (для inline-режима) ----------
def day_summary(rows: list[dict]) -> str:
    items = _merge(rows)
    if not items:
        return "пар нет"
    first, last = _times(items[0]["time"]), _times(items[-1]["time"])
    s = pairs_word(len(items))
    if first and last:
        s += f" · {first[0]:%H:%M}–{last[1]:%H:%M}"
    return s


# ---------- звонки ----------
def format_bells(bells: dict[int, str], d: date, now: datetime,
                 my_rows: list[dict] | None = None, kind: str | None = None) -> str:
    lines = [f"⏰ <b>Звонки</b> · {human_date(d)}", ""]
    parsed = {p: tt for p, s in bells.items() if (tt := _times(s))}
    if not parsed:
        return "\n".join(lines + ["<blockquote>Пока нет данных о звонках</blockquote>"])

    t = now.time()
    pairs = sorted(parsed)
    current = next((p for p in pairs if parsed[p][0] <= t <= parsed[p][1]), None)
    upcoming = next((p for p in pairs if t < parsed[p][0]), None)

    # статус + таймер
    if d.weekday() == 6:
        lines.append("🌤 Сегодня воскресенье — пар нет")
    elif current is not None:
        left = minutes_between(t, parsed[current][1])
        lines.append(f"🟢 Идёт <b>{current} пара</b> — до звонка <b>{fmt_minutes(left)}</b>")
    elif upcoming is not None and upcoming == pairs[0]:
        lines.append(f"☀️ Пары ещё не начались — <b>{upcoming} пара</b> через "
                     f"<b>{fmt_minutes(minutes_between(t, parsed[upcoming][0]))}</b>")
    elif upcoming is not None:
        lines.append(f"☕ Перемена — <b>{upcoming} пара</b> через "
                     f"<b>{fmt_minutes(minutes_between(t, parsed[upcoming][0]))}</b>")
    else:
        lines.append("🌙 Пары на сегодня закончились")

    # что сейчас / дальше у самого пользователя
    if my_rows and d.weekday() != 6:
        mine = {r["pair"]: r for r in _merge(my_rows)}
        target = current if current in mine else None
        nxt = next((p for p in sorted(mine) if (tt := _times(mine[p]["time"])) and t < tt[0]), None)
        if target is not None:
            r = mine[target]
            lines.append(f"📖 У тебя сейчас: <b>{escape(r['subject'])}</b>"
                         + (f", {escape(r['rooms'])}" if r["rooms"] and kind != "r" else ""))
        if nxt is not None:
            r = mine[nxt]
            lines.append(f"⏭ Дальше у тебя: {nxt} пара — <b>{escape(r['subject'])}</b>"
                         + (f", {escape(r['rooms'])}" if r["rooms"] and kind != "r" else ""))
    lines.append("")

    rows = []
    for i, p in enumerate(pairs):
        a, b = parsed[p]
        mark = ""
        if d.weekday() != 6:
            if p == current:
                mark = "  ◀️ <b>сейчас</b>"
            elif b < t:
                mark = "  ✔️"
        rows.append(f"<b>{p} пара</b>   {a:%H:%M} – {b:%H:%M}{mark}")
        if i + 1 < len(pairs):
            brk = minutes_between(b, parsed[pairs[i + 1]][0])
            if brk >= 20:
                rows.append(f"      🍽 <i>большая перемена · {brk} мин</i>")
    lines.append("<blockquote>" + "\n".join(rows) + "</blockquote>")
    return "\n".join(lines)


# ---------- подробные изменения ----------
def _describe(lessons: list, kind: str, group_names: dict[int, str]) -> dict[int, tuple[str, str]]:
    """{пара: (описание, время)} — «Математика, 2-25» (у препода ещё и группы)."""
    by_pair: dict[int, dict[tuple, set]] = defaultdict(lambda: defaultdict(set))
    times: dict[int, str] = {}
    for l in lessons:
        by_pair[l.pair][(l.subject, l.rooms)].add(group_names.get(l.group_id, ""))
        times.setdefault(l.pair, l.time)
    result = {}
    for p, variants in by_pair.items():
        parts = []
        for (subject, rooms), groups in sorted(variants.items()):
            bits = [f"<b>{escape(subject)}</b>"]
            if rooms:
                bits.append(escape(rooms))
            if kind == "t":
                bits.append(escape(", ".join(sorted(g for g in groups if g))))
            parts.append(", ".join(b for b in bits if b))
        result[p] = (" / ".join(parts), times.get(p, ""))
    return result


def format_changes(kind: str, name: str, changes: dict[str, tuple[list, list]],
                   old_max: str | None, group_names: dict[int, str]) -> tuple[str, str] | None:
    """changes = {дата: (старые, новые)}. Возвращает (текст, первая_дата) или None."""
    blocks, new_days, shown = [], [], []
    for day in sorted(changes):
        old, new = changes[day]
        if not old and (old_max is None or day > old_max):
            new_days.append(day)
            shown.append(day)
            continue
        o, n = _describe(old, kind, group_names), _describe(new, kind, group_names)
        lines = []
        for p in sorted(o.keys() | n.keys()):
            od, nd = o.get(p), n.get(p)
            if od and nd:
                if od[0] != nd[0]:
                    lines.append(f"<b>{p} пара:</b> <s>{od[0]}</s> → {nd[0]}")
                elif od[1] != nd[1]:
                    lines.append(f"<b>{p} пара:</b> время <s>{od[1]}</s> → {nd[1]}")
            elif nd:
                lines.append(f"<b>{p} пара:</b> ➕ {nd[0]}")
            elif od:
                lines.append(f"<b>{p} пара:</b> ❌ <s>{od[0]}</s> — отменена")
        if lines:
            blocks.append(f"📅 <b>{short_date(day)}</b>\n<blockquote>" + "\n".join(lines) + "</blockquote>")
            shown.append(day)
    if not blocks and not new_days:
        return None
    head = f"🔔 <b>Изменения в расписании</b>\n{KIND_ICON[kind]} {escape(name)}"
    if not blocks:
        head = f"🆕 <b>Выложено новое расписание</b>\n{KIND_ICON[kind]} {escape(name)}"
    parts = [head] + blocks
    if new_days:
        parts.append("🆕 Выложено расписание: " + ", ".join(short_date(d) for d in new_days))
    return "\n\n".join(parts), min(shown)


# ---------- отсчёты ----------
def days_word(n: int) -> str:
    return plural(n, "день", "дня", "дней")


# ---------- свободные аудитории ----------
def _room_sort_key(name: str):
    parts = name.replace("–", "-").split("-", 1)
    num = "".join(ch for ch in parts[-1] if ch.isdigit())
    return (parts[0] if len(parts) == 2 else "~", int(num) if num else 0, name)


def format_free_rooms(d: date, pair: int, time_: str | None, free: list[str], total: int,
                      now: datetime) -> str:
    rel = relative(d, now.date())
    head = (f"🏫 <b>Свободные аудитории</b>\n📅 {human_date(d)}" + (f" · {rel}" if rel else "")
            + f"\n🕐 <b>{pair} пара</b>" + (f" · {time_}" if time_ else ""))
    if not free:
        return head + "\n\n<blockquote>😬 Свободных аудиторий нет</blockquote>"
    # группируем по корпусу/этажу — по тому, что до дефиса («2-25» → корпус 2)
    groups: dict[str, list[str]] = defaultdict(list)
    for name in sorted(free, key=_room_sort_key):
        prefix = name.replace("–", "-").split("-", 1)[0] if "-" in name else "Другие"
        groups[prefix].append(name)
    blocks = []
    for prefix, names in groups.items():
        title = f"Корпус {prefix}" if prefix != "Другие" and prefix.isdigit() else prefix
        blocks.append(f"<b>{escape(title)}</b>\n" + "  ".join(f"<code>{escape(n)}</code>" for n in names))
    return (head + f"\n<i>свободно {len(free)} из {total}</i>\n\n<blockquote>"
            + "\n\n".join(blocks) + "</blockquote>\n\n"
            "<i>Учитываются аудитории, которые встречаются в расписании.</i>")


# ---------- где сейчас преподаватель ----------
def format_where(name: str, now: datetime, today_rows: list[dict],
                 next_day: date | None, next_rows: list[dict]) -> str:
    t = now.time()
    lines = [f"📍 <b>{escape(name)}</b>", ""]
    items = _merge(today_rows) if now.weekday() != 6 else []
    current = nxt = None
    for r in items:
        tt = _times(r["time"])
        if not tt:
            continue
        if tt[0] <= t <= tt[1]:
            current = (r, tt)
        elif t < tt[0] and nxt is None:
            nxt = (r, tt)

    def place(r: dict) -> str:
        bits = [f"<b>{escape(r['subject'])}</b>"]
        if r["rooms"]:
            bits.append(f"🚪 <b>{escape(r['rooms'])}</b>")
        groups = sorted({g for g in r["groups"] if g})
        if groups:
            bits.append("👥 " + escape(", ".join(groups)))
        return "  ·  ".join(bits)

    if current:
        r, tt = current
        lines.append(f"🟢 <b>Сейчас на паре</b> · ещё {fmt_minutes(minutes_between(t, tt[1]))}\n"
                     f"<blockquote>{r['pair']} пара · {r['time']}\n{place(r)}</blockquote>")
    elif items and nxt:
        lines.append("☕ Сейчас без пары")
    if nxt:
        r, tt = nxt
        lines.append(f"⏭ <b>Следующая</b> — через {fmt_minutes(minutes_between(t, tt[0]))}\n"
                     f"<blockquote>{r['pair']} пара · {r['time']}\n{place(r)}</blockquote>")
    if not current and not nxt:
        lines.append("🌙 Сегодня пар больше нет" if items else "😌 Сегодня пар нет")
        nitems = _merge(next_rows)
        if next_day and nitems:
            r = nitems[0]
            lines.append(f"\n📅 <b>{human_date(next_day)}</b> — первая пара\n"
                         f"<blockquote>{r['pair']} пара · {r['time']}\n{place(r)}</blockquote>")
    elif items:
        last = items[-1]
        lt = _times(last["time"])
        if lt:
            lines.append(f"\n🏁 Сегодня до {lt[1]:%H:%M} · всего {pairs_word(len(items))}")
    return "\n".join(lines)


# ---------- нагрузка ----------
def format_workload(kind: str, name: str, label: str, d1: date, d2: date, rows: list[dict],
                    max_date: str | None) -> str:
    items = _merge(rows)
    minutes = 0
    for r in items:
        tt = _times(r["time"])
        minutes += minutes_between(*tt) if tt else 80
    n = len(items)
    head = (f"📊 <b>Нагрузка</b> · {KIND_ICON[kind]} {escape(name)}\n"
            f"🗓 {label}: {d1:%d.%m} – {d2:%d.%m}")
    if not items:
        return head + "\n\n<blockquote>Пар нет</blockquote>"
    days = len({r["date"] for r in items})
    total = (f"<blockquote>📚 <b>{pairs_word(n)}</b> за {days_word(days)}\n"
             f"🎓 <b>{n * 2}</b> академ. часов\n"
             f"⏱ <b>{fmt_minutes(minutes)}</b> чистого времени\n"
             f"📈 в среднем {n / days:.1f} пары в день</blockquote>")

    by_subject: dict[str, int] = defaultdict(int)
    for r in items:
        by_subject[r["subject"]] += 1
    subj = "\n".join(f"{c} × <b>{escape(s)}</b>" for s, c in
                     sorted(by_subject.items(), key=lambda x: -x[1])[:10])
    parts = [head, "", total, "", f"<b>По предметам</b>\n<blockquote>{subj}</blockquote>"]

    if kind == "t":
        by_group: dict[str, int] = defaultdict(int)
        for r in items:
            for g in {g for g in r["groups"] if g}:
                by_group[g] += 1
        grp = "\n".join(f"{c} × {escape(g)}" for g, c in sorted(by_group.items(), key=lambda x: -x[1])[:10])
        parts += ["", f"<b>По группам</b>\n<blockquote>{grp}</blockquote>"]
    if max_date and d2.isoformat() > max_date:
        parts += ["", f"<i>⚠️ На сайте расписание выложено только до {date.fromisoformat(max_date):%d.%m}"
                      " — дальше пока не учтено.</i>"]
    return "\n".join(parts)


# ---------- служебное ----------
def split_text(text: str, limit: int = 4000) -> list[str]:
    """Telegram режет сообщения длиннее 4096 — делим по пустым строкам
    (цитаты внутри не содержат пустых строк, так что теги не разрываются)."""
    parts, cur = [], ""
    for block in text.split("\n\n"):
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) > limit and cur:
            parts.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts
