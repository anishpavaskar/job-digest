"""Best-effort Prospect company explorer scraper."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

PROSPECT_EXPLORE_URL = "https://www.joinprospect.com/explore"
PAGE_PARAM = "ef34f5f2_page"
MAX_PAGES = 20
DETAIL_CONCURRENCY = 10
REQUEST_TIMEOUT = httpx.Timeout(20.0)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _slug_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    return slug.removesuffix("-stock")


def _humanize_slug(slug: str) -> str:
    return slug.replace("-", " ").title()


def _extract_company_links(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, dict[str, str]] = {}
    for anchor in soup.select("a[href^='/explore/']"):
        href = _clean_text(anchor.get("href"))
        if not href or not href.endswith("-stock"):
            continue
        detail_url = urljoin(PROSPECT_EXPLORE_URL, href)
        links[detail_url] = {
            "detail_url": detail_url,
            "slug": _slug_from_url(detail_url),
            "summary": _clean_text(anchor.get_text(" ", strip=True)),
        }
    return list(links.values())


def _extract_section_text(soup: BeautifulSoup, heading_text: str) -> str:
    heading = soup.find(lambda tag: tag.name in {"h2", "h3"} and _clean_text(tag.get_text()) == heading_text)
    if not heading:
        return ""

    parts: list[str] = []
    for sibling in heading.next_siblings:
        name = getattr(sibling, "name", None)
        if name in {"h1", "h2", "h3"}:
            break
        if hasattr(sibling, "get_text"):
            text = _clean_text(sibling.get_text(" ", strip=True))
        else:
            text = _clean_text(sibling)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_labeled_value(soup: BeautifulSoup, label: str) -> str:
    strings = [_clean_text(text) for text in soup.stripped_strings]
    for index, text in enumerate(strings):
        if text == label and index > 0:
            return strings[index - 1]
    return ""


def _extract_career_url(soup: BeautifulSoup, detail_url: str) -> str:
    for anchor in soup.find_all("a", href=True):
        href = _clean_text(anchor["href"])
        if not href:
            continue
        full_url = urljoin(detail_url, href)
        lowered = full_url.lower()
        anchor_text = _clean_text(anchor.get_text(" ", strip=True)).lower()
        if "joinprospect.com" in lowered or "equity.joinprospect.com" in lowered:
            continue
        has_career_url = any(
            token in lowered
            for token in (
                "/career",
                "/careers",
                "/job",
                "/jobs",
                "/open-roles",
                "/positions",
                "/join-us",
                "greenhouse.io",
                "lever.co",
                "ashbyhq.com",
                "workatastartup.com",
            )
        )
        has_career_text = any(
            token in anchor_text
            for token in ("career", "careers", "job", "jobs", "apply", "open roles", "we're hiring")
        )
        if has_career_url or has_career_text:
            return full_url
    return ""


async def _fetch_company_entry(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    entry: dict[str, str],
) -> dict[str, Any] | None:
    try:
        async with semaphore:
            response = await client.get(entry["detail_url"])
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Prospect detail fetch failed for {entry['detail_url']}: {exc}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    company_name = _clean_text((soup.find("h1") or soup.find("h2") or "").get_text(" ", strip=True))
    if not company_name:
        company_name = _humanize_slug(entry["slug"])

    description = _extract_section_text(soup, "Company Description") or entry["summary"]
    career_url = _extract_career_url(soup, entry["detail_url"])
    if not career_url:
        return None

    return {
        "id": f"prospect:{entry['slug']}:explore",
        "title": f"Explore roles at {company_name}",
        "company": company_name,
        "location": _extract_labeled_value(soup, "Headquarters"),
        "url": career_url,
        "description": description,
        "source": "prospect",
        "posted_at": "",
    }


async def fetch_prospect_jobs() -> list[dict[str, Any]]:
    discovered: dict[str, dict[str, str]] = {}
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES + 1):
            page_url = PROSPECT_EXPLORE_URL if page == 1 else f"{PROSPECT_EXPLORE_URL}?{PAGE_PARAM}={page}"
            response = await client.get(page_url)
            if response.status_code != 200:
                break

            page_entries = _extract_company_links(response.text)
            new_entries = [entry for entry in page_entries if entry["detail_url"] not in discovered]
            if not new_entries:
                break

            for entry in new_entries:
                discovered[entry["detail_url"]] = entry

        results = await asyncio.gather(
            *(_fetch_company_entry(client, semaphore, entry) for entry in discovered.values()),
            return_exceptions=True,
        )

    jobs: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            print(f"Prospect entry parse failed: {result}")
            continue
        if result:
            jobs.append(result)
    if not jobs:
        print("Prospect returned no actionable role/apply links; returning no jobs.")
    return jobs
