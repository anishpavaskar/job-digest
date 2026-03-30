"""Exports tracker data for the static Vercel dashboard."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from logging_config import get_logger
from tracker import get_stats, init_db, search_jobs

PROJECT_ROOT = Path(__file__).resolve().parent
DASHBOARD_DATA = PROJECT_ROOT / "dashboard" / "data"
JOBS_JSON = DASHBOARD_DATA / "jobs.json"
EXPORT_PATH = Path("dashboard") / "data" / "jobs.json"
GIT_TIMEOUT_SECONDS = 60
log = get_logger("export")


def export_jobs() -> int:
    """Export all tracked jobs from SQLite to dashboard/data/jobs.json."""
    init_db()
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)

    jobs = search_jobs(query="", status="", limit=2000)
    stats = get_stats()
    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "jobs": jobs,
    }

    JOBS_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    log.info("Wrote %s jobs to dashboard/data/jobs.json", len(jobs))
    return len(jobs)


def _git_run(args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def git_push() -> None:
    """Commit and push dashboard data updates to GitHub."""
    try:
        _git_run(["git", "add", str(EXPORT_PATH)], check=True)

        staged_diff = _git_run(["git", "diff", "--staged", "--quiet", "--", str(EXPORT_PATH)])
        if staged_diff.returncode == 0:
            log.info("No changes to push - dashboard already current")
            return
        if staged_diff.returncode not in (0, 1):
            log.warning("Git diff failed: %s", (staged_diff.stderr or staged_diff.stdout).strip()[:200])
            return

        message = f"digest update {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        _git_run(["git", "commit", "-m", message, "--", str(EXPORT_PATH)], check=True)
        _git_run(["git", "push", "origin", "main"], check=True)
        log.info("Pushed to GitHub -> Vercel deploying...")
    except FileNotFoundError:
        log.warning("Git is not available; dashboard data was saved locally only")
    except subprocess.CalledProcessError as exc:
        error_output = (exc.stderr or exc.stdout or str(exc)).strip()[:200]
        log.warning("Git push failed: %s", error_output)
        log.info("Dashboard data saved locally but was not pushed")
    except subprocess.TimeoutExpired as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()[:200]
        log.warning("Git command timed out: %s", message)
        log.info("Dashboard data saved locally but was not pushed")


def export_and_push() -> None:
    """Export current dashboard data and push it when there is data to publish."""
    count = export_jobs()
    if count > 0:
        git_push()


if __name__ == "__main__":
    export_and_push()
