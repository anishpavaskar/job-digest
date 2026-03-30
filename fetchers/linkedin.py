"""Best-effort LinkedIn scraper that fails soft when blocked."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup

LINKEDIN_JOBS_URL = (
    "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&location=Remote&f_TPR=r86400"
)
REQUEST_TIMEOUT = httpx.Timeout(20.0)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
RELATIVE_TIME_PATTERN = re.compile(r"(?P<count>\d+)\+?\s*(?P<unit>minute|hour|day|week|month|year)s?", re.IGNORECASE)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _job_id_from_url(url: str) -> str:
    view_match = re.search(r"/view/(\d+)", url)
    if view_match:
        return view_match.group(1)
    query = parse_qs(urlparse(url).query)
    if query.get("currentJobId"):
        return query["currentJobId"][0]
    return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-") or "listing"


def _normalize_posted_at(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date().isoformat()
    except ValueError:
        pass

    lowered = text.lower().replace("ago", "").strip()
    now = datetime.now(timezone.utc)
    if lowered in {"today", "just now", "now"}:
        return now.date().isoformat()
    if lowered == "yesterday":
        return (now - timedelta(days=1)).date().isoformat()

    match = RELATIVE_TIME_PATTERN.search(lowered)
    if not match:
        return ""

    count = int(match.group("count"))
    unit = match.group("unit").lower()
    day_count = {
        "minute": 0,
        "hour": 0,
        "day": count,
        "week": count * 7,
        "month": count * 30,
        "year": count * 365,
    }[unit]
    return (now - timedelta(days=day_count)).date().isoformat()


def _blocked_response(response: httpx.Response) -> bool:
    text = response.text.lower()
    return response.status_code != 200 or any(
        marker in text
        for marker in (
            "sign in to view more jobs",
            "security verification",
            "captcha",
            "let's do a quick security check",
        )
    )


def _extract_json_ld_jobs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = _clean_text(script.string or script.get_text())
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue

            url = _clean_text(item.get("url"))
            title = _clean_text(item.get("title"))
            if not url or not title:
                continue

            org = item.get("hiringOrganization") or {}
            location_data = item.get("jobLocation") or {}
            if isinstance(location_data, list):
                location_data = location_data[0] if location_data else {}
            address = location_data.get("address") if isinstance(location_data, dict) else {}
            location = ", ".join(
                part for part in [_clean_text(address.get("addressLocality")), _clean_text(address.get("addressRegion"))] if part
            )

            jobs.append(
                {
                    "id": f"linkedin:{_job_id_from_url(url)}",
                    "title": title,
                    "company": _clean_text(org.get("name")),
                    "location": location,
                    "url": url,
                    "description": "",
                    "source": "linkedin",
                    "posted_at": _normalize_posted_at(item.get("datePosted")),
                }
            )
    return jobs


def _extract_html_jobs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    cards = soup.select("div.base-search-card, li div.base-card, li")
    for card in cards:
        link = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        title_el = card.select_one("h3.base-search-card__title, h3.base-card__title, h3")
        company_el = card.select_one("h4.base-search-card__subtitle, h4.base-card__subtitle, h4 a, h4")
        location_el = card.select_one(
            "span.job-search-card__location, span.base-search-card__metadata, .job-search-card__location"
        )
        time_el = card.select_one("time")

        url = _clean_text(link.get("href")) if link else ""
        title = _clean_text(title_el.get_text(" ", strip=True)) if title_el else ""
        company = _clean_text(company_el.get_text(" ", strip=True)) if company_el else ""
        location = _clean_text(location_el.get_text(" ", strip=True)) if location_el else ""
        posted_at = _clean_text(time_el.get("datetime") or time_el.get_text(" ", strip=True)) if time_el else ""

        if not url or not title:
            continue

        url = urljoin(LINKEDIN_JOBS_URL, url)
        jobs.append(
            {
                "id": f"linkedin:{_job_id_from_url(url)}",
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "description": "",
                "source": "linkedin",
                "posted_at": _normalize_posted_at(posted_at),
            }
        )
    return jobs


async def fetch_linkedin_jobs() -> list[dict[str, Any]]:
    headers = {"user-agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers) as client:
        response = await client.get(LINKEDIN_JOBS_URL)

    if _blocked_response(response):
        print("LinkedIn blocked the request; returning no jobs.")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    jobs = _extract_json_ld_jobs(soup) + _extract_html_jobs(soup)
    unique_jobs: dict[str, dict[str, Any]] = {}
    for job in jobs:
        unique_jobs[job["id"]] = job

    if not unique_jobs:
        print("LinkedIn returned no parseable jobs; returning no jobs.")
    return list(unique_jobs.values())
