from __future__ import annotations

import io
from datetime import date, datetime

from PIL import ImageDraw

from utils.formatting import WD_SHORT, _merge, _times, fmt_minutes, minutes_between, pairs_word
from utils.image import F_BOLD, F_REG, F_SEMI, F_SUBJ, _background, _font
from utils.themes import Theme, build, mix

SIZES = {"s": (480, 480), "m": (1020, 480), "l": (1020, 1070)}
PAD = 38


def _fit(draw, text: str, font_fn, size: int, width: int, min_size: int = 18):
    f = font_fn(size)
    while draw.textlength(text, font=f) > width and size > min_size:
        size -= 2
        f = font_fn(size)
    if draw.textlength(text, font=f) > width:
        while text and draw.textlength(text + "…", font=f) > width:
            text = text[:-1]
        text += "…"
    return text, f


def _status(items: list[dict], now: datetime, is_today: bool) -> tuple[str, dict | None, str]:
    if not items:
        return "none", None, "Пар нет"
    if not is_today:
        r = items[0]
        tt = _times(r["time"])
        return "next", r, f"первая в {tt[0]:%H:%M}" if tt else "первая пара"
    t = now.time()
    for r in items:
        tt = _times(r["time"])
        if tt and tt[0] <= t <= tt[1]:
            return "now", r, f"ещё {fmt_minutes(minutes_between(t, tt[1]))}"
    for r in items:
        tt = _times(r["time"])
        if tt and t < tt[0]:
            return "next", r, f"через {fmt_minutes(minutes_between(t, tt[0]))}"
    return "done", None, "Пары закончились"


def render_widget(size: str, kind: str, name: str, d: date, rows: list[dict], now: datetime,
                  label: str, theme: Theme | None = None, photo: str | None = None) -> bytes:
    t = theme or build("classic")
    W, H = SIZES.get(size, SIZES["m"])
    items = _merge(rows)
    is_today = d == now.date()
    state, cur, caption = _status(items, now, is_today)

    bg = _background(t, H, photo)
    left = (bg.width - W) // 2
    img = bg.crop((left, 0, left + W, H))
    draw = ImageDraw.Draw(img)

    head = f"{WD_SHORT[d.weekday()]} {d:%d.%m} · {label}"
    draw.text((PAD, PAD - 4), head.upper(), font=F_SEMI(24 if size == "s" else 26), fill=t.accent)
    nm, nf = _fit(draw, name, lambda s: _font(t.title_font, s), 34 if size == "s" else 40, W - 2 * PAD)
    draw.text((PAD, PAD + 30), nm, font=nf, fill=t.text)
    y = PAD + 30 + nf.size + 22

    if size == "s":
        if cur:
            tag = {"now": "Сейчас", "next": "Далее"}.get(state, "")
            draw.text((PAD, y), f"{tag} · {cur['pair']} пара", font=F_SEMI(26), fill=t.muted)
            y += 40
            subj, sf = _fit(draw, cur["subject"], lambda s: F_SUBJ(t, s), 44, W - 2 * PAD, 26)
            draw.text((PAD, y), subj, font=sf, fill=t.text)
            y += sf.size + 18
            if cur["rooms"] and kind != "r":
                draw.text((PAD, y), f"ауд. {cur['rooms']}", font=F_BOLD(34), fill=t.accent)
                y += 50
        else:
            draw.text((PAD, y + 10), caption, font=F_BOLD(40), fill=t.text)
        bar_col = t.accent if state == "now" else t.line
        draw.rounded_rectangle((PAD, H - PAD - 44, W - PAD, H - PAD), radius=22, fill=bar_col)
        txt = caption if cur else (pairs_word(len(items)) if items else "отдыхаем")
        tf = F_SEMI(24)
        draw.text(((W - draw.textlength(txt, font=tf)) / 2, H - PAD - 37), txt, font=tf,
                  fill=(255, 255, 255) if state == "now" else t.text)
    else:
        if size == "m":
            st = caption
            sf = F_SEMI(26)
            tw = draw.textlength(st, font=sf)
            draw.rounded_rectangle((W - PAD - tw - 32, PAD - 6, W - PAD, PAD + 36), radius=21,
                                   fill=t.accent if state == "now" else t.line)
            draw.text((W - PAD - tw - 16, PAD + 1), st, font=sf,
                      fill=(255, 255, 255) if state == "now" else t.text)
        else:
            draw.text((PAD, y - 6), caption, font=F_SEMI(30), fill=t.accent if state == "now" else t.muted)
            y += 46
        if not items:
            draw.text((PAD, y + 10), "Можно отдыхать", font=F_BOLD(40), fill=t.text)
        row_h = 74 if size == "m" else 96
        max_rows = max(1, (H - y - PAD) // row_h)
        shown, start = items, 0
        if len(items) > max_rows:
            start = items.index(cur) if cur in items else (len(items) - max_rows if state == "done" else 0)
            start = min(start, len(items) - max_rows)
            shown = items[start:start + max_rows]
        t_now = now.time()
        for r in shown:
            tt = _times(r["time"])
            past = is_today and tt and t_now > tt[1]
            active = state == "now" and r is cur
            if active:
                draw.rounded_rectangle((PAD - 14, y - 8, W - PAD + 14, y + row_h - 14), radius=18,
                                       fill=t.card_now if t.card else mix(t.bg, t.accent, 0.25))
            col = t.muted if past else t.text
            draw.text((PAD, y), str(r["pair"]), font=F_BOLD(36), fill=t.accent if not past else t.muted)
            if tt:
                draw.text((PAD + 42, y + 6), f"{tt[0]:%H:%M}", font=F_SEMI(26), fill=t.muted)
            x = PAD + 140
            room = f"  ·  {r['rooms']}" if r["rooms"] and kind != "r" else ""
            room_w = draw.textlength(room, font=F_SEMI(28))
            subj, sf = _fit(draw, r["subject"], lambda s: F_SUBJ(t, s), 34, W - PAD - x - room_w - 10, 24)
            draw.text((x, y), subj, font=sf, fill=col)
            if room:
                draw.text((x + draw.textlength(subj, font=sf), y + 4), room, font=F_SEMI(28),
                          fill=t.muted if past else t.accent)
            if size == "l":
                meta = r["teachers"] if kind == "g" else ", ".join(sorted({g for g in r["groups"] if g}))
                if meta:
                    mt, mf = _fit(draw, meta, F_REG, 24, W - PAD - x, 18)
                    draw.text((x, y + 42), mt, font=mf, fill=t.muted)
            y += row_h
        after = len(items) - start - len(shown)
        note = "  ·  ".join(x for x in (f"прошло: {start}" if start else "",
                                        f"ещё {after} позже" if after else "") if x)
        if note:
            nf2 = F_SEMI(24)
            draw.text((W - PAD - draw.textlength(note, font=nf2), H - PAD - 28), note, font=nf2, fill=t.muted)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
