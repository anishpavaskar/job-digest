"""Unified.to ATS fetcher for Lever and Ashby-backed companies."""

from __future__ import annotations

import asyncio
from typing import Any

from config import UNIFIED_API_KEY, UNIFIED_ASHBY_CONN_ID, UNIFIED_LEVER_CONN_ID

LEVER_COMPANIES = {
    "Notion": lambda: UNIFIED_LEVER_CONN_ID,
    "Plaid": lambda: UNIFIED_LEVER_CONN_ID,
    "Scale AI": lambda: UNIFIED_LEVER_CONN_ID,
}

ASHBY_COMPANIES = {
    "Linear": lambda: UNIFIED_ASHBY_CONN_ID,
    "Ramp": lambda: UNIFIED_ASHBY_CONN_ID,
    "Retool": lambda: UNIFIED_ASHBY_CONN_ID,
    "Mercury": lambda: UNIFIED_ASHBY_CONN_ID,
    "Cursor": lambda: UNIFIED_ASHBY_CONN_ID,
}


def _location_from_job(job: Any) -> str:
    addresses = getattr(job, "addresses", None) or []
    if addresses:
        address = addresses[0]
        location_parts = [
            str(getattr(address, "city", "") or "").strip(),
            str(getattr(address, "region", "") or "").strip(),
            str(getattr(address, "country", "") or "").strip(),
        ]
        location = ", ".join(part for part in location_parts if part)
        if location:
            return location
    if getattr(job, "remote", False):
        return "Remote"
    return ""


def _apply_url_from_job(job: Any) -> str:
    public_job_urls = getattr(job, "public_job_urls", None) or []
    if public_job_urls:
        return str(public_job_urls[0] or "").strip()
    return ""


def _normalize_job(company_name: str, job: Any) -> dict[str, str]:
    job_id = str(getattr(job, "id", "") or "").strip()
    return {
        "id": f"unified:{company_name.lower().replace(' ', '-')}:{job_id or 'unknown'}",
        "title": str(getattr(job, "name", "") or "").strip(),
        "company": company_name,
        "location": _location_from_job(job),
        "url": _apply_url_from_job(job),
        "description": str(getattr(job, "description", "") or "").strip(),
        "source": "unified",
        "posted_at": str(getattr(job, "created_at", "") or "").strip(),
    }


def _configured_companies() -> dict[str, str]:
    configured: dict[str, str] = {}
    for company_name, resolver in {**LEVER_COMPANIES, **ASHBY_COMPANIES}.items():
        connection_id = str(resolver() or "").strip()
        if connection_id:
            configured[company_name] = connection_id
    return configured


def _fetch_unified_jobs_sync() -> list[dict[str, str]]:
    try:
        from unified_python_sdk import UnifiedTo
        from unified_python_sdk.models import operations, shared
    except ImportError:
        print("  [unified] Unified SDK not installed — skipping")
        return []

    if not UNIFIED_API_KEY:
        print("  [unified] UNIFIED_API_KEY not set — skipping")
        return []

    companies = _configured_companies()
    if not companies:
        print("  [unified] No Unified connection IDs configured — skipping")
        return []

    all_jobs: list[dict[str, str]] = []
    with UnifiedTo(security=shared.Security(jwt=UNIFIED_API_KEY)) as sdk:
        for company_name, connection_id in companies.items():
            try:
                response = sdk.ats.list_ats_jobs(
                    request=operations.ListAtsJobsRequest(
                        connection_id=connection_id,
                        limit=100,
                    )
                )
                for job in getattr(response, "ats_jobs", None) or []:
                    all_jobs.append(_normalize_job(company_name, job))
            except Exception as exc:
                print(f"  [unified] Failed for {company_name}: {exc}")
                continue

    print(f"  [unified] Fetched {len(all_jobs)} jobs from Lever/Ashby")
    return all_jobs


async def fetch_unified_jobs() -> list[dict[str, str]]:
    """Fetch jobs from Unified.to without crashing the pipeline."""

    return await asyncio.to_thread(_fetch_unified_jobs_sync)
