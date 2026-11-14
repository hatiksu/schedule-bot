"""🖼 Картинка-расписание (PNG) — для беседы или сторис. Поддерживает темы (utils/themes.py).

День рисуется в формате сторис 1080×1920 (контент по центру, если пар мало),
неделя — длинной карточкой шириной 1080.
"""
from __future__ import annotations

import io
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.formatting import KIND_TITLE, MONTHS, WEEKDAYS, _merge, _times, pairs_word
from utils.themes import Theme, build, mix

FONTS = Path(__file__).resolve().parent.parent / "fonts"
W = 1080
PAD = 72


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for path in (FONTS / f"{name}.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                 Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def F_BOLD(s):
    return _font("Manrope-ExtraBold", s)


def F_SEMI(s):
    return _font("Manrope-SemiBold", s)


def F_REG(s):
    return _font("Manrope-Regular", s)


def F_SUBJ(t: Theme, s):
    return _font(t.subj_font, int(s * t.subj_scale))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if draw.textlength(cand, font=font) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=font) > width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


# ---------- фон и декор тем ----------
def _photo_background(t: Theme, H: int, path: str) -> Image.Image:
    """Своё фото на фоне: обрезаем по центру и затемняем/осветляем под тему, чтобы текст читался."""
    photo = Image.open(path).convert("RGB")
    k = max(W / photo.width, H / photo.height)
    photo = photo.resize((int(photo.width * k) + 1, int(photo.height * k) + 1), Image.LANCZOS)
    left, top = (photo.width - W) // 2, (photo.height - H) // 2
    photo = photo.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(2))
    veil = Image.new("RGB", (W, H), t.bg)
    return Image.blend(photo, veil, 0.55)


def _background(t: Theme, H: int, photo: str | None = None) -> Image.Image:
    if photo:
        try:
            return _photo_background(t, H, photo)
        except Exception:
            pass  # файл испорчен — рисуем обычный фон темы
    img = Image.new("RGB", (W, H), t.bg)
    d = ImageDraw.Draw(img)
    if t.bg2 != t.bg:
        for y in range(H):
            d.line([(0, y), (W, y)], fill=mix(t.bg, t.bg2, y / H))
    rnd = random.Random(42)  # декор одинаковый при каждой генерации
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    if t.deco in ("glow", "grid", "snow"):
        for i in range(520):
            k = (1 - i / 520) ** 2 * (0.30 if t.deco == "grid" else 0.20)
            ld.line([(0, i), (W, i)], fill=(*t.accent, int(255 * k)))
    if t.deco == "grid":  # synthwave-сетка снизу
        horizon = int(H * 0.72)
        for i in range(14):
            y = horizon + int((H - horizon) * (i / 13) ** 1.8)
            ld.line([(0, y), (W, y)], fill=(*t.accent2, 70), width=2)
        for i in range(-12, 13):
            ld.line([(W / 2 + i * 30, horizon), (W / 2 + i * 260, H)], fill=(*t.accent2, 60), width=2)
        ld.rectangle((0, horizon - 2, W, horizon + 2), fill=(*t.accent, 150))
    elif t.deco == "blobs":
        for (x, y, r, c) in ((-80, 120, 420, t.accent), (W + 60, 700, 460, t.accent2),
                             (180, H - 200, 380, (255, 214, 150))):
            ld.ellipse((x - r, y - r, x + r, y + r), fill=(*c, 95))
        layer = layer.filter(ImageFilter.GaussianBlur(110))
    elif t.deco == "sakura":
        for _ in range(46):
            x, y = rnd.randint(0, W), rnd.randint(0, H)
            w, h = rnd.randint(18, 34), rnd.randint(10, 18)
            petal = Image.new("RGBA", (w * 2, w * 2), (0, 0, 0, 0))
            ImageDraw.Draw(petal).ellipse((w // 2, w - h // 2, w // 2 + w, w + h // 2),
                                          fill=(*t.accent2, rnd.randint(90, 170)))
            petal = petal.rotate(rnd.randint(0, 180), resample=Image.BICUBIC)
            layer.alpha_composite(petal, (x, y))
    elif t.deco == "paper":
        for y in range(0, H, 44):
            ld.line([(0, y), (W, y)], fill=(*t.line, 255), width=2)
        for x in range(0, W, 44):
            ld.line([(x, 0), (x, H)], fill=(*t.line, 150), width=1)
        ld.line([(PAD - 30, 0), (PAD - 30, H)], fill=(*t.accent, 170), width=3)
    elif t.deco == "snow":
        for _ in range(170):
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((2, 2, 3, 3, 4, 6))
            ld.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rnd.randint(70, 200)))
    elif t.deco == "halloween":
        mx, my, mr = W - 190, 210, 120
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((mx - mr - 60, my - mr - 60, mx + mr + 60, my + mr + 60),
                                     fill=(*t.accent, 90))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(50)))
        ld = ImageDraw.Draw(layer)
        ld.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(255, 196, 90, 255))
        ld.ellipse((mx - mr + 40, my - mr - 10, mx + mr + 40, my + mr - 10), fill=(*t.bg, 255))
        for _ in range(90):
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((1, 2, 2, 3))
            ld.ellipse((x - r, y - r, x + r, y + r), fill=(255, 240, 220, rnd.randint(60, 180)))
    img = img.convert("RGBA")
    img.alpha_composite(layer)
    return img.convert("RGB")


def _gradient_bar(img: Image.Image, t: Theme, x: int, y: int, w: int, h: int) -> None:
    bar = Image.new("RGB", (w, h))
    px = bar.load()
    for i in range(w):
        col = mix(t.accent, t.accent2, i / max(w - 1, 1))
        for j in range(h):
            px[i, j] = col
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=255)
    img.paste(bar, (x, y), mask)


def _card(draw: ImageDraw.ImageDraw, t: Theme, box, now: bool = False, radius: int = 36) -> None:
    if t.card is None:  # «Тетрадка»: без карточек, текущая пара — маркером
        if now:
            draw.rounded_rectangle(box, radius=12, fill=t.card_now)
        return
    draw.rounded_rectangle(box, radius=radius, fill=t.card_now if now else t.card,
                           outline=(t.accent if now else t.line) if t.outline else None,
                           width=3 if t.outline else 0)


def _meta(r: dict, kind: str) -> str:
    bits = []
    if kind != "r" and r["rooms"]:
        bits.append(f"ауд. {r['rooms']}")
    groups = sorted({g for g in r["groups"] if g})
    if kind != "g" and groups:
        bits.append(", ".join(groups))
    if kind != "t" and r["teachers"]:
        bits.append(r["teachers"])
    return "  ·  ".join(bits)


def _header(draw, img, t: Theme, y: int, kind: str, name: str, subtitle: str, summary: str) -> int:
    _gradient_bar(img, t, PAD, y, 120, 12)
    y += 40
    draw.text((PAD, y), f"РАСПИСАНИЕ · {KIND_TITLE[kind].upper()}", font=F_SEMI(28), fill=t.muted)
    y += 52
    tf = _font(t.title_font, 86)
    while draw.textlength(name, font=tf) > W - 2 * PAD and tf.size > 40:
        tf = _font(t.title_font, tf.size - 4)
    draw.text((PAD, y), name, font=tf, fill=t.text)
    y += tf.size + 34
    draw.text((PAD, y), subtitle, font=F_BOLD(44), fill=t.text)
    y += 62
    if summary:
        draw.text((PAD, y), summary, font=F_REG(32), fill=t.muted)
        y += 48
    return y + 30


def _footer(draw, t: Theme, y: int, bot_username: str | None, updated: str | None) -> None:
    if bot_username:
        draw.text((PAD, y), f"@{bot_username}", font=F_SEMI(30), fill=t.accent)
    if updated:
        right = f"обновлено {updated}"
        fr = F_REG(26)
        draw.text((W - PAD - draw.textlength(right, font=fr), y + 3), right, font=fr, fill=t.muted)


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------- день ----------
def _day_blocks(draw, t: Theme, kind: str, items: list[dict], notes: dict[int, str]) -> list[tuple]:
    blocks, prev = [], None
    sf, mf, nf = F_SUBJ(t, 44), F_REG(30), F_SEMI(30)
    line_h = int(54 * t.subj_scale)
    text_w = W - 2 * PAD - 190
    for r in items:
        if prev is not None and r["pair"] - prev > 1:
            blocks.append(("gap", r["pair"] - prev - 1, 64))
        prev = r["pair"]
        subj = _wrap(draw, r["subject"], sf, text_w, 3)
        meta = _wrap(draw, _meta(r, kind), mf, text_w, 2)
        note = _wrap(draw, "Заметка: " + notes[r["pair"]], nf, text_w, 2) if r["pair"] in notes else []
        h = 44 + len(subj) * line_h + len(meta) * 40 + len(note) * 40 + (10 if note else 0) + 36
        blocks.append(("lesson", (r, subj, meta, note), max(h, 214)))
    return blocks


def render_day(kind: str, name: str, d: date, rows: list[dict], notes: dict[int, str] | None = None,
               bot_username: str | None = None, updated: str | None = None,
               now_pair: int | None = None, theme: Theme | None = None, photo: str | None = None) -> bytes:
    t = theme or build("classic")
    notes = notes or {}
    items = _merge(rows)
    probe = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    blocks = _day_blocks(probe, t, kind, items, notes)
    header_h = 420
    content_h = sum(b[2] + 22 for b in blocks) if blocks else 260
    H = max(1920, header_h + content_h + 220)

    img = _background(t, H, photo)
    draw = ImageDraw.Draw(img)
    summary = ""
    if items:
        a, b = _times(items[0]["time"]), _times(items[-1]["time"])
        summary = pairs_word(len(items)) + (f"  ·  {a[0]:%H:%M} – {b[1]:%H:%M}" if a and b else "")
    total = header_h + content_h
    y = max(PAD + 40, (H - 160 - total) // 2) if H == 1920 else PAD + 40
    y = _header(draw, img, t, y, kind, name, f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}", summary)

    if not items:
        _card(draw, t, (PAD, y, W - PAD, y + 220))
        msg = "Выходной" if d.weekday() == 6 else "Пар нет"
        f = F_BOLD(56)
        draw.text(((W - draw.textlength(msg, font=f)) / 2, y + 78), msg, font=f, fill=t.text)
    line_h = int(54 * t.subj_scale)
    for kind_, payload, h in blocks:
        if kind_ == "gap":
            label = f"окно — {pairs_word(payload)}"
            f = F_SEMI(30)
            draw.text(((W - draw.textlength(label, font=f)) / 2, y + 12), label, font=f, fill=t.muted)
            y += h + 22
            continue
        r, subj, meta, note = payload
        is_now = r["pair"] == now_pair
        _card(draw, t, (PAD, y, W - PAD, y + h), now=is_now)
        cx, cy = PAD + 70, y + 74
        draw.ellipse((cx - 42, cy - 42, cx + 42, cy + 42), fill=t.accent if is_now else t.line)
        num = str(r["pair"])
        nf = F_BOLD(44)
        num_col = (255, 255, 255) if is_now or t.card is not None and sum(t.line) < 300 else t.text
        draw.text((cx - draw.textlength(num, font=nf) / 2, cy - 30), num, font=nf, fill=num_col)
        tt = _times(r["time"])
        if tt:
            tf = F_SEMI(26)
            for k, s in enumerate((f"{tt[0]:%H:%M}", f"{tt[1]:%H:%M}")):
                draw.text((cx - draw.textlength(s, font=tf) / 2, cy + 56 + k * 32), s, font=tf,
                          fill=t.text if k == 0 else t.muted)
        x, ty = PAD + 170, y + 34
        for line in subj:
            draw.text((x, ty), line, font=F_SUBJ(t, 44), fill=t.text)
            ty += line_h
        ty += 4
        for line in meta:
            draw.text((x, ty), line, font=F_REG(30), fill=t.muted)
            ty += 40
        if note:
            ty += 10
            for line in note:
                draw.text((x, ty), line, font=F_SEMI(30), fill=t.note)
                ty += 40
        y += h + 22

    _footer(draw, t, H - PAD - 30, bot_username, updated)
    return _to_png(img)


# ---------- неделя ----------
def render_week(kind: str, name: str, monday: date, rows: list[dict],
                notes: dict[tuple[str, int], str] | None = None,
                bot_username: str | None = None, updated: str | None = None,
                theme: Theme | None = None, photo: str | None = None) -> bytes:
    t = theme or build("classic")
    notes = notes or {}
    items = _merge(rows)
    by_day: dict[str, list[dict]] = {}
    for r in items:
        by_day.setdefault(r["date"], []).append(r)
    probe = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    sf, mf = F_SUBJ(t, 36), F_REG(27)
    line_h = int(46 * t.subj_scale)
    text_w = W - 2 * PAD - 230

    days = []
    for i in range(6):
        d = monday + timedelta(days=i)
        lessons = []
        for r in by_day.get(d.isoformat(), []):
            subj = _wrap(probe, r["subject"], sf, text_w, 2)
            meta = _wrap(probe, _meta(r, kind), mf, text_w, 1)
            note = _wrap(probe, "Заметка: " + notes[(r["date"], r["pair"])], mf, text_w, 1) \
                if (r["date"], r["pair"]) in notes else []
            lessons.append((r, subj, meta, note, 24 + len(subj) * line_h + (len(meta) + len(note)) * 36 + 22))
        days.append((d, lessons))
    H = 420 + sum(80 + (sum(l[4] for l in ls) + 30 if ls else 70) for _, ls in days) + 160

    img = _background(t, H, photo)
    draw = ImageDraw.Draw(img)
    sunday = monday + timedelta(days=6)
    y = _header(draw, img, t, PAD + 20, kind, name,
                f"Неделя {monday.day} {MONTHS[monday.month - 1][:3]} – {sunday.day} {MONTHS[sunday.month - 1][:3]}",
                pairs_word(len(items)) + " за неделю" if items else "")
    for d, lessons in days:
        draw.text((PAD, y), f"{WEEKDAYS[d.weekday()]}", font=F_BOLD(40), fill=t.text)
        dl = f"{d:%d.%m}"
        draw.text((W - PAD - draw.textlength(dl, font=F_SEMI(32)), y + 6), dl, font=F_SEMI(32), fill=t.muted)
        y += 70
        if not lessons:
            draw.text((PAD, y), "пар нет", font=F_REG(30), fill=t.muted)
            y += 80
            continue
        card_h = sum(l[4] for l in lessons) + 10
        _card(draw, t, (PAD - 20, y - 10, W - PAD + 20, y + card_h), radius=30)
        for n, (r, subj, meta, note, h) in enumerate(lessons):
            ty = y + 14
            draw.text((PAD + 10, ty + 2), str(r["pair"]), font=F_BOLD(40), fill=t.accent)
            tt = _times(r["time"])
            if tt:
                draw.text((PAD + 60, ty + 10), f"{tt[0]:%H:%M}", font=F_SEMI(28), fill=t.muted)
            x = PAD + 200
            for line in subj:
                draw.text((x, ty), line, font=sf, fill=t.text)
                ty += line_h
            for line in meta:
                draw.text((x, ty), line, font=mf, fill=t.muted)
                ty += 36
            for line in note:
                draw.text((x, ty), line, font=mf, fill=t.note)
                ty += 36
            y += h
            if n < len(lessons) - 1:
                draw.line((PAD + 10, y - 4, W - PAD - 10, y - 4), fill=t.line, width=2)
        y += 40
    _footer(draw, t, H - PAD - 30, bot_username, updated)
    return _to_png(img)
