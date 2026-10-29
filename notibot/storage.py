"""Persistencia mínima en SQLite: noticias enviadas y ejecuciones."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import NewsItem
from .utils import utcnow

log = logging.getLogger(__name__)


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS seen (
                    code TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    items INTEGER DEFAULT 0,
                    error TEXT
                );
                """
            )

    def filter_new(self, items: list[NewsItem]) -> list[NewsItem]:
        if not items:
            return []
        codes = [item.code for item in items if item.code]
        if not codes:
            return items
        placeholders = ",".join("?" for _ in codes)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT code FROM seen WHERE code IN ({placeholders})",
                    codes,
                ).fetchall()
        except sqlite3.Error as exc:
            log.warning("No se pudo consultar SQLite: %s", exc)
            return items

        seen = {row["code"] for row in rows}
        return [item for item in items if not item.code or item.code not in seen]

    def mark_sent(self, items: list[NewsItem]) -> None:
        if not items:
            return
        sent_at = utcnow().isoformat()
        rows = [
            (item.code or item.url, item.url, item.source, sent_at)
            for item in items
        ]
        try:
            with self._lock, self._connect() as connection:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO seen (code, url, source, sent_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    rows,
                )
        except sqlite3.Error as exc:
            log.warning("No se pudo guardar en SQLite: %s", exc)

    def record_run(
        self,
        kind: str,
        started_at: datetime,
        status: str,
        items: int = 0,
        error: str | None = None,
    ) -> None:
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO runs (kind, started_at, finished_at, status, items, error)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kind,
                        started_at.isoformat(),
                        utcnow().isoformat(),
                        status,
                        items,
                        (error or "")[:500] or None,
                    ),
                )
        except sqlite3.Error as exc:
            log.warning("No se pudo registrar la ejecución: %s", exc)

    def last_success(self) -> str | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT finished_at FROM runs
                    WHERE status = 'success'
                    ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
        except sqlite3.Error:
            return None
        return str(row["finished_at"]) if row else None

    def stats(self) -> dict[str, object]:
        try:
            with self._connect() as connection:
                seen = connection.execute(
                    "SELECT COUNT(*) AS total FROM seen"
                ).fetchone()["total"]
                last = connection.execute(
                    """
                    SELECT kind, status, started_at, finished_at, items, error
                    FROM runs ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
        except sqlite3.Error:
            return {"seen": 0, "last_run": None}
        return {
            "seen": int(seen),
            "last_run": dict(last) if last else None,
        }

    def prune_seen(self, days: int = 30) -> None:
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "DELETE FROM seen WHERE sent_at < datetime('now', ?)",
                    (f"-{int(days)} days",),
                )
        except sqlite3.Error as exc:
            log.debug("No se pudo limpiar SQLite: %s", exc)
