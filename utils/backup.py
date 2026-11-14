from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from config import BACKUP_DIR, BACKUP_KEEP, DB_PATH, TZ
from utils.db import DB

SQLITE_HEADER = b"SQLite format 3\x00"


def backup_dir() -> Path:
    path = Path(BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backups() -> list[Path]:
    return sorted(backup_dir().glob("schedule_*.db"), reverse=True)


def is_sqlite(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_HEADER
    except OSError:
        return False


async def make_backup(db: DB, tag: str = "auto") -> Path:
    stamp = datetime.now(TZ).strftime("%Y-%m-%d_%H-%M-%S")
    path = backup_dir() / f"schedule_{stamp}_{tag}.db"
    n = 2
    while path.exists():
        path = backup_dir() / f"schedule_{stamp}-{n}_{tag}.db"
        n += 1
    await db.backup_to(str(path))
    _rotate()
    return path


def _rotate() -> None:
    regular = [p for p in list_backups() if "_before-" not in p.stem]
    for old in regular[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)


async def restore(db: DB, source: Path) -> Path:
    if not is_sqlite(source):
        raise ValueError("это не файл базы SQLite")
    safety = await make_backup(db, "before-restore")
    tmp = Path(DB_PATH).with_suffix(".restoring")
    shutil.copyfile(source, tmp)
    await db.close()
    try:
        tmp.replace(DB_PATH)
    finally:
        await db.connect()
    return safety


def describe(path: Path) -> str:
    parts = path.stem.split("_")
    try:
        dt = datetime.strptime(f"{parts[1]} {parts[2][:8]}", "%Y-%m-%d %H-%M-%S")
        when = dt.strftime("%d.%m %H:%M")
    except (IndexError, ValueError):
        when = path.stem
    tag = {"auto": "авто", "manual": "вручную", "before-restore": "до восстановления",
           "before-import": "до импорта"}.get(
        parts[-1] if len(parts) > 3 else "", "")
    size = path.stat().st_size / 1024
    size_s = f"{size:.0f} КБ" if size < 1024 else f"{size / 1024:.1f} МБ"
    return " · ".join(x for x in (when, tag, size_s) if x)
