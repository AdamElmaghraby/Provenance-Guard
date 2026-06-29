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
                status TEXT NOT NULL,
                appeal_reasoning TEXT
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
        if "appeal_reasoning" not in columns:
            conn.execute("ALTER TABLE audit_log ADD COLUMN appeal_reasoning TEXT")


def append_entry(
    *,
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_score: float,
    stylometric_score: float,
    status: str = "classified",
    appeal_reasoning: str | None = None,
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
                status,
                appeal_reasoning
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                appeal_reasoning,
            ),
        )


def mark_under_review(content_id: str, creator_reasoning: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM audit_log WHERE content_id = ? LIMIT 1",
            (content_id,),
        ).fetchone()
        if row is None:
            return False

        conn.execute(
            """
            UPDATE audit_log
            SET status = ?, appeal_reasoning = ?
            WHERE content_id = ?
            """,
            ("under_review", creator_reasoning, content_id),
        )
    return True


def get_recent_entries(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT content_id, creator_id, timestamp, attribution, confidence, llm_score, stylometric_score, status, appeal_reasoning
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]
