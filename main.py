"""Entrypoint for the job digest pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from config import GREENHOUSE_COMPANIES, MAX_JOB_AGE_DAYS, MY_PROFILE
from emailer import send_digest
from export_data import export_and_push
from fetchers.greenhouse import fetch_greenhouse_jobs
from fetchers.jobspy_fetcher import fetch_jobspy_jobs
from fetchers.linkedin_mcp_fetcher import fetch_linkedin_mcp_jobs
from fetchers.playwright_fetcher import fetch_ashby_jobs, fetch_lever_jobs
from fetchers.prospect import fetch_prospect
from fetchers.yc import fetch_yc
from logging_config import get_logger
from renderer import OUTPUT_PATH, render_html
from scorer import score_jobs
from sync_applied import sync_applied
from tracker import filter_new_jobs, init_db, update_scores

Job = dict[str, Any]
MAX_SCORING_JOBS = 100
HEURISTIC_ROLE_TERMS = ("engineer", "engineering", "developer", "platform", "backend", "infrastructure", "sre", "devops")
SOURCE_NAMES = ["greenhouse", "yc", "prospect", "jobspy", "linkedin_mcp", "lever", "ashby"]
log = get_logger("main")


def _export_dashboard() -> None:
    try:
        export_and_push()
    except Exception as exc:
        log.error("Dashboard export failed: %s", exc)


def _deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    unique_by_url: dict[str, Job] = {}
    for job in jobs:
        key = str(job.get("url") or job.get("id") or "").strip()
        if not key:
            continue
        unique_by_url[key] = job

    title_company_seen: set[str] = set()
    deduplicated: list[Job] = []
    for job in unique_by_url.values():
        title = str(job.get("title", "") or "").lower().strip()
        company = str(job.get("company", "") or "").lower().strip()
        key = f"{title}:{company}"
        if not title and not company:
            deduplicated.append(job)
            continue
        if key in title_company_seen:
            continue
        title_company_seen.add(key)
        deduplicated.append(job)
    return deduplicated


def _shortlist_terms() -> set[str]:
    profile_terms = {
        term.lower()
        for bucket in (
            MY_PROFILE.get("target_roles", []),
            MY_PROFILE.get("skills_tier1", []),
            MY_PROFILE.get("skills_tier2", []),
            MY_PROFILE.get("preferred_domains", []),
        )
        for term in bucket
    }
    profile_terms.update(HEURISTIC_ROLE_TERMS)
    return profile_terms


def _heuristic_rank(job: Job, terms: set[str]) -> int:
    haystack = " ".join(
        [
            str(job.get("title", "")),
            str(job.get("description", "")),
            str(job.get("company", "")),
            str(job.get("location", "")),
        ]
    ).lower()

    score = 0
    for term in terms:
        if term in haystack:
            score += 3 if term in HEURISTIC_ROLE_TERMS else 1
    if str(job.get("title", "")).lower().find("engineer") != -1:
        score += 5
    return score


def _shortlist_jobs(jobs: list[Job]) -> list[Job]:
    terms = _shortlist_terms()
    ranked = sorted(
        ((job, _heuristic_rank(job, terms)) for job in jobs),
        key=lambda item: item[1],
        reverse=True,
    )
    shortlisted = [job for job, rank in ranked if rank > 0][:MAX_SCORING_JOBS]
    return shortlisted or [job for job, _ in ranked[:MAX_SCORING_JOBS]]


def _parse_posted_at(value: Any) -> datetime | None:
    posted_clean = str(value or "").strip()
    if not posted_clean:
        return None

    candidates = [
        posted_clean,
        posted_clean[:19],
        posted_clean.replace("Z", "+00:00"),
    ]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                return parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            continue

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(posted_clean[:19], fmt)
        except ValueError:
            continue
    return None


def filter_fresh_jobs(jobs: list[Job], max_days: int = 7) -> list[Job]:
    """Keep jobs with no date or a posted_at value within max_days."""
    cutoff = datetime.now() - timedelta(days=max_days)
    fresh_jobs: list[Job] = []
    stale_count = 0

    for job in jobs:
        posted_at = _parse_posted_at(job.get("posted_at"))
        if posted_at is None:
            fresh_jobs.append(job)
            continue

        if posted_at >= cutoff:
            fresh_jobs.append(job)
            continue

        stale_count += 1

    if stale_count:
        log.info("Filtered %s stale jobs older than %s days", stale_count, max_days)
    return fresh_jobs


async def run_pipeline() -> list[Job]:
    log.info("Starting job digest pipeline")
    try:
        sync_applied()
    except Exception as exc:
        log.error("applied.txt sync failed: %s", exc)
    init_db()

    results = await asyncio.gather(
        fetch_greenhouse_jobs(GREENHOUSE_COMPANIES),
        fetch_yc(),
        fetch_prospect(),
        fetch_jobspy_jobs(),
        fetch_linkedin_mcp_jobs(),
        fetch_lever_jobs(),
        fetch_ashby_jobs(),
        return_exceptions=True,
    )

    all_jobs: list[Job] = []
    for index, result in enumerate(results):
        source = SOURCE_NAMES[index]
        if isinstance(result, list):
            log.info("%s: %s jobs", source, len(result))
            all_jobs.extend(result)
        else:
            log.error("%s failed: %s", source, result)

    url_deduped_count = len(
        {
            str(job.get("url") or job.get("id") or "").strip()
            for job in all_jobs
            if str(job.get("url") or job.get("id") or "").strip()
        }
    )
    deduped_jobs = _deduplicate_jobs(all_jobs)

    log.info("Total fetched jobs: %s", len(all_jobs))
    log.info("After URL dedup: %s jobs", url_deduped_count)
    log.info("After title+company dedup: %s jobs", len(deduped_jobs))
    new_jobs = filter_new_jobs(deduped_jobs)
    seen_jobs = len(deduped_jobs) - len(new_jobs)
    log.info("New jobs (not seen before): %s", len(new_jobs))

    new_jobs = filter_fresh_jobs(new_jobs, max_days=MAX_JOB_AGE_DAYS)
    log.info("Fresh new jobs to score: %s", len(new_jobs))

    if not new_jobs:
        log.info("No new jobs today - skipping score + email")
        _export_dashboard()
        return []

    scoring_candidates = _shortlist_jobs(new_jobs)
    log.info("Shortlisted new jobs for scoring: %s of %s", len(scoring_candidates), len(new_jobs))

    try:
        scored_jobs = await score_jobs(scoring_candidates, profile=MY_PROFILE)
    except Exception as exc:
        log.error("Scoring failed: %s", exc)
        scored_jobs = []
    update_scores(scored_jobs)
    log.info("Total jobs after scoring filter: %s", len(scored_jobs))

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    render_html(scored_jobs, generated_at)
    log.info("Rendered HTML digest: %s", OUTPUT_PATH)

    try:
        send_digest(scored_jobs, str(OUTPUT_PATH))
    except Exception as exc:
        log.error("Email send failed: %s", exc)
    _export_dashboard()
    log.info("Pipeline complete: %s new jobs scored, %s already seen (skipped)", len(scored_jobs), seen_jobs)

    return scored_jobs


def main() -> None:
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
