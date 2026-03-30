"""SQLite-backed job tracker for cross-run deduplication and funnel status."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import DB_PATH as CONFIG_DB_PATH
from logging_config import get_logger

DB_PATH = Path(CONFIG_DB_PATH)
VALID_STATUSES = {"new", "skipped", "applied", "interviewing", "rejected", "offer"}
log = get_logger("tracker")

Job = dict[str, Any]


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tracker tables if they do not already exist."""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                url          TEXT PRIMARY KEY,
                id           TEXT,
                title        TEXT,
                company      TEXT,
                location     TEXT,
                source       TEXT,
                description  TEXT,
                score        INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'new',
                first_seen   TEXT,
                last_seen    TEXT,
                applied_at   TEXT,
                notes        TEXT DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_score ON jobs(score DESC)")
        conn.commit()


def filter_new_jobs(jobs: list[Job]) -> list[Job]:
    """
    Return only jobs whose URL has not been seen before.

    Existing jobs keep their original row and only have `last_seen` refreshed.
    """
    init_db()
    now = datetime.now().isoformat()
    new_jobs: list[Job] = []

    with _get_conn() as conn:
        for job in jobs:
            url = str(job.get("url", "") or "").strip()
            if not url:
                continue

            existing = conn.execute("SELECT url FROM jobs WHERE url = ?", (url,)).fetchone()
            if existing:
                conn.execute("UPDATE jobs SET last_seen = ? WHERE url = ?", (now, url))
                continue

            conn.execute(
                """
                INSERT INTO jobs (
                    url,
                    id,
                    title,
                    company,
                    location,
                    source,
                    description,
                    status,
                    first_seen,
                    last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
                """,
                (
                    url,
                    str(job.get("id", "") or ""),
                    str(job.get("title", "") or ""),
                    str(job.get("company", "") or ""),
                    str(job.get("location", "") or ""),
                    str(job.get("source", "") or ""),
                    str(job.get("description", "") or "")[:500],
                    now,
                    now,
                ),
            )
            new_jobs.append(job)

        conn.commit()

    return new_jobs


def update_scores(scored_jobs: list[Job]) -> None:
    """Persist scores after scoring completes."""
    init_db()
    with _get_conn() as conn:
        for job in scored_jobs:
            conn.execute(
                "UPDATE jobs SET score = ? WHERE url = ?",
                (int(job.get("score", 0) or 0), str(job.get("url", "") or "")),
            )
        conn.commit()


def update_status(url: str, status: str, notes: str = "") -> None:
    """Update a tracked job status, optionally storing notes."""
    if status not in VALID_STATUSES:
        valid_statuses = ", ".join(sorted(VALID_STATUSES))
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    init_db()
    now = datetime.now().isoformat()
    applied_at = now if status == "applied" else None

    with _get_conn() as conn:
        if applied_at:
            result = conn.execute(
                """
                UPDATE jobs
                SET status = ?, notes = ?, applied_at = ?
                WHERE url = ?
                """,
                (status, notes, applied_at, url),
            )
        else:
            result = conn.execute(
                "UPDATE jobs SET status = ?, notes = ? WHERE url = ?",
                (status, notes, url),
            )

        if result.rowcount == 0:
            raise ValueError(f"Job not found for URL: {url}")

        conn.commit()

    log.info("Updated status for %s... -> %s", url[:60], status)


def get_stats() -> dict[str, Any]:
    """Return a summary of tracked jobs and current funnel state."""
    init_db()
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        by_status = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM jobs
            GROUP BY status
            ORDER BY count DESC, status ASC
            """
        ).fetchall()
        top_sources = conn.execute(
            """
            SELECT COALESCE(NULLIF(source, ''), 'unknown') AS source, COUNT(*) AS count
            FROM jobs
            GROUP BY COALESCE(NULLIF(source, ''), 'unknown')
            ORDER BY count DESC, source ASC
            LIMIT 5
            """
        ).fetchall()
        recent = conn.execute(
            """
            SELECT title, company, score, status, first_seen
            FROM jobs
            ORDER BY first_seen DESC
            LIMIT 5
            """
        ).fetchall()

    return {
        "total_seen": total,
        "by_status": {row["status"]: row["count"] for row in by_status},
        "top_sources": {row["source"]: row["count"] for row in top_sources},
        "recent": [dict(row) for row in recent],
    }


def get_applied_jobs() -> list[Job]:
    """Return tracked jobs with applied status."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = 'applied'
            ORDER BY applied_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def search_jobs(query: str = "", status: str = "", limit: int = 20) -> list[Job]:
    """Search tracked jobs by title/company and optionally filter by status."""
    init_db()
    sql = "SELECT * FROM jobs WHERE 1=1"
    params: list[Any] = []

    if query:
        sql += " AND (title LIKE ? OR company LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY score DESC, first_seen DESC LIMIT ?"
    params.append(limit)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
