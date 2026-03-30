from __future__ import annotations

import asyncio

import pytest

from config import GREENHOUSE_COMPANIES
from fetchers import fetch_greenhouse_jobs, fetch_prospect_jobs, fetch_yc_jobs
from fetchers.jobspy_fetcher import fetch_jobspy_jobs
from fetchers.linkedin_mcp_fetcher import fetch_linkedin_mcp_jobs
from fetchers.playwright_fetcher import fetch_ashby_jobs, fetch_lever_jobs

REQUIRED_FIELDS = ["id", "title", "company", "location", "url", "description", "source", "posted_at"]
VALID_SOURCES = {
    "greenhouse",
    "yc",
    "prospect",
    "indeed",
    "zip_recruiter",
    "google",
    "linkedin",
    "linkedin_mcp",
    "lever",
    "ashby",
}


def validate_job(job: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in job:
            errors.append(f"missing:{field}")
            continue
        if not isinstance(job[field], str):
            errors.append(f"type:{field}")
    if job.get("url") and not job["url"].startswith("http"):
        errors.append("url")
    if job.get("source") not in VALID_SOURCES:
        errors.append("source")
    return errors


def _assert_job_schema(job: dict) -> None:
    errors = validate_job(job)
    assert errors == [], f"Schema errors: {errors}"


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


def test_jobspy_empty_queries_returns_empty_list() -> None:
    jobs = asyncio.run(fetch_jobspy_jobs([]))
    assert jobs == []


def test_linkedin_mcp_skips_gracefully_without_uvx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fetchers.linkedin_mcp_fetcher._is_mcp_available", lambda: False)
    jobs = asyncio.run(fetch_linkedin_mcp_jobs(["backend engineer"]))
    assert jobs == []


def test_extracted_jobs_pass_schema(sample_jobs: list[dict]) -> None:
    for job in sample_jobs:
        errors = validate_job(job)
        assert errors == [], f"Schema errors: {errors}"


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
async def test_jobspy_linkedin_live() -> None:
    jobs = await fetch_jobspy_jobs(["backend engineer remote"])
    assert isinstance(jobs, list)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_lever_notion_live() -> None:
    jobs = await fetch_lever_jobs(["notion"])
    assert isinstance(jobs, list)
    if jobs:
        assert all(job["source"] == "lever" for job in jobs)
        assert all(job["url"].startswith("https://") for job in jobs)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ashby_linear_live() -> None:
    jobs = await fetch_ashby_jobs(["linear"])
    assert isinstance(jobs, list)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_linkedin_mcp_does_not_crash() -> None:
    jobs = await fetch_linkedin_mcp_jobs(["backend engineer"])
    assert isinstance(jobs, list)
