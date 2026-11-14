from datetime import date, datetime
from io import BytesIO

import pytest
from PIL import Image

from utils.image import render_day, render_week
from utils.themes import THEMES, build, hex2rgb, luminance
from utils.widget_image import render_widget

DAY = date(2026, 11, 16)
ROWS = [
    {"date": "2026-11-16", "pair": 1, "time": "8:30–9:50", "subject": "Базы данных", "rooms": "2-25",
     "teachers": "Смирнова А. В.", "group_name": "К-11"},
    {"date": "2026-11-16", "pair": 2, "time": "10:00–11:20", "subject": "Веб-разработка", "rooms": "3-14",
     "teachers": "Новиков И. А.", "group_name": "К-11"},
]


def png(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    assert img.format == "PNG"
    return img


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_render_day_every_theme(theme):
    img = png(render_day("g", "К-11", DAY, ROWS, notes={2: "Сдать лабу"}, now_pair=1, theme=build(theme)))
    assert img.size == (1080, 1920)


def test_render_empty_day_and_week():
    assert png(render_day("g", "К-11", DAY, [])).size[0] == 1080
    week = png(render_week("g", "К-11", DAY, ROWS))
    assert week.size[0] == 1080


@pytest.mark.parametrize(("size", "expected"), [("s", (480, 480)), ("m", (1020, 480))])
def test_render_widget(size, expected):
    img = png(render_widget(size, "g", "К-11", DAY, ROWS, datetime(2026, 11, 16, 10, 30), label="Сегодня"))
    assert img.size == expected


def test_custom_colors():
    t = build("classic", accent_hex="#ff3366", bg_hex="#ffffff")
    assert t.accent == hex2rgb("#ff3366")
    assert luminance(t.bg) > 0.9 and luminance(t.text) < 0.2
    assert build("нет-такой").id == "classic"
