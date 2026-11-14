"""Парсер «Экспресс-расписания»: страницы собраны вручную по структуре сайта (без сети)."""
from bs4 import BeautifulSoup

from utils.site_parser import parse_group_page, parse_index, parse_updated

INDEX = """
<html><body>
  <a href="cg12.htm">К-11</a> <a href="cg13.htm">К-12</a>
  <a href="cp7.htm">Смирнова А. В.</a> <a href="other.html">Сайт</a> <a href="cg99.htm"> </a>
</body></html>
"""

GROUP = """
<html><body>
  <p>Обновлено: 16.11.2026 в 7:40</p>
  <a href="j1.htm">Предмет до первой даты — игнорируется</a>
  <table>
    <tr><td colspan="3">16.11.2026 Понедельник</td></tr>
    <tr><td>1 пара</td><td>8.30-9.50</td>
        <td><a href="j5.htm">Базы данных</a> <a href="ca64.htm">2-25</a> <a href="cp7.htm">Смирнова А. В.</a></td></tr>
    <tr><td>2</td><td>10:00–11:20</td>
        <td><a href="j9.htm">Веб-разработка</a> <a href="ca64.htm">2-25</a> <a href="ca71.htm">2-35</a>
            <a href="cp8.htm">Новиков И. А.</a></td></tr>
    <tr><td colspan="3">17.11.2026 Вторник</td></tr>
    <tr><td>4 пара: 12.50-14.10</td>
        <td><a href="j3.htm">Иностранный язык</a> <a href="cp9.htm">Орлова Е. П.</a></td></tr>
  </table>
</body></html>
"""


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_parse_index_by_kind():
    page = soup(INDEX)
    assert parse_index(page, "cg") == {12: "К-11", 13: "К-12"}
    assert parse_index(page, "cp") == {7: "Смирнова А. В."}


def test_parse_updated():
    assert parse_updated(soup(GROUP)) == "16.11.2026 в 7:40"
    assert parse_updated(soup(INDEX)) is None


def test_parse_group_page():
    teachers: dict[int, str] = {}
    rooms: dict[int, str] = {}
    lessons = parse_group_page(soup(GROUP), 12, teachers, rooms)

    assert [(x.date, x.pair, x.time, x.subject) for x in lessons] == [
        ("2026-11-16", 1, "8:30–9:50", "Базы данных"),
        ("2026-11-16", 2, "10:00–11:20", "Веб-разработка"),
        ("2026-11-17", 4, "12:50–14:10", "Иностранный язык"),
    ]
    web = lessons[1]
    assert (web.rooms, web.room_ids, web.teachers, web.teacher_ids) == ("2-25, 2-35", "64,71", "Новиков И. А.", "8")
    assert lessons[2].rooms == ""
    assert all(x.group_id == 12 for x in lessons)
    # Справочники преподавателей и аудиторий пополняются по ходу разбора
    assert teachers == {7: "Смирнова А. В.", 8: "Новиков И. А.", 9: "Орлова Е. П."}
    assert rooms == {64: "2-25", 71: "2-35"}
