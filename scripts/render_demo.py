"""Демо-картинки для README и сайта-портфолио: расписание, неделя и виджеты на выдуманных данных.

Запуск из папки проекта:  python -m scripts.render_demo
Картинки сохраняются в docs/screenshots/.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from utils.image import render_day, render_week
from utils.themes import build
from utils.widget_image import render_widget

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
GROUP = "К-11"
# Выдуманные пары — реальные данные пользователей и колледжа в демо не попадают
LESSONS = [
    (1, "8:30–9:50", "Основы алгоритмизации и программирования", "2-25", "Смирнова А. В."),
    (2, "10:00–11:20", "Базы данных", "3-14", "Кузнецов Д. С."),
    (3, "11:50–13:10", "Иностранный язык", "1-08", "Орлова Е. П."),
    (4, "13:20–14:40", "Веб-разработка", "2-31", "Новиков И. А."),
]


def rows_for(d: date, take: int = 4, shift: int = 0) -> list[dict]:
    picked = LESSONS[shift:] + LESSONS[:shift]
    return [
        {"date": d.isoformat(), "pair": p, "time": t, "subject": s, "rooms": r, "teachers": tch,
         "group_name": GROUP}
        for (p, t, _, _, _), (_, _, s, r, tch) in zip(LESSONS[:take], picked[:take], strict=True)
    ]


def showcase(files: dict[str, bytes]) -> bytes:
    """Витрина 1440×900 для сайта: три темы дня и виджет на градиентном фоне."""
    W, H = 1440, 900
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):  # мягкий фиолетово-синий градиент
        k = y / H
        draw.line([(0, y), (W, y)], fill=(int(24 + 10 * k), int(18 + 14 * k), int(48 + 30 * k)))
    phones = ["day-classic.png", "day-neon.png", "day-pastel.png"]
    ph_h = 700
    ph_w = int(ph_h * 1080 / 1920)
    x0 = (W - 3 * ph_w - 2 * 40) // 2
    for i, name in enumerate(phones):
        shot = Image.open(BytesIO(files[name])).convert("RGB").resize((ph_w, ph_h), Image.LANCZOS)
        mask = Image.new("L", shot.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, ph_w - 1, ph_h - 1], radius=36, fill=255)
        img.paste(shot, (x0 + i * (ph_w + 40), (H - ph_h) // 2 + (30 if i == 1 else 0) - 40), mask)
    widget = Image.open(BytesIO(files["widget-m.png"])).convert("RGB")
    ww = 520
    widget = widget.resize((ww, int(widget.height * ww / widget.width)), Image.LANCZOS)
    mask = Image.new("L", widget.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, widget.width - 1, widget.height - 1], radius=28, fill=255)
    img.paste(widget, (W - ww - 60, H - widget.height - 40), mask)
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    today = date(2026, 11, 16)  # понедельник
    monday = today - timedelta(days=today.weekday())
    now = datetime(2026, 11, 16, 10, 30)
    day = rows_for(today)
    week = [r for i in range(6) for r in rows_for(monday + timedelta(days=i), take=3 + i % 2, shift=i % 4)]

    files = {
        "day-classic.png": render_day("g", GROUP, today, day, notes={2: "Сдать лабораторную №5"}, now_pair=2,
                                      updated="16.11.2026 в 7:40", theme=build("classic")),
        "day-neon.png": render_day("g", GROUP, today, day, now_pair=2, theme=build("neon")),
        "day-pastel.png": render_day("g", GROUP, today, day, theme=build("pastel")),
        "week.png": render_week("g", GROUP, monday, week, updated="16.11.2026 в 7:40", theme=build("classic")),
        "widget-m.png": render_widget("m", "g", GROUP, today, day, now, label="Сегодня", theme=build("classic")),
        "widget-s.png": render_widget("s", "g", GROUP, today, day, now, label="Сегодня", theme=build("neon")),
    }
    files["showcase.png"] = showcase(files)
    for name, png in files.items():
        (OUT / name).write_bytes(png)
        print(f"  🖼  docs/screenshots/{name}")


if __name__ == "__main__":
    main()
