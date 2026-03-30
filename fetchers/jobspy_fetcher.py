"""JobSpy fetcher for Indeed, ZipRecruiter, Google Jobs, and LinkedIn."""

from __future__ import annotations

import asyncio
from typing import Any

from config import JOBSPY_SEARCHES
from logging_config import get_logger

SITES = ["indeed", "zip_recruiter", "google", "linkedin"]
RESULTS_PER_QUERY = 15
HOURS_OLD = 24
REQUEST_TIMEOUT_SECONDS = 60
log = get_logger("jobspy")


def _silence_jobspy_logs(jobspy_module: Any) -> None:
    import logging

    def _quiet_create_logger(name: str) -> logging.Logger:
        quiet_logger = logging.getLogger(f"JobSpy:{name}")
        quiet_logger.handlers.clear()
        quiet_logger.propagate = False
        quiet_logger.setLevel(logging.ERROR)
        return quiet_logger

    jobspy_module.create_logger = _quiet_create_logger
    try:
        from jobspy import util as jobspy_util

        jobspy_util.create_logger = _quiet_create_logger
    except Exception:
        return


def _normalize(row: dict[str, Any]) -> dict[str, str]:
    url = str(row.get("job_url", "") or "").strip()
    city = str(row.get("city", "") or "").strip()
    state = str(row.get("state", "") or "").strip()
    location = ", ".join(part for part in [city, state] if part) or "Remote"
    return {
        "id": f"jobspy:{row.get('site', '')}:{url[-40:]}",
        "title": str(row.get("title", "") or "").strip(),
        "company": str(row.get("company", "") or "").strip(),
        "location": location,
        "url": url,
        "description": str(row.get("description", "") or "")[:600],
        "source": str(row.get("site", "jobspy") or "jobspy").strip(),
        "posted_at": str(row.get("date_posted", "") or "").strip(),
    }


async def _search_one(query: str) -> list[dict[str, str]]:
    try:
        import jobspy

        _silence_jobspy_logs(jobspy)
        scrape_jobs = jobspy.scrape_jobs
    except ImportError:
        log.warning("python-jobspy not installed — skipping")
        return []

    try:
        dataframe = await asyncio.wait_for(
            asyncio.to_thread(
                scrape_jobs,
                site_name=SITES,
                search_term=query,
                location="Remote",
                is_remote=True,
                results_wanted=RESULTS_PER_QUERY,
                hours_old=HOURS_OLD,
                job_type="fulltime",
                description_format="markdown",
                country_indeed="USA",
            ),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if dataframe is None or dataframe.empty:
            return []

        jobs: list[dict[str, str]] = []
        for _, row in dataframe.iterrows():
            job = _normalize(row.to_dict())
            if job["url"] and job["title"]:
                jobs.append(job)
        log.info("'%s': %s jobs", query, len(jobs))
        return jobs
    except asyncio.TimeoutError:
        log.warning("'%s' timed out", query)
        return []
    except Exception as exc:
        log.warning("'%s' failed: %s", query, exc)
        return []


async def fetch_jobspy_jobs(queries: list[str] | None = None) -> list[dict[str, str]]:
    if queries is None:
        queries = JOBSPY_SEARCHES
    if not queries:
        return []

    results = await asyncio.gather(*[_search_one(query) for query in queries], return_exceptions=True)
    seen_urls: set[str] = set()
    jobs: list[dict[str, str]] = []
    for result in results:
        if isinstance(result, list):
            for job in result:
                if job["url"] and job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    jobs.append(job)
    log.info("Total unique: %s", len(jobs))
    return jobs
