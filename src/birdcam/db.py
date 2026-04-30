"""SQLite database for detection metadata."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    confidence REAL NOT NULL,
    bbox_x1 REAL NOT NULL,
    bbox_y1 REAL NOT NULL,
    bbox_x2 REAL NOT NULL,
    bbox_y2 REAL NOT NULL,
    image_path TEXT NOT NULL,
    thumbnail_path TEXT NOT NULL,
    burst_paths TEXT NOT NULL DEFAULT '[]',
    favorite INTEGER NOT NULL DEFAULT 0,
    species TEXT,
    classified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp);
CREATE INDEX IF NOT EXISTS idx_detections_confidence ON detections(confidence);
"""

MIGRATIONS = [
    "ALTER TABLE detections ADD COLUMN species TEXT",
    "ALTER TABLE detections ADD COLUMN classified_at TEXT",
]


@dataclass
class Detection:
    id: int
    timestamp: float
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    image_path: str
    thumbnail_path: str
    burst_paths: list[str]
    favorite: bool
    species: str | None


class DetectionDB:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Run schema migrations that haven't been applied yet."""
        for sql in MIGRATIONS:
            try:
                self._conn.execute(sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # already applied

    def insert(
        self,
        timestamp: float,
        confidence: float,
        bbox: tuple[float, float, float, float],
        image_path: str,
        thumbnail_path: str,
        burst_paths: list[str] | None = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO detections
               (timestamp, confidence, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                image_path, thumbnail_path, burst_paths)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                confidence,
                *bbox,
                image_path,
                thumbnail_path,
                json.dumps(burst_paths or []),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get(self, detection_id: int) -> Detection | None:
        row = self._conn.execute(
            "SELECT * FROM detections WHERE id = ?", (detection_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_detection(row)

    def list_detections(
        self,
        limit: int = 50,
        offset: int = 0,
        min_confidence: float | None = None,
        date: str | None = None,
        favorites_only: bool = False,
    ) -> list[Detection]:
        query = "SELECT * FROM detections WHERE 1=1"
        params: list = []

        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        if date is not None:
            query += " AND date(timestamp, 'unixepoch', 'localtime') = ?"
            params.append(date)

        if favorites_only:
            query += " AND favorite = 1"

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_detection(r) for r in rows]

    def count(
        self,
        min_confidence: float | None = None,
        date: str | None = None,
        favorites_only: bool = False,
    ) -> int:
        query = "SELECT COUNT(*) FROM detections WHERE 1=1"
        params: list = []

        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        if date is not None:
            query += " AND date(timestamp, 'unixepoch', 'localtime') = ?"
            params.append(date)

        if favorites_only:
            query += " AND favorite = 1"

        return self._conn.execute(query, params).fetchone()[0]

    def set_species(self, detection_id: int, species: str) -> None:
        self._conn.execute(
            "UPDATE detections SET species = ?, classified_at = datetime('now') WHERE id = ?",
            (species, detection_id),
        )
        self._conn.commit()

    def classifications_today(self) -> int:
        """Count API classifications made today (local time).

        Tracks when the API call happened (`classified_at`), not the detection
        timestamp — so backfilling old detections still counts against the
        per-day budget.
        """
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        row = self._conn.execute(
            """SELECT COUNT(*) FROM detections
               WHERE classified_at IS NOT NULL
               AND date(classified_at, 'localtime') = ?""",
            (today,),
        ).fetchone()
        return row[0]

    def get_unclassified(self, limit: int = 50) -> list[Detection]:
        """Return detections with no species label, oldest first."""
        rows = self._conn.execute(
            """SELECT * FROM detections
               WHERE species IS NULL
               ORDER BY timestamp ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_detection(r) for r in rows]

    def delete(self, detection_id: int) -> None:
        self._conn.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
        self._conn.commit()

    def set_favorite(self, detection_id: int, favorite: bool) -> None:
        self._conn.execute(
            "UPDATE detections SET favorite = ? WHERE id = ?",
            (int(favorite), detection_id),
        )
        self._conn.commit()

    def get_dates(self) -> list[str]:
        """Return distinct detection dates, newest first."""
        rows = self._conn.execute(
            """SELECT DISTINCT date(timestamp, 'unixepoch', 'localtime') as d
               FROM detections ORDER BY d DESC"""
        ).fetchall()
        return [r[0] for r in rows]

    def get_burst_paths_older_than(self, days: int) -> list[tuple[int, list[str]]]:
        """Return (id, burst_paths) for non-favorite detections older than N days."""
        import time

        cutoff = time.time() - (days * 86400)
        rows = self._conn.execute(
            """SELECT id, burst_paths FROM detections
               WHERE timestamp < ? AND favorite = 0 AND burst_paths != '[]'""",
            (cutoff,),
        ).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def clear_burst_paths(self, detection_id: int) -> None:
        self._conn.execute(
            "UPDATE detections SET burst_paths = '[]' WHERE id = ?",
            (detection_id,),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    @staticmethod
    def _row_to_detection(row: sqlite3.Row) -> Detection:
        return Detection(
            id=row["id"],
            timestamp=row["timestamp"],
            confidence=row["confidence"],
            bbox=(row["bbox_x1"], row["bbox_y1"], row["bbox_x2"], row["bbox_y2"]),
            image_path=row["image_path"],
            thumbnail_path=row["thumbnail_path"],
            burst_paths=json.loads(row["burst_paths"]),
            favorite=bool(row["favorite"]),
            species=row["species"],
        )
