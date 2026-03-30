"""APScheduler entrypoint for twice-daily job digest runs."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from main import run_pipeline

DEFAULT_TZ = "America/Los_Angeles"


def _timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("TZ", DEFAULT_TZ))


def _log(message: str) -> None:
    print(message)


def _run_pipeline_job() -> None:
    asyncio.run(run_pipeline())


def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=_timezone())
    scheduler.add_job(_run_pipeline_job, "cron", hour=7, minute=0, id="job_digest_morning")
    scheduler.add_job(_run_pipeline_job, "cron", hour=17, minute=0, id="job_digest_evening")
    return scheduler


def main() -> None:
    scheduler = create_scheduler()
    _log(f"Starting scheduler — {datetime.now(_timezone())}")
    for job in scheduler.get_jobs():
        _log(f"Scheduled {job.id} — next run at {job.next_run_time}")
    scheduler.start()


if __name__ == "__main__":
    main()
