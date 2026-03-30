"""Entrypoint for the job digest pipeline."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
from typing import Any

from config import GREENHOUSE_COMPANIES, MY_PROFILE
from emailer import send_digest
from fetchers import (
    fetch_greenhouse_jobs,
    fetch_linkedin_jobs,
    fetch_prospect_jobs,
    fetch_unified_jobs,
    fetch_yc_jobs,
)
from renderer import OUTPUT_PATH, render_html
from scorer import score_jobs

Job = dict[str, Any]
MAX_SCORING_JOBS = 100
HEURISTIC_ROLE_TERMS = ("engineer", "engineering", "developer", "platform", "backend", "infrastructure", "sre", "devops")


def _log(message: str) -> None:
    print(message)


def _flatten_results(results: list[Any]) -> list[Job]:
    jobs: list[Job] = []
    for result in results:
        if isinstance(result, Exception):
            _log(f"Fetcher failed: {result}")
            continue
        jobs.extend(result)
    return jobs


def _deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        key = str(job.get("url") or job.get("id") or "").strip()
        if not key:
            continue
        unique_jobs[key] = job
    return list(unique_jobs.values())


def _source_counts(jobs: list[Job]) -> str:
    counts = Counter(job.get("source") or "unknown" for job in jobs)
    if not counts:
        return "none"
    return ", ".join(f"{source}={counts[source]}" for source in sorted(counts))


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


async def run_pipeline() -> list[Job]:
    _log(f"Starting job digest pipeline — {datetime.now()}")

    results = await asyncio.gather(
        fetch_greenhouse_jobs(GREENHOUSE_COMPANIES),
        fetch_yc_jobs(),
        fetch_prospect_jobs(),
        fetch_linkedin_jobs(),
        fetch_unified_jobs(),
        return_exceptions=True,
    )

    fetched_jobs = _flatten_results(list(results))
    deduped_jobs = _deduplicate_jobs(fetched_jobs)

    _log(f"Total jobs fetched per source — {_source_counts(deduped_jobs)}")
    scoring_candidates = _shortlist_jobs(deduped_jobs)
    _log(f"Shortlisted jobs for scoring — {len(scoring_candidates)} of {len(deduped_jobs)}")

    try:
        scored_jobs = await score_jobs(scoring_candidates, profile=MY_PROFILE)
    except Exception as exc:
        _log(f"Scoring failed — {exc}")
        scored_jobs = []
    _log(f"Total jobs after scoring filter — {len(scored_jobs)}")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    render_html(scored_jobs, generated_at)
    _log(f"Rendered HTML digest — {OUTPUT_PATH}")

    try:
        send_digest(scored_jobs, str(OUTPUT_PATH))
    except Exception as exc:
        _log(f"Email send failed — {exc}")
    _log(f"Pipeline complete — {len(scored_jobs)} jobs in digest")

    return scored_jobs


def main() -> None:
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
