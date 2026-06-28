import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "provenance_guard.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                attribution TEXT NOT NULL,
                confidence REAL NOT NULL,
                llm_score REAL NOT NULL,
                stylometric_score REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL
            )
            """
        )

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()
        }
        if "stylometric_score" not in columns:
            conn.execute(
                "ALTER TABLE audit_log ADD COLUMN stylometric_score REAL NOT NULL DEFAULT 0.0"
            )


def append_entry(
    *,
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_score: float,
    stylometric_score: float,
    status: str = "classified",
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                content_id,
                creator_id,
                timestamp,
                attribution,
                confidence,
                llm_score,
                stylometric_score,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id,
                creator_id,
                timestamp,
                attribution,
                confidence,
                llm_score,
                stylometric_score,
                status,
            ),
        )


def get_recent_entries(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT content_id, creator_id, timestamp, attribution, confidence, llm_score, stylometric_score, status
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]
