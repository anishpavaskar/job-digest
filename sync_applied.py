"""Sync applied.txt URLs into the tracker, with Greenhouse auto-apply support."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from auto_apply import auto_apply_greenhouse, parse_greenhouse_url
from logging_config import get_logger
from tracker import ensure_job, get_job, init_db, update_status

APPLIED_FILE = Path(__file__).parent / "applied.txt"
log = get_logger("sync")


def sync_applied() -> int:
    """Mark URLs from applied.txt as applied in tracker.db."""
    if not APPLIED_FILE.exists():
        APPLIED_FILE.touch()
        log.info("created applied.txt - add URLs there to mark as applied")
        return 0

    init_db()
    synced = 0

    with APPLIED_FILE.open(encoding="utf-8") as handle:
        for raw_line in handle:
            url = raw_line.strip()
            if not url or url.startswith("#"):
                continue

            existing = get_job(url)
            if existing and existing.get("status") == "applied":
                log.info("already applied: %s", url[:70])
                continue

            ensure_job(url)
            slug, job_id = parse_greenhouse_url(url)
            notes = ""

            if slug and job_id:
                log.info("Greenhouse URL detected - auto-applying")
                success = auto_apply_greenhouse(url)
                if success:
                    notes = "auto-applied via Greenhouse API"
                else:
                    notes = "auto-apply failed - check manually"
                    log.warning("Auto-apply failed for %s; marking applied manually", url[:70])

            try:
                update_status(url, "applied", notes=notes)
                log.info("applied: %s", url[:70])
                synced += 1
            except Exception as exc:
                log.error("failed for %s: %s", url[:70], exc)

    log.info("%s jobs marked as applied", synced)
    return synced


if __name__ == "__main__":
    sync_applied()
