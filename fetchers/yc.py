"""YC jobs board fetcher with JSON-first parsing and HTML fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

YC_JOBS_URL = "https://www.ycombinator.com/jobs"
REQUEST_TIMEOUT = httpx.Timeout(20.0)
ENGINEERING_KEYWORDS = (
    "engineer",
    "engineering",
    "developer",
    "backend",
    "platform",
    "infrastructure",
    "devops",
    "sre",
    "site reliability",
    "full stack",
    "full-stack",
    "software",
    "data",
    "ml",
    "machine learning",
)
RELATIVE_TIME_PATTERN = re.compile(r"(?P<count>\d+)\+?\s*(?P<unit>minute|hour|day|week|month|year)s?", re.IGNORECASE)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_clean_text(item) for item in value if _clean_text(item))
    return re.sub(r"\s+", " ", str(value)).strip()


def _as_company_name(value: Any) -> str:
    if isinstance(value, dict):
        return _clean_text(
            value.get("name")
            or value.get("companyName")
            or value.get("title")
            or value.get("slug")
        )
    return _clean_text(value)


def _is_engineering_role(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in ENGINEERING_KEYWORDS)


def _job_id_from_url(url: str, fallback: str) -> str:
    match = re.search(r"/jobs/([^/?#]+)", url)
    if match:
        return match.group(1)
    return fallback


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


def _extract_candidate_from_mapping(node: dict[str, Any]) -> dict[str, Any] | None:
    title = _clean_text(
        node.get("title")
        or node.get("role")
        or node.get("jobTitle")
        or node.get("headline")
    )
    listing_url = _clean_text(
        node.get("url")
        or node.get("jobUrl")
        or node.get("job_url")
        or node.get("href")
    )
    apply_url = _clean_text(node.get("applyUrl") or node.get("apply_url"))
    url = apply_url or listing_url
    company = _as_company_name(
        node.get("company")
        or node.get("companyName")
        or node.get("company_name")
        or node.get("startup")
    )
    location = _clean_text(node.get("location") or node.get("locations") or node.get("jobLocation"))
    description = _clean_text(
        node.get("description")
        or node.get("summary")
        or node.get("excerpt")
        or node.get("blurb")
        or node.get("oneLiner")
    )
    posted_at = _clean_text(
        node.get("postedAt")
        or node.get("createdAt")
        or node.get("publishedAt")
        or node.get("datePosted")
    )

    if not title or not url or not _is_engineering_role(title):
        return None

    url = urljoin(YC_JOBS_URL, url)
    if not company:
        slug_match = re.search(r"/companies/([^/]+)/jobs/", listing_url or url)
        if slug_match:
            company = slug_match.group(1).replace("-", " ").title()
    fallback_id = re.sub(r"[^a-z0-9]+", "-", f"{company}-{title}".lower()).strip("-") or "job"
    return {
        "id": f"yc:{company or 'unknown'}:{_job_id_from_url(url, fallback_id)}",
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": description,
        "source": "yc",
        "posted_at": _normalize_posted_at(posted_at),
    }


def _walk_json(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        candidate = _extract_candidate_from_mapping(node)
        if candidate:
            yield candidate
        for value in node.values():
            yield from _walk_json(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_json(item)


def _extract_jobs_from_scripts(soup: BeautifulSoup) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw or raw[0] not in "[{":
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        jobs.extend(_walk_json(payload))
    return jobs


def _extract_embedded_job_postings(html: str) -> list[dict[str, Any]]:
    text = unescape(html)
    marker = '"jobPostings":'
    marker_index = text.find(marker)
    if marker_index == -1:
        return []

    start = text.find("[", marker_index)
    if start == -1:
        return []

    depth = 0
    in_string = False
    escaping = False
    end = -1

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaping:
                escaping = False
            elif char == "\\":
                escaping = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break

    if end == -1:
        return []

    try:
        payload = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _extract_jobs_from_html(soup: BeautifulSoup) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for link in soup.select("a[href*='/companies/'][href*='/jobs/'], a[href*='/jobs/']"):
        href = _clean_text(link.get("href"))
        title = _clean_text(link.get_text(" ", strip=True))
        if not href or not title or not _is_engineering_role(title):
            continue

        url = urljoin(YC_JOBS_URL, href)
        container = link.find_parent(["article", "li", "div"])
        container_text = _clean_text(container.get_text(" ", strip=True)) if container else ""

        company = ""
        company_match = re.search(r"^(.*?)\s+(?:is hiring|hiring|looking for)", container_text, re.IGNORECASE)
        if company_match:
            company = _clean_text(company_match.group(1))
        if not company:
            slug_match = re.search(r"/companies/([^/]+)/jobs/", url)
            if slug_match:
                company = slug_match.group(1).replace("-", " ").title()

        fallback_id = re.sub(r"[^a-z0-9]+", "-", f"{company}-{title}".lower()).strip("-") or "job"
        jobs.append(
            {
                "id": f"yc:{company or 'unknown'}:{_job_id_from_url(url, fallback_id)}",
                "title": title,
                "company": company,
                "location": "",
                "url": url,
                "description": container_text,
                "source": "yc",
                "posted_at": "",
            }
        )
    return jobs


async def fetch_yc_jobs() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(YC_JOBS_URL)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    embedded_jobs = [_extract_candidate_from_mapping(item) for item in _extract_embedded_job_postings(response.text)]
    candidates = embedded_jobs + _extract_jobs_from_scripts(soup) + _extract_jobs_from_html(soup)

    unique_jobs: dict[str, dict[str, Any]] = {}
    for job in candidates:
        if not job:
            continue
        unique_jobs[job["url"]] = job
    return list(unique_jobs.values())
