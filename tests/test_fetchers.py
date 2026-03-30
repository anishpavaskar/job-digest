from __future__ import annotations

import pytest

from config import GREENHOUSE_COMPANIES
from fetchers import fetch_greenhouse_jobs, fetch_prospect_jobs, fetch_unified_jobs, fetch_yc_jobs

REQUIRED_FIELDS = ["id", "title", "company", "location", "url", "description", "source", "posted_at"]
VALID_SOURCES = {"greenhouse", "yc", "prospect", "linkedin", "unified"}


def _assert_job_schema(job: dict) -> None:
    for field in REQUIRED_FIELDS:
        assert field in job
        assert isinstance(job[field], str)
    if job["url"]:
        assert job["url"].startswith("http")
    assert job["source"] in VALID_SOURCES


def test_job_schema_all_fields_present(sample_jobs: list[dict]) -> None:
    for job in sample_jobs:
        for field in REQUIRED_FIELDS:
            assert field in job


def test_job_schema_all_fields_are_strings(sample_jobs: list[dict]) -> None:
    for job in sample_jobs:
        for field in REQUIRED_FIELDS:
            assert isinstance(job[field], str)


def test_job_url_format(sample_jobs: list[dict]) -> None:
    for job in sample_jobs:
        if job["url"]:
            assert job["url"].startswith("http")


def test_job_id_is_unique(sample_jobs: list[dict]) -> None:
    job_ids = [job["id"] for job in sample_jobs]
    assert len(job_ids) == len(set(job_ids))


def test_job_source_is_valid(sample_jobs: list[dict]) -> None:
    for job in sample_jobs:
        assert job["source"] in VALID_SOURCES


@pytest.mark.slow
@pytest.mark.asyncio
async def test_greenhouse_returns_jobs() -> None:
    jobs = await fetch_greenhouse_jobs(GREENHOUSE_COMPANIES[:2])
    assert len(jobs) > 0
    for job in jobs:
        _assert_job_schema(job)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_yc_returns_jobs() -> None:
    jobs = await fetch_yc_jobs()
    assert len(jobs) > 0
    for job in jobs:
        _assert_job_schema(job)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_prospect_returns_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    jobs = await fetch_prospect_jobs()
    if jobs:
        for job in jobs:
            _assert_job_schema(job)
        return

    captured = capsys.readouterr()
    combined = f"{captured.out}\n{captured.err}".lower()
    assert "prospect" in combined
    assert "returning no jobs" in combined or "failed" in combined or "warning" in combined


@pytest.mark.slow
@pytest.mark.asyncio
async def test_unified_returns_jobs_or_skips_gracefully() -> None:
    jobs = await fetch_unified_jobs()
    if not jobs:
        assert jobs == []
        return

    for job in jobs:
        _assert_job_schema(job)
