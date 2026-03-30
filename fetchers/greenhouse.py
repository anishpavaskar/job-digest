"""Greenhouse public API fetcher with detail hydration."""

from __future__ import annotations

import asyncio
from html import unescape
from typing import Any

import httpx
from bs4 import BeautifulSoup

GREENHOUSE_LIST_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
GREENHOUSE_DETAIL_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
DETAIL_CONCURRENCY = 10
REQUEST_TIMEOUT = httpx.Timeout(20.0)


def _location_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _posted_at(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _description_text(value: Any) -> str:
    if not value:
        return ""
    html = unescape(str(value))
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def _normalize_job(
    slug: str,
    company_name: str,
    job_id: str,
    list_job: dict[str, Any],
    detail_job: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = detail_job or {}
    return {
        "id": f"greenhouse:{slug}:{job_id}",
        "title": str(payload.get("title") or list_job.get("title") or "").strip(),
        "company": company_name,
        "location": _location_name(payload.get("location") or list_job.get("location")),
        "url": str(payload.get("absolute_url") or list_job.get("absolute_url") or "").strip(),
        "description": _description_text(payload.get("content") or list_job.get("content")),
        "source": "greenhouse",
        "posted_at": _posted_at(payload.get("updated_at") or list_job.get("updated_at")),
    }


async def _fetch_job_detail(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    slug: str,
    company_name: str,
    list_job: dict[str, Any],
) -> dict[str, Any] | None:
    job_id = str(list_job.get("id") or "").strip()
    if not job_id:
        return None

    detail_job: dict[str, Any] | None = None
    try:
        async with semaphore:
            response = await client.get(GREENHOUSE_DETAIL_URL.format(slug=slug, job_id=job_id))
        if response.status_code == 200:
            detail_job = response.json()
        else:
            print(f"Greenhouse detail fetch failed for {slug}:{job_id} ({response.status_code})")
    except httpx.HTTPError as exc:
        print(f"Greenhouse detail fetch failed for {slug}:{job_id}: {exc}")

    return _normalize_job(slug, company_name, job_id, list_job, detail_job)


async def _fetch_company_jobs(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    company: dict[str, str],
) -> list[dict[str, Any]]:
    slug = company["slug"]
    company_name = company["name"]

    try:
        response = await client.get(GREENHOUSE_LIST_URL.format(slug=slug))
    except httpx.HTTPError as exc:
        print(f"Greenhouse list fetch failed for {slug}: {exc}")
        return []

    if response.status_code == 404:
        print(f"Greenhouse board unavailable for {slug}; skipping.")
        return []
    if response.status_code != 200:
        print(f"Greenhouse list fetch failed for {slug} ({response.status_code})")
        return []

    jobs = response.json().get("jobs", [])
    results = await asyncio.gather(
        *(_fetch_job_detail(client, semaphore, slug, company_name, job) for job in jobs),
        return_exceptions=True,
    )

    normalized_jobs: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            print(f"Greenhouse job hydration failed for {slug}: {result}")
            continue
        if result:
            normalized_jobs.append(result)
    return normalized_jobs


async def fetch_greenhouse_jobs(companies: list[dict[str, str]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(_fetch_company_jobs(client, semaphore, company) for company in companies),
            return_exceptions=True,
        )

    jobs: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            print(f"Greenhouse company fetch failed: {result}")
            continue
        jobs.extend(result)
    return jobs
