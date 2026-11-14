from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from config import BASE_URL

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–]\s*(\d{1,2})[.:](\d{2})")
PAIR_RE = re.compile(r"(\d{1,2})\s*пара", re.I)
BARE_PAIR_RE = re.compile(r"^([1-9])\s*:?$")
UPDATED_RE = re.compile(r"Обновлено:\s*(\d{2}\.\d{2}\.\d{4}\s*в\s*\d{1,2}:\d{2})")
HREF_RE = re.compile(r"(cg|cp|ca|j)(\d+)\.htm$")
SKIP_PARENTS = {"script", "style", "title", "a"}


@dataclass(frozen=True)
class Lesson:
    group_id: int
    date: str
    pair: int
    time: str
    subject: str
    room_ids: str
    rooms: str
    teacher_ids: str
    teachers: str


@dataclass
class Snapshot:
    updated: str | None
    groups: dict[int, str]
    teachers: dict[int, str] = field(default_factory=dict)
    rooms: dict[int, str] = field(default_factory=dict)
    lessons: list[Lesson] = field(default_factory=list)


def _link(a: Tag) -> tuple[str | None, int | None]:
    m = HREF_RE.search(a.get("href", ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


async def _get(client: httpx.AsyncClient, path: str) -> BeautifulSoup:
    r = await client.get(BASE_URL + path)
    r.raise_for_status()
    return BeautifulSoup(r.content.decode("cp1251", errors="replace"), "html.parser")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (schedule-bot)"},
    )


def parse_index(soup: BeautifulSoup, kind: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        k, sid = _link(a)
        name = a.get_text(" ", strip=True)
        if k == kind and name:
            result[sid] = name
    return result


def parse_updated(soup: BeautifulSoup) -> str | None:
    m = UPDATED_RE.search(soup.get_text(" ", strip=True))
    return m.group(1) if m else None


def parse_group_page(
    soup: BeautifulSoup, group_id: int, teachers: dict[int, str], rooms: dict[int, str]
) -> list[Lesson]:
    raw: list[dict] = []
    date_: str | None = None
    pair: int | None = None
    time_ = ""
    cur: dict | None = None

    root = soup.body or soup
    for node in root.descendants:
        if isinstance(node, Tag):
            if node.name != "a":
                continue
            kind, sid = _link(node)
            name = node.get_text(" ", strip=True)
            if kind == "j":
                cur = None
                if date_ and pair:
                    cur = {"date": date_, "pair": pair, "time": time_, "subject": name,
                           "rooms": [], "teachers": []}
                    raw.append(cur)
            elif kind == "ca" and cur is not None:
                cur["rooms"].append((sid, name))
                rooms.setdefault(sid, name)
            elif kind == "cp" and cur is not None:
                cur["teachers"].append((sid, name))
                teachers.setdefault(sid, name)
            continue

        if not isinstance(node, NavigableString) or node.parent.name in SKIP_PARENTS:
            continue
        if node.find_parent("a"):
            continue
        s = str(node).strip()
        if not s:
            continue

        if len(s) <= 25 and (m := DATE_RE.search(s)):
            d, mo, y = m.groups()
            date_, pair, time_, cur = f"{y}-{mo}-{d}", None, "", None
        elif (m := BARE_PAIR_RE.match(s)) or (m := PAIR_RE.search(s)):
            pair, time_, cur = int(m.group(1)), "", None
            if (t := TIME_RE.search(s)):
                time_ = f"{t.group(1)}:{t.group(2)}–{t.group(3)}:{t.group(4)}"
        elif (t := TIME_RE.search(s)):
            time_ = f"{t.group(1)}:{t.group(2)}–{t.group(3)}:{t.group(4)}"
            if cur is not None and not cur["time"]:
                cur["time"] = time_

    return [
        Lesson(
            group_id=group_id,
            date=r["date"],
            pair=r["pair"],
            time=r["time"],
            subject=r["subject"],
            room_ids=",".join(str(i) for i, _ in r["rooms"]),
            rooms=", ".join(n for _, n in r["rooms"]),
            teacher_ids=",".join(str(i) for i, _ in r["teachers"]),
            teachers=", ".join(n for _, n in r["teachers"]),
        )
        for r in raw
    ]


async def fetch_updated() -> str | None:
    async with _client() as client:
        return parse_updated(await _get(client, "cg.htm"))


async def fetch_all(concurrency: int = 5) -> Snapshot:
    async with _client() as client:
        index = await _get(client, "cg.htm")
        snap = Snapshot(updated=parse_updated(index), groups=parse_index(index, "cg"))
        if not snap.groups:
            raise RuntimeError("На cg.htm не найдено ни одной группы — изменилась вёрстка?")
        try:
            snap.teachers.update(parse_index(await _get(client, "cp.htm"), "cp"))
        except httpx.HTTPError:
            pass

        sem = asyncio.Semaphore(concurrency)

        async def one(gid: int) -> list[Lesson]:
            async with sem:
                soup = await _get(client, f"cg{gid}.htm")
            return parse_group_page(soup, gid, snap.teachers, snap.rooms)

        results = await asyncio.gather(*(one(g) for g in snap.groups))

    snap.lessons = sorted(
        {l for part in results for l in part},
        key=lambda l: (l.group_id, l.date, l.pair, l.subject),
    )
    return snap


if __name__ == "__main__":
    async def _test():
        snap = await fetch_all()
        print(f"Обновлено на сайте: {snap.updated}")
        print(f"Групп: {len(snap.groups)}, преподавателей: {len(snap.teachers)}, "
              f"аудиторий: {len(snap.rooms)}, пар: {len(snap.lessons)}")
        gid = next(iter(snap.groups))
        print(f"\nПример — {snap.groups[gid]}:")
        for l in [l for l in snap.lessons if l.group_id == gid][:10]:
            print(f"  {l.date} | {l.pair} пара {l.time} | {l.subject} | {l.rooms} | {l.teachers}")

    asyncio.run(_test())
