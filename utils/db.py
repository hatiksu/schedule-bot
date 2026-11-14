from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import astuple
from datetime import datetime, timedelta

import aiosqlite

from utils.site_parser import Lesson, Snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,   -- Telegram ID
    username      TEXT,                  -- @username (может не быть)
    full_name     TEXT,                  -- имя в Telegram
    kind          TEXT,                  -- выбор: 'g' группа | 't' преподаватель (NULL — ещё не выбрал)
    target_id     INTEGER,               -- ID группы/препода с сайта
    target_name   TEXT,                  -- название группы/ФИО препода (для удобного просмотра БД)
    notify        INTEGER NOT NULL DEFAULT 1,
    registered_at TEXT,                  -- дата регистрации (первый контакт с ботом)
    last_seen     TEXT,                  -- когда последний раз пользовался ботом
    banned        INTEGER NOT NULL DEFAULT 0,
    digest_mode   TEXT,                  -- авторассылка: 'evening' (на завтра) | 'morning' (на сегодня)
    digest_time   TEXT,                  -- «20:00»
    last_digest   TEXT                   -- дата последней авторассылки (чтобы не слать дважды)
);
CREATE TABLE IF NOT EXISTS notes (
    user_id INTEGER, kind TEXT, target_id INTEGER, date TEXT, pair INTEGER, text TEXT,
    PRIMARY KEY (user_id, kind, target_id, date, pair)
);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    text       TEXT,
    created_at TEXT,
    answered   INTEGER NOT NULL DEFAULT 0,
    answer     TEXT
);
CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    product    TEXT,                 -- plan:month | theme:neon | donate:50 | grant:30 (выдал админ)
    stars      INTEGER,
    charge_id  TEXT,                 -- telegram_payment_charge_id (нужен для возврата)
    created_at TEXT,
    refunded   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS owned_themes (user_id INTEGER, theme TEXT, PRIMARY KEY (user_id, theme));
CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER, kind TEXT, target_id INTEGER, added_at TEXT,
    PRIMARY KEY (user_id, kind, target_id)
);
CREATE TABLE IF NOT EXISTS promos (
    code TEXT PRIMARY KEY, days INTEGER, uses_left INTEGER, created_at TEXT  -- days 0 = навсегда, uses -1 = безлимит
);
CREATE TABLE IF NOT EXISTS promo_uses (user_id INTEGER, code TEXT, used_at TEXT, PRIMARY KEY (user_id, code));
CREATE TABLE IF NOT EXISTS gifts (
    code TEXT PRIMARY KEY, plan TEXT, buyer_id INTEGER, created_at TEXT,
    redeemed_by INTEGER, redeemed_at TEXT
);
CREATE TABLE IF NOT EXISTS achievements (user_id INTEGER, code TEXT, at TEXT, PRIMARY KEY (user_id, code));
CREATE TABLE IF NOT EXISTS events (day TEXT, user_id INTEGER, name TEXT);
CREATE INDEX IF NOT EXISTS ix_events_day ON events(day, name);
CREATE INDEX IF NOT EXISTS ix_events_user ON events(user_id, day);
CREATE TABLE IF NOT EXISTS update_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT,
    ok          INTEGER,
    forced      INTEGER,
    lessons     INTEGER,             -- NULL — сайт не менялся, выгрузку не качали
    changes     INTEGER,
    duration_ms INTEGER,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    kind TEXT NOT NULL,               -- 'g' | 't' | 'r' (аудитория)
    id   INTEGER NOT NULL,            -- ID с сайта (cg87 -> 87)
    name TEXT NOT NULL,
    norm TEXT NOT NULL,               -- для поиска: «ИС-21» -> «ис21»
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS lessons (
    group_id INTEGER, date TEXT, pair INTEGER, time TEXT, subject TEXT,
    room_ids TEXT, rooms TEXT, teacher_ids TEXT, teachers TEXT
);
CREATE INDEX IF NOT EXISTS ix_lessons_group ON lessons(group_id, date);
CREATE INDEX IF NOT EXISTS ix_lessons_date  ON lessons(date);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def norm(s: str) -> str:
    return re.sub(r"[\s\-.]", "", s.lower().replace("ё", "е"))


def _ids(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x]


def _sig(l: Lesson) -> tuple:
    return (l.pair, l.time, l.subject, l.rooms, l.teachers, l.group_id)


def _by_target(lessons: list[Lesson]) -> dict[tuple, list[Lesson]]:
    """(вид, id, дата) -> пары этого дня. Нужно, чтобы понять, у кого что поменялось."""
    idx: dict[tuple, list[Lesson]] = defaultdict(list)
    for l in lessons:
        idx[("g", l.group_id, l.date)].append(l)
        for t in _ids(l.teacher_ids):
            idx[("t", t, l.date)].append(l)
    return idx


class DB:
    def __init__(self, path: str, tz=None):
        self.path = path
        self.tz = tz
        self.conn: aiosqlite.Connection | None = None

    def _now(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d %H:%M:%S")

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._migrate_users()
        async with self.conn.execute("PRAGMA table_info(users)") as cur:
            cols = {r["name"] for r in await cur.fetchall()}
        for col, ddl in (("banned", "INTEGER NOT NULL DEFAULT 0"), ("digest_mode", "TEXT"),
                         ("digest_time", "TEXT"), ("last_digest", "TEXT"),
                         # ⭐ Premium
                         ("premium_until", "TEXT"), ("trial_used", "INTEGER NOT NULL DEFAULT 0"),
                         ("premium_warned", "TEXT"),
                         # 🎨 оформление
                         ("theme", "TEXT"), ("accent", "TEXT"), ("bg", "TEXT"),
                         ("no_watermark", "INTEGER NOT NULL DEFAULT 0"), ("msg_style", "TEXT"),
                         ("emoji_set", "TEXT"),
                         # ⏳ напоминания
                         ("remind_before", "INTEGER"), ("remind_first_only", "INTEGER NOT NULL DEFAULT 0"),
                         ("note_remind", "INTEGER NOT NULL DEFAULT 1"),
                         # ⏰ рассылки: вечер / утро / неделя (время «20:00» или NULL)
                         ("digest_evening", "TEXT"), ("digest_morning", "TEXT"), ("digest_week", "TEXT"),
                         ("last_digest_e", "TEXT"), ("last_digest_m", "TEXT"), ("last_digest_w", "TEXT"),
                         # 🤝 рефералка, 📱 виджет, 🖼 фото на фоне, 🏆 счётчики
                         ("referred_by", "INTEGER"), ("ref_rewarded", "INTEGER NOT NULL DEFAULT 0"),
                         ("widget_msg_id", "INTEGER"), ("widget_hash", "TEXT"),
                         ("bg_photo", "INTEGER NOT NULL DEFAULT 0"),
                         ("digests_sent", "INTEGER NOT NULL DEFAULT 0"),
                         ("home_token", "TEXT")):  # 📲 секрет ссылки на виджет рабочего стола
            if col not in cols:
                await self.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        # старая одиночная рассылка → новые слоты
        await self.conn.execute(
            "UPDATE users SET digest_evening = digest_time, last_digest_e = last_digest, digest_mode = NULL "
            "WHERE digest_mode = 'evening'")
        await self.conn.execute(
            "UPDATE users SET digest_morning = digest_time, last_digest_m = last_digest, digest_mode = NULL "
            "WHERE digest_mode = 'morning'")
        async with self.conn.execute("PRAGMA table_info(notes)") as cur:
            ncols = {r["name"] for r in await cur.fetchall()}
        if "reminded" not in ncols:
            await self.conn.execute("ALTER TABLE notes ADD COLUMN reminded INTEGER NOT NULL DEFAULT 0")
        await self.conn.commit()

    async def _migrate_users(self) -> None:
        """Переносит пользователей из старой таблицы (без имени/даты регистрации) в новую."""
        async with self.conn.execute("PRAGMA table_info(users)") as cur:
            cols = {r["name"] for r in await cur.fetchall()}
        if "registered_at" in cols:
            return
        now = self._now()
        await self.conn.executescript("ALTER TABLE users RENAME TO users_old;")
        await self.conn.executescript(SCHEMA)
        await self.conn.execute(
            "INSERT INTO users(user_id, kind, target_id, notify, registered_at, last_seen) "
            "SELECT user_id, kind, target_id, notify, ?, ? FROM users_old",
            (now, now),
        )
        await self.conn.execute(
            "UPDATE users SET target_name = (SELECT name FROM entities e "
            "WHERE e.kind = users.kind AND e.id = users.target_id)"
        )
        await self.conn.execute("DROP TABLE users_old")

    # ---------- meta ----------
    async def get_meta(self, key: str) -> str | None:
        async with self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_meta(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    # ---------- расписание ----------
    async def replace_snapshot(self, snap: Snapshot, today_iso: str):
        """Обновляет расписание. Возвращает (changes, old_max_date), где
        changes = {(вид, id, дата): (старые_пары, новые_пары)} — только сегодня и дальше."""
        async with self.conn.execute(
            "SELECT group_id, date, pair, time, subject, room_ids, rooms, teacher_ids, teachers "
            "FROM lessons WHERE date >= ?",
            (today_iso,),
        ) as cur:
            old = [Lesson(*row) for row in await cur.fetchall()]
        old_max = await self.max_date()
        new = [l for l in snap.lessons if l.date >= today_iso]
        a, b = _by_target(old), _by_target(new)
        changes = {}
        for k in a.keys() | b.keys():
            o, n = a.get(k, []), b.get(k, [])
            if {_sig(x) for x in o} != {_sig(x) for x in n}:
                changes[k] = (o, n)

        entities = (
            [("g", i, n, norm(n)) for i, n in snap.groups.items()]
            + [("t", i, n, norm(n)) for i, n in snap.teachers.items()]
            + [("r", i, n, norm(n)) for i, n in snap.rooms.items()]
        )
        # прошлые дни, которых уже нет на сайте, оставляем (для истории и звонков),
        # всё, что покрывает новая выгрузка, — перезаписываем
        min_new = min((l.date for l in snap.lessons), default=today_iso)
        await self.conn.execute("DELETE FROM lessons WHERE date >= ?", (min_new,))
        await self.conn.execute("DELETE FROM lessons WHERE date < date(?, '-120 days')", (today_iso,))
        await self.conn.execute("DELETE FROM entities")
        await self.conn.executemany(
            "INSERT OR REPLACE INTO entities(kind, id, name, norm) VALUES (?, ?, ?, ?)", entities
        )
        await self.conn.executemany(
            "INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [astuple(l) for l in snap.lessons],
        )
        # подтягиваем актуальные названия групп / ФИО преподов в таблицу пользователей
        await self.conn.execute(
            "UPDATE users SET target_name = (SELECT name FROM entities e "
            "WHERE e.kind = users.kind AND e.id = users.target_id) "
            "WHERE kind IS NOT NULL AND EXISTS (SELECT 1 FROM entities e "
            "WHERE e.kind = users.kind AND e.id = users.target_id)"
        )
        await self.conn.commit()
        return changes, old_max

    async def bells(self, day_iso: str | None = None) -> dict[int, str]:
        """Расписание звонков {номер пары: "8:00–9:20"} — самое частое время для каждой пары.
        Если указан день, время этого дня важнее (например, сокращённая суббота)."""
        async def collect(where: str, params: tuple) -> dict[int, str]:
            async with self.conn.execute(
                "SELECT pair, time, COUNT(*) AS c FROM lessons "
                f"WHERE time != '' {where} GROUP BY pair, time ORDER BY pair, c DESC",
                params,
            ) as cur:
                res: dict[int, str] = {}
                for r in await cur.fetchall():
                    res.setdefault(r["pair"], r["time"])
                return res

        result = await collect("", ())
        if day_iso:
            result.update(await collect("AND date = ?", (day_iso,)))
        return dict(sorted(result.items()))

    async def lessons(self, kind: str, eid: int, date_from: str, date_to: str) -> list[dict]:
        where = {
            "g": "l.group_id = ?",
            "t": "(',' || l.teacher_ids || ',') LIKE ?",
            "r": "(',' || l.room_ids || ',') LIKE ?",
        }[kind]
        param = eid if kind == "g" else f"%,{eid},%"
        sql = (
            "SELECT l.*, e.name AS group_name FROM lessons l "
            "LEFT JOIN entities e ON e.kind = 'g' AND e.id = l.group_id "
            f"WHERE {where} AND l.date BETWEEN ? AND ? ORDER BY l.date, l.pair"
        )
        async with self.conn.execute(sql, (param, date_from, date_to)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def max_date(self) -> str | None:
        """До какого дня на сайте выложено расписание."""
        async with self.conn.execute("SELECT MAX(date) AS d FROM lessons") as cur:
            row = await cur.fetchone()
        return row["d"] if row else None

    async def entity_name(self, kind: str, eid: int) -> str | None:
        async with self.conn.execute(
            "SELECT name FROM entities WHERE kind = ? AND id = ?", (kind, eid)
        ) as cur:
            row = await cur.fetchone()
        return row["name"] if row else None

    async def search(self, query: str, kinds=("g", "t", "r"), limit: int = 24) -> list[tuple]:
        """[(kind, id, name)] — сначала точные совпадения, потом начало, потом вхождение."""
        q = norm(query)
        if not q:
            return []
        ph = ",".join("?" * len(kinds))
        async with self.conn.execute(
            f"SELECT kind, id, name, norm FROM entities WHERE kind IN ({ph})", tuple(kinds)
        ) as cur:
            rows = await cur.fetchall()
        order = {"g": 0, "t": 1, "r": 2}
        found = []
        for r in rows:
            n = r["norm"]
            if q not in n:
                continue
            rank = 0 if n == q else 1 if n.startswith(q) else 2
            found.append((rank, order[r["kind"]], r["name"], r["kind"], r["id"]))
        found.sort()
        return [(k, i, name) for _, _, name, k, i in found[:limit]]

    # ---------- пользователи ----------
    async def get_user(self, uid: int) -> dict | None:
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def touch_user(self, uid: int, username: str | None, full_name: str | None) -> bool:
        """Вызывается на каждое сообщение/нажатие: создаёт пользователя при первом контакте
        (дата регистрации) и обновляет имя, юзернейм и время последнего визита."""
        now = self._now()
        await self.conn.execute(
            "INSERT INTO users(user_id, username, full_name, registered_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, "
            "full_name = excluded.full_name, last_seen = excluded.last_seen",
            (uid, username, full_name, now, now),
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT banned FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        return bool(row and row["banned"])

    async def set_user(self, uid: int, kind: str, eid: int) -> None:
        name = await self.entity_name(kind, eid)
        now = self._now()
        await self.conn.execute(
            "INSERT INTO users(user_id, kind, target_id, target_name, registered_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET kind = excluded.kind, "
            "target_id = excluded.target_id, target_name = excluded.target_name",
            (uid, kind, eid, name, now, now),
        )
        await self.conn.commit()

    # ---------- админка ----------
    async def stats(self) -> dict:
        today = self._now()[:10]
        async with self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(kind = 'g') AS students, SUM(kind = 't') AS teachers, "
            "SUM(kind IS NULL) AS no_choice, SUM(banned = 1) AS banned, "
            "SUM(notify = 0 AND kind IS NOT NULL) AS notify_off, "
            "SUM(substr(registered_at, 1, 10) = ?) AS new_today, "
            "SUM(registered_at >= date(?, '-6 days')) AS new_week, "
            "SUM(substr(last_seen, 1, 10) = ?) AS active_today, "
            "SUM(last_seen >= date(?, '-6 days')) AS active_week "
            "FROM users",
            (today, today, today, today),
        ) as cur:
            row = await cur.fetchone()
        return {k: row[k] or 0 for k in row.keys()}

    async def top_targets(self, kind: str, limit: int = 5) -> list[tuple[str, int]]:
        async with self.conn.execute(
            "SELECT COALESCE(target_name, target_id) AS name, COUNT(*) AS c FROM users "
            "WHERE kind = ? AND banned = 0 GROUP BY target_id ORDER BY c DESC LIMIT ?",
            (kind, limit),
        ) as cur:
            return [(str(r["name"]), r["c"]) for r in await cur.fetchall()]

    async def audience(self, kind: str | None = None, target_id: int | None = None) -> list[int]:
        """ID получателей рассылки: всем / студентам / преподам / конкретной группе или преподу."""
        sql, params = "SELECT user_id FROM users WHERE banned = 0", []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if target_id is not None:
            sql += " AND target_id = ?"
            params.append(target_id)
        async with self.conn.execute(sql, params) as cur:
            return [r["user_id"] for r in await cur.fetchall()]

    async def find_users(self, query: str, limit: int = 10) -> list[dict]:
        """Поиск по ID, @юзернейму, имени или группе/преподу."""
        q = query.strip().lstrip("@").lower()
        if q.isdigit():
            async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (int(q),)) as cur:
                return [dict(r) for r in await cur.fetchall()]
        # фильтруем в Python: SQLite lower() не понимает кириллицу
        async with self.conn.execute("SELECT * FROM users ORDER BY last_seen DESC") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return [r for r in rows
                if any(q in (r[f] or "").lower() for f in ("username", "full_name", "target_name"))][:limit]

    async def set_banned(self, uid: int, banned: bool) -> None:
        await self.conn.execute("UPDATE users SET banned = ? WHERE user_id = ?", (int(banned), uid))
        await self.conn.commit()

    async def all_users(self) -> list[dict]:
        async with self.conn.execute("SELECT * FROM users ORDER BY registered_at") as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def toggle_notify(self, uid: int) -> bool:
        await self.conn.execute("UPDATE users SET notify = 1 - notify WHERE user_id = ?", (uid,))
        await self.conn.commit()
        user = await self.get_user(uid)
        return bool(user and user["notify"])

    async def users_for(self, kind: str, eid: int) -> list[int]:
        async with self.conn.execute(
            "SELECT user_id FROM users WHERE kind = ? AND target_id = ? AND notify = 1 AND banned = 0",
            (kind, eid),
        ) as cur:
            return [r["user_id"] for r in await cur.fetchall()]

    # ---------- авторассылка ----------
    async def set_digest(self, uid: int, mode: str | None, time_: str | None) -> None:
        await self.conn.execute(
            "UPDATE users SET digest_mode = ?, digest_time = ? WHERE user_id = ?", (mode, time_, uid))
        await self.conn.commit()

    async def digest_users(self, today_iso: str) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE digest_mode IS NOT NULL AND kind IS NOT NULL AND banned = 0 "
            "AND (last_digest IS NULL OR last_digest != ?)", (today_iso,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_digest(self, uid: int, today_iso: str) -> None:
        await self.conn.execute("UPDATE users SET last_digest = ? WHERE user_id = ?", (today_iso, uid))
        await self.conn.commit()

    # ---------- заметки ----------
    async def notes(self, uid: int, kind: str, eid: int, date_from: str, date_to: str) -> dict:
        """{(дата, пара): текст}"""
        async with self.conn.execute(
            "SELECT date, pair, text FROM notes WHERE user_id = ? AND kind = ? AND target_id = ? "
            "AND date BETWEEN ? AND ?", (uid, kind, eid, date_from, date_to)
        ) as cur:
            return {(r["date"], r["pair"]): r["text"] for r in await cur.fetchall()}

    async def set_note(self, uid: int, kind: str, eid: int, date_iso: str, pair: int, text: str) -> None:
        await self.conn.execute(
            "INSERT INTO notes(user_id, kind, target_id, date, pair, text) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, kind, target_id, date, pair) DO UPDATE SET text = excluded.text, reminded = 0",
            (uid, kind, eid, date_iso, pair, text))
        await self.conn.commit()

    async def delete_note(self, uid: int, kind: str, eid: int, date_iso: str, pair: int) -> None:
        await self.conn.execute(
            "DELETE FROM notes WHERE user_id = ? AND kind = ? AND target_id = ? AND date = ? AND pair = ?",
            (uid, kind, eid, date_iso, pair))
        await self.conn.commit()

    # ---------- аудитории ----------
    async def rooms(self) -> list[tuple[int, str]]:
        async with self.conn.execute("SELECT id, name FROM entities WHERE kind = 'r'") as cur:
            return [(r["id"], r["name"]) for r in await cur.fetchall()]

    async def busy_rooms(self, date_iso: str, pair: int) -> set[int]:
        async with self.conn.execute(
            "SELECT room_ids FROM lessons WHERE date = ? AND pair = ?", (date_iso, pair)
        ) as cur:
            return {i for r in await cur.fetchall() for i in _ids(r["room_ids"])}

    # ---------- обратная связь ----------
    async def add_feedback(self, uid: int, text: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO feedback(user_id, text, created_at) VALUES (?, ?, ?)", (uid, text, self._now()))
        await self.conn.commit()
        return cur.lastrowid

    async def get_feedback(self, fid: int) -> dict | None:
        async with self.conn.execute("SELECT * FROM feedback WHERE id = ?", (fid,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def open_feedback(self, limit: int = 10) -> list[dict]:
        async with self.conn.execute(
            "SELECT f.*, u.full_name, u.username FROM feedback f LEFT JOIN users u USING(user_id) "
            "WHERE f.answered = 0 ORDER BY f.id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def count_open_feedback(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) AS c FROM feedback WHERE answered = 0") as cur:
            return (await cur.fetchone())["c"]

    async def answer_feedback(self, fid: int, answer: str | None) -> None:
        await self.conn.execute("UPDATE feedback SET answered = 1, answer = ? WHERE id = ?", (answer, fid))
        await self.conn.commit()

    # ---------- журнал обновлений ----------
    async def log_update(self, ok: bool, forced: bool, lessons: int | None, changes: int | None,
                         duration_ms: int, error: str | None = None) -> None:
        await self.conn.execute(
            "INSERT INTO update_log(at, ok, forced, lessons, changes, duration_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self._now(), int(ok), int(forced), lessons, changes, duration_ms, error))
        await self.conn.execute(
            "DELETE FROM update_log WHERE id <= (SELECT MAX(id) - 500 FROM update_log)")
        await self.conn.commit()

    async def update_log(self, limit: int = 15, only_events: bool = False) -> list[dict]:
        where = "WHERE ok = 0 OR lessons IS NOT NULL" if only_events else ""
        async with self.conn.execute(
            f"SELECT * FROM update_log {where} ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---------- бэкапы и импорт ----------
    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def backup_to(self, path: str) -> None:
        """Целостная копия базы на лету (без остановки бота)."""
        await self.conn.commit()
        await self.conn.execute("VACUUM INTO ?", (path,))

    async def import_ids(self, ids: list[int]) -> tuple[int, int]:
        """Добавляет пользователей по одним ID. Возвращает (добавлено, уже были)."""
        now = self._now()
        added = 0
        for uid in dict.fromkeys(ids):  # без дублей, порядок сохраняем
            cur = await self.conn.execute(
                "INSERT OR IGNORE INTO users(user_id, registered_at, last_seen) VALUES (?, ?, NULL)",
                (uid, now))
            added += cur.rowcount
        await self.conn.commit()
        return added, len(dict.fromkeys(ids)) - added

    async def _upsert_imported(self, u: dict) -> str:
        """'added' | 'updated' | 'skipped'. Существующих не затираем — только дополняем пустые поля."""
        if u.get("kind") and u.get("target_id") and not u.get("target_name"):
            u = {**u, "target_name": await self.entity_name(u["kind"], u["target_id"])}
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (u["user_id"],)) as cur:
            row = await cur.fetchone()
        if row is None:
            await self.conn.execute(
                "INSERT INTO users(user_id, username, full_name, kind, target_id, target_name, notify, "
                "banned, registered_at, last_seen, digest_mode, digest_time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (u["user_id"], u.get("username"), u.get("full_name"), u.get("kind"), u.get("target_id"),
                 u.get("target_name"), int(u.get("notify", 1) or 0), int(u.get("banned", 0) or 0),
                 u.get("registered_at") or self._now(), u.get("last_seen"),
                 u.get("digest_mode"), u.get("digest_time")))
            return "added"
        row = dict(row)
        patch = {}
        if not row["kind"] and u.get("kind") and u.get("target_id"):
            patch.update(kind=u["kind"], target_id=u["target_id"], target_name=u.get("target_name"))
        for f in ("username", "full_name", "digest_mode", "digest_time"):
            if not row.get(f) and u.get(f):
                patch[f] = u[f]
        if u.get("registered_at") and (not row["registered_at"] or u["registered_at"] < row["registered_at"]):
            patch["registered_at"] = u["registered_at"]  # настоящая дата регистрации — более ранняя
        if not patch:
            return "skipped"
        sets = ", ".join(f"{k} = ?" for k in patch)
        await self.conn.execute(f"UPDATE users SET {sets} WHERE user_id = ?", (*patch.values(), u["user_id"]))
        return "updated"

    async def import_users(self, users: list[dict]) -> dict:
        stats = {"added": 0, "updated": 0, "skipped": 0}
        for u in users:
            stats[await self._upsert_imported(u)] += 1
        # рассылка из старых бэкапов (одна колонка) → новые слоты
        await self.conn.execute("UPDATE users SET digest_evening = digest_time, digest_mode = NULL "
                                "WHERE digest_mode = 'evening'")
        await self.conn.execute("UPDATE users SET digest_morning = digest_time, digest_mode = NULL "
                                "WHERE digest_mode = 'morning'")
        await self.conn.commit()
        return stats

    async def merge_from_db(self, path: str) -> dict:
        """Переносит пользователей (и их заметки) из другого файла schedule.db."""
        async with aiosqlite.connect(path) as other:
            other.row_factory = aiosqlite.Row
            async with other.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
                tables = {r["name"] for r in await cur.fetchall()}
            if "users" not in tables:
                raise ValueError("в файле нет таблицы users")
            async with other.execute("SELECT * FROM users") as cur:
                users = [dict(r) for r in await cur.fetchall()]
            notes = []
            if "notes" in tables:
                async with other.execute(
                        "SELECT user_id, kind, target_id, date, pair, text FROM notes") as cur:
                    notes = [tuple(r) for r in await cur.fetchall()]
        stats = await self.import_users(users)
        if notes:
            await self.conn.executemany(
                "INSERT OR IGNORE INTO notes(user_id, kind, target_id, date, pair, text) VALUES (?, ?, ?, ?, ?, ?)",
                notes)
            await self.conn.commit()
        stats["notes"] = len(notes)
        return stats

    async def resolve_target(self, kind: str, name: str) -> int | None:
        """«А-1» → ID группы с сайта (для импорта CSV, где есть только название)."""
        if not name:
            return None
        for _kind, eid, n in await self.search(name, kinds=(kind,)):
            if norm(n) == norm(name):
                return eid
        return None

    async def fill_profile(self, uid: int, username: str | None, full_name: str | None) -> None:
        """Дописывает имя / юзернейм, только если их ещё нет."""
        await self.conn.execute(
            "UPDATE users SET username = COALESCE(username, ?), full_name = COALESCE(full_name, ?) "
            "WHERE user_id = ?", (username, full_name, uid))
        await self.conn.commit()

    # ---------- ⭐ Premium ----------
    PREFS = {"theme", "accent", "bg", "no_watermark", "msg_style", "emoji_set", "remind_before",
             "remind_first_only", "note_remind", "digest_evening", "digest_morning", "digest_week",
             "widget_msg_id", "widget_hash", "bg_photo"}

    async def set_pref(self, uid: int, field: str, value) -> None:
        if field not in self.PREFS:
            raise ValueError(field)
        await self.conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, uid))
        await self.conn.commit()

    async def extend_premium(self, uid: int, days: int | None) -> str:
        """Продлевает Premium от текущей даты окончания (или от сейчас). days=None — навсегда."""
        from utils.premium import FOREVER
        if days is None:
            until = FOREVER
        else:
            user = await self.get_user(uid) or {}
            base = datetime.now(self.tz).replace(tzinfo=None)
            cur = user.get("premium_until")
            if cur == FOREVER:
                return FOREVER
            if cur and cur > base.strftime("%Y-%m-%d %H:%M:%S"):
                base = datetime.strptime(cur, "%Y-%m-%d %H:%M:%S")
            until = (base + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        await self.conn.execute("UPDATE users SET premium_until = ?, premium_warned = NULL WHERE user_id = ?",
                                (until, uid))
        await self.conn.commit()
        return until

    async def revoke_premium(self, uid: int) -> None:
        await self.conn.execute("UPDATE users SET premium_until = NULL WHERE user_id = ?", (uid,))
        await self.conn.commit()

    async def mark_trial(self, uid: int) -> None:
        await self.conn.execute("UPDATE users SET trial_used = 1 WHERE user_id = ?", (uid,))
        await self.conn.commit()

    async def premium_expiring(self, now_s: str, until_s: str) -> list[dict]:
        from utils.premium import FOREVER
        async with self.conn.execute(
            "SELECT * FROM users WHERE premium_until BETWEEN ? AND ? AND premium_until != ? "
            "AND (premium_warned IS NULL OR premium_warned != premium_until) AND banned = 0",
            (now_s, until_s, FOREVER)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_warned(self, uid: int) -> None:
        await self.conn.execute("UPDATE users SET premium_warned = premium_until WHERE user_id = ?", (uid,))
        await self.conn.commit()

    async def premium_stats(self, now_s: str, month_start: str) -> dict:
        from utils.premium import FOREVER
        async with self.conn.execute(
            "SELECT SUM(premium_until >= ?) AS active, SUM(premium_until = ?) AS forever, "
            "SUM(trial_used = 1 AND premium_until >= ? AND NOT EXISTS (SELECT 1 FROM purchases p "
            "WHERE p.user_id = users.user_id AND p.product LIKE 'plan:%' AND p.refunded = 0)) AS trials "
            "FROM users", (now_s, FOREVER, now_s)
        ) as cur:
            row = dict(await cur.fetchone())
        async with self.conn.execute(
            "SELECT COALESCE(SUM(stars), 0) AS total, COUNT(*) AS cnt, "
            "COALESCE(SUM(CASE WHEN created_at >= ? THEN stars END), 0) AS month "
            "FROM purchases WHERE refunded = 0 AND charge_id IS NOT NULL", (month_start,)
        ) as cur:
            row.update(dict(await cur.fetchone()))
        async with self.conn.execute(
            "SELECT product, COUNT(*) AS c, SUM(stars) AS s FROM purchases WHERE refunded = 0 "
            "AND charge_id IS NOT NULL GROUP BY product ORDER BY s DESC LIMIT 8"
        ) as cur:
            row["by_product"] = [dict(r) for r in await cur.fetchall()]
        return {k: (v or 0) if k != "by_product" else v for k, v in row.items()}

    # покупки
    async def add_purchase(self, uid: int, product: str, stars: int, charge_id: str | None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO purchases(user_id, product, stars, charge_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, product, stars, charge_id, self._now()))
        await self.conn.commit()
        return cur.lastrowid

    async def purchases(self, limit: int = 15) -> list[dict]:
        async with self.conn.execute(
            "SELECT p.*, u.full_name, u.username FROM purchases p LEFT JOIN users u USING(user_id) "
            "ORDER BY p.id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_purchase(self, pid: int) -> dict | None:
        async with self.conn.execute("SELECT * FROM purchases WHERE id = ?", (pid,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def mark_refunded(self, pid: int) -> None:
        await self.conn.execute("UPDATE purchases SET refunded = 1 WHERE id = ?", (pid,))
        await self.conn.commit()

    # темы
    async def owned_themes(self, uid: int) -> set[str]:
        async with self.conn.execute("SELECT theme FROM owned_themes WHERE user_id = ?", (uid,)) as cur:
            return {r["theme"] for r in await cur.fetchall()}

    async def add_theme(self, uid: int, theme: str) -> None:
        await self.conn.execute("INSERT OR IGNORE INTO owned_themes VALUES (?, ?)", (uid, theme))
        await self.conn.commit()

    async def remove_theme(self, uid: int, theme: str) -> None:
        await self.conn.execute("DELETE FROM owned_themes WHERE user_id = ? AND theme = ?", (uid, theme))
        await self.conn.commit()

    # избранное
    async def favorites(self, uid: int) -> list[tuple[str, int, str]]:
        async with self.conn.execute(
            "SELECT f.kind, f.target_id, COALESCE(e.name, '?') AS name FROM favorites f "
            "LEFT JOIN entities e ON e.kind = f.kind AND e.id = f.target_id WHERE f.user_id = ? "
            "ORDER BY f.added_at", (uid,)
        ) as cur:
            return [(r["kind"], r["target_id"], r["name"]) for r in await cur.fetchall()]

    async def is_favorite(self, uid: int, kind: str, eid: int) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND kind = ? AND target_id = ?", (uid, kind, eid)
        ) as cur:
            return await cur.fetchone() is not None

    async def add_favorite(self, uid: int, kind: str, eid: int) -> None:
        await self.conn.execute("INSERT OR IGNORE INTO favorites VALUES (?, ?, ?, ?)", (uid, kind, eid, self._now()))
        await self.conn.commit()

    async def remove_favorite(self, uid: int, kind: str, eid: int) -> None:
        await self.conn.execute("DELETE FROM favorites WHERE user_id = ? AND kind = ? AND target_id = ?",
                                (uid, kind, eid))
        await self.conn.commit()

    # промокоды
    async def create_promo(self, code: str, days: int, uses: int) -> None:
        await self.conn.execute("INSERT OR REPLACE INTO promos VALUES (?, ?, ?, ?)",
                                (code.upper(), days, uses, self._now()))
        await self.conn.commit()

    async def promos(self) -> list[dict]:
        async with self.conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM promo_uses u WHERE u.code = p.code) AS used "
            "FROM promos p ORDER BY created_at DESC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def delete_promo(self, code: str) -> None:
        await self.conn.execute("DELETE FROM promos WHERE code = ?", (code.upper(),))
        await self.conn.commit()

    async def redeem_promo(self, uid: int, code: str) -> int | str:
        """Возвращает число дней (0 = навсегда) или текст ошибки."""
        code = code.strip().upper()
        async with self.conn.execute("SELECT * FROM promos WHERE code = ?", (code,)) as cur:
            promo = await cur.fetchone()
        if not promo:
            return "Такого промокода нет 🤔"
        if promo["uses_left"] == 0:
            return "Промокод закончился 😔"
        async with self.conn.execute("SELECT 1 FROM promo_uses WHERE user_id = ? AND code = ?", (uid, code)) as cur:
            if await cur.fetchone():
                return "Ты уже использовал этот промокод"
        await self.conn.execute("INSERT INTO promo_uses VALUES (?, ?, ?)", (uid, code, self._now()))
        if promo["uses_left"] > 0:
            await self.conn.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code = ?", (code,))
        await self.conn.commit()
        return promo["days"]

    # заметки и напоминания
    async def count_future_notes(self, uid: int, today_iso: str) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE user_id = ? AND date >= ?", (uid, today_iso)
        ) as cur:
            return (await cur.fetchone())["c"]

    async def notes_to_remind(self, today_iso: str, now_s: str) -> list[dict]:
        async with self.conn.execute(
            "SELECT n.* FROM notes n JOIN users u USING(user_id) WHERE n.date = ? AND n.reminded = 0 "
            "AND u.note_remind = 1 AND u.premium_until >= ? AND u.banned = 0 ORDER BY n.user_id, n.pair",
            (today_iso, now_s)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_notes_reminded(self, uid: int, date_iso: str) -> None:
        await self.conn.execute("UPDATE notes SET reminded = 1 WHERE user_id = ? AND date = ?", (uid, date_iso))
        await self.conn.commit()

    async def reminder_users(self, now_s: str) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE remind_before IS NOT NULL AND kind IS NOT NULL AND banned = 0 "
            "AND premium_until >= ?", (now_s,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def digest_slot_users(self) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE kind IS NOT NULL AND banned = 0 AND "
            "(digest_evening IS NOT NULL OR digest_morning IS NOT NULL OR digest_week IS NOT NULL)"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_slot(self, uid: int, slot: str, today_iso: str) -> None:
        col = {"e": "last_digest_e", "m": "last_digest_m", "w": "last_digest_w"}[slot]
        await self.conn.execute(f"UPDATE users SET {col} = ? WHERE user_id = ?", (today_iso, uid))
        await self.conn.commit()

    # ---------- 🤝 рефералка ----------
    async def user_exists(self, uid: int) -> bool:
        async with self.conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)) as cur:
            return await cur.fetchone() is not None

    async def set_referrer(self, uid: int, inviter: int) -> None:
        await self.conn.execute("UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
                                (inviter, uid))
        await self.conn.commit()

    async def take_referral_reward(self, uid: int) -> int | None:
        """Если пользователь пришёл по ссылке и бонус ещё не начислен — отмечает и возвращает ID пригласившего."""
        async with self.conn.execute(
            "SELECT referred_by FROM users WHERE user_id = ? AND referred_by IS NOT NULL AND ref_rewarded = 0",
            (uid,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        await self.conn.execute("UPDATE users SET ref_rewarded = 1 WHERE user_id = ?", (uid,))
        await self.conn.commit()
        return row["referred_by"]

    async def referral_counts(self, uid: int) -> tuple[int, int]:
        """(пришли по ссылке, выбрали группу — засчитаны)"""
        async with self.conn.execute(
            "SELECT COUNT(*) AS a, SUM(ref_rewarded) AS b FROM users WHERE referred_by = ?", (uid,)
        ) as cur:
            row = await cur.fetchone()
        return row["a"] or 0, row["b"] or 0

    async def top_inviters(self, limit: int = 5) -> list[dict]:
        async with self.conn.execute(
            "SELECT u.user_id, u.full_name, u.username, COUNT(*) AS c FROM users r JOIN users u "
            "ON u.user_id = r.referred_by WHERE r.ref_rewarded = 1 GROUP BY u.user_id ORDER BY c DESC LIMIT ?",
            (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---------- 🎁 подарки ----------
    async def create_gift(self, code: str, plan: str, buyer: int) -> None:
        await self.conn.execute("INSERT INTO gifts(code, plan, buyer_id, created_at) VALUES (?, ?, ?, ?)",
                                (code, plan, buyer, self._now()))
        await self.conn.commit()

    async def get_gift(self, code: str) -> dict | None:
        async with self.conn.execute("SELECT * FROM gifts WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def redeem_gift(self, code: str, uid: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE gifts SET redeemed_by = ?, redeemed_at = ? WHERE code = ? AND redeemed_by IS NULL",
            (uid, self._now(), code))
        await self.conn.commit()
        return cur.rowcount == 1

    async def gifts_of(self, buyer: int) -> list[dict]:
        async with self.conn.execute(
            "SELECT g.*, u.full_name FROM gifts g LEFT JOIN users u ON u.user_id = g.redeemed_by "
            "WHERE g.buyer_id = ? ORDER BY g.created_at DESC LIMIT 10", (buyer,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---------- 🏆 достижения ----------
    async def achievements(self, uid: int) -> dict[str, str]:
        async with self.conn.execute("SELECT code, at FROM achievements WHERE user_id = ?", (uid,)) as cur:
            return {r["code"]: r["at"] for r in await cur.fetchall()}

    async def grant_achievement(self, uid: int, code: str) -> bool:
        cur = await self.conn.execute("INSERT OR IGNORE INTO achievements VALUES (?, ?, ?)", (uid, code, self._now()))
        await self.conn.commit()
        return cur.rowcount == 1

    async def achievement_progress(self, uid: int, since_week: str) -> dict:
        q = {
            "notes": "SELECT COUNT(*) FROM notes WHERE user_id = ?",
            "images": "SELECT COUNT(*) FROM events WHERE user_id = ? AND name = 'img'",
            "invites": "SELECT COUNT(*) FROM users WHERE referred_by = ? AND ref_rewarded = 1",
            "digests": "SELECT digests_sent FROM users WHERE user_id = ?",
            "paid": "SELECT COUNT(*) FROM purchases WHERE user_id = ? AND charge_id IS NOT NULL AND refunded = 0 "
                    "AND (product LIKE 'plan:%' OR product LIKE 'donate:%' OR product LIKE 'theme:%')",
            "gifts": "SELECT COUNT(*) FROM gifts WHERE buyer_id = ?",
            "chosen": "SELECT kind IS NOT NULL FROM users WHERE user_id = ?",
        }
        res = {}
        for k, sql in q.items():
            async with self.conn.execute(sql, (uid,)) as cur:
                row = await cur.fetchone()
                res[k] = (row[0] if row else 0) or 0
        async with self.conn.execute(
            "SELECT COUNT(DISTINCT day) FROM events WHERE user_id = ? AND day >= ?", (uid, since_week)
        ) as cur:
            res["streak"] = (await cur.fetchone())[0] or 0
        return res

    async def inc_digests(self, uid: int) -> None:
        await self.conn.execute("UPDATE users SET digests_sent = digests_sent + 1 WHERE user_id = ?", (uid,))
        await self.conn.commit()

    # ---------- 📱 виджет ----------
    async def widget_users(self, now_s: str) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE widget_msg_id IS NOT NULL AND kind IS NOT NULL AND banned = 0 "
            "AND premium_until >= ?", (now_s,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---------- 📊 статистика фич ----------
    async def log_event(self, uid: int, name: str) -> None:
        await self.conn.execute("INSERT INTO events VALUES (?, ?, ?)", (self._now()[:10], uid, name))
        await self.conn.commit()

    async def feature_stats(self, since: str) -> list[dict]:
        async with self.conn.execute(
            "SELECT name, COUNT(*) AS c, COUNT(DISTINCT user_id) AS u FROM events WHERE day >= ? "
            "GROUP BY name ORDER BY c DESC", (since,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def usage_counts(self, now_s: str) -> dict:
        sql = {
            "digest": "SELECT COUNT(*) FROM users WHERE banned = 0 AND (digest_evening IS NOT NULL "
                      "OR digest_morning IS NOT NULL OR digest_week IS NOT NULL)",
            "remind": "SELECT COUNT(*) FROM users WHERE remind_before IS NOT NULL AND premium_until >= ?",
            "widget": "SELECT COUNT(*) FROM users WHERE widget_msg_id IS NOT NULL AND premium_until >= ?",
            "notes_users": "SELECT COUNT(DISTINCT user_id) FROM notes",
            "fav_users": "SELECT COUNT(DISTINCT user_id) FROM favorites",
            "themed": "SELECT COUNT(*) FROM users WHERE theme IS NOT NULL AND theme != 'classic'",
            "notify_off": "SELECT COUNT(*) FROM users WHERE notify = 0 AND kind IS NOT NULL",
        }
        res = {}
        for k, q in sql.items():
            async with self.conn.execute(q, (now_s,) if "?" in q else ()) as cur:
                res[k] = (await cur.fetchone())[0] or 0
        return res

    # ---------- 📈 графики ----------
    async def daily_series(self, since: str) -> dict:
        res = {}
        for key, sql in {
            "new": "SELECT substr(registered_at, 1, 10) AS d, COUNT(*) FROM users "
                   "WHERE registered_at >= ? GROUP BY d",
            "dau": "SELECT day AS d, COUNT(DISTINCT user_id) FROM events WHERE day >= ? GROUP BY d",
            "stars": "SELECT substr(created_at, 1, 10) AS d, SUM(stars) FROM purchases "
                     "WHERE created_at >= ? AND refunded = 0 AND charge_id IS NOT NULL GROUP BY d",
        }.items():
            async with self.conn.execute(sql, (since,)) as cur:
                res[key] = {r[0]: r[1] for r in await cur.fetchall()}
        async with self.conn.execute("SELECT COUNT(*) FROM users WHERE registered_at < ?", (since,)) as cur:
            res["base"] = (await cur.fetchone())[0] or 0
        return res

    # ---------- 📲 виджет на рабочий стол ----------
    async def home_token(self, uid: int, reset: bool = False) -> str:
        import secrets
        user = await self.get_user(uid) or {}
        token = user.get("home_token")
        if reset or not token:
            token = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
            await self.conn.execute("UPDATE users SET home_token = ? WHERE user_id = ?", (token, uid))
            await self.conn.commit()
        return token

    async def user_by_home_token(self, token: str) -> dict | None:
        async with self.conn.execute("SELECT * FROM users WHERE home_token = ?", (token,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None
