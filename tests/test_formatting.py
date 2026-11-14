from datetime import date, time

from utils.formatting import (fmt_minutes, human_date, minutes_between, pairs_word, plural, relative, short_date,
                              split_text, study_day, week_start)


def test_plural_and_pairs():
    assert [pairs_word(n) for n in (1, 2, 5, 11, 21, 22, 112)] == [
        "1 пара", "2 пары", "5 пар", "11 пар", "21 пара", "22 пары", "112 пар"]
    assert plural(3, "день", "дня", "дней") == "3 дня"


def test_dates():
    monday = date(2026, 11, 16)
    assert human_date(monday) == "Понедельник, 16 ноября"
    assert short_date("2026-11-21") == "Сб 21.11"
    assert week_start(date(2026, 11, 21)) == monday
    assert relative(date(2026, 11, 17), monday) == "завтра"
    assert relative(date(2026, 11, 20), monday) == ""


def test_study_day_skips_sunday():
    saturday = date(2026, 11, 21)
    assert study_day(saturday) == date(2026, 11, 23)
    assert study_day(date(2026, 11, 23), -1) == saturday


def test_minutes():
    assert minutes_between(time(8, 30), time(9, 50)) == 80
    assert [fmt_minutes(m) for m in (-5, 45, 60, 95)] == ["0 мин", "45 мин", "1 ч", "1 ч 35 мин"]


def test_split_text_keeps_blocks_whole():
    blocks = [f"<blockquote>{'x' * 900}</blockquote>" for _ in range(6)]
    parts = split_text("\n\n".join(blocks), limit=2000)
    assert len(parts) == 3
    assert all(len(p) <= 2000 for p in parts)
    assert "\n\n".join(parts) == "\n\n".join(blocks)
    assert split_text("коротко") == ["коротко"]
