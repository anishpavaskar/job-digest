"""Playwright fetcher for Lever and Ashby job boards."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from anthropic import AsyncAnthropic

from config import ANTHROPIC_API_KEY, ASHBY_COMPANIES, LEVER_COMPANIES
from logging_config import get_logger

EXTRACT_PROMPT = """
Parse this job board page. Extract all engineering job listings.

Return ONLY a JSON array. Each item must have:
{
  "title": "job title",
  "company": "company name",
  "location": "city or Remote",
  "url": "full https:// apply link",
  "description": "first 300 chars or empty string"
}

Include only: engineering, backend, platform, infra, SRE, DevOps, ML/AI.
Exclude: sales, marketing, HR, finance, legal, design.
If no relevant jobs: return []
Return ONLY valid JSON array. No markdown fences.
""".strip()
SCRAPE_CONCURRENCY = 5
EXTRACTION_CONCURRENCY = 4
_SCRAPE_SEMAPHORE = asyncio.Semaphore(SCRAPE_CONCURRENCY)
_EXTRACTION_SEMAPHORE = asyncio.Semaphore(EXTRACTION_CONCURRENCY)
ENGINEERING_TERMS = (
    "engineer",
    "engineering",
    "developer",
    "software",
    "fullstack",
    "full stack",
    "platform",
    "backend",
    "infrastructure",
    "infra",
    "sre",
    "devops",
    "site reliability",
    "machine learning",
    "ml engineer",
    "ai engineer",
    "data engineer",
)
log = get_logger("playwright")
_EXTRACTION_DISABLED_REASON: str | None = None


def _anthropic_client() -> AsyncAnthropic | None:
    if not ANTHROPIC_API_KEY:
        return None
    return AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


async def _scrape_page(url: str) -> tuple[str, str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("playwright not installed — skipping")
        return "", ""

    async with _SCRAPE_SEMAPHORE:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                content = await page.inner_text("body")
                html = await page.content()
                return content[:5000], html
            finally:
                await browser.close()


def _extract_json_array(raw_text: str) -> list[dict[str, Any]]:
    cleaned = raw_text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        if len(parts) > 1:
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end == -1 or end <= start:
            log.warning("Extraction returned invalid JSON: %s", cleaned[:100].replace("\n", " "))
            return []
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            log.warning("Extraction returned invalid JSON snippet: %s", cleaned[:100].replace("\n", " "))
            return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _is_relevant_title(title: str) -> bool:
    lowered = title.lower()
    return any(term in lowered for term in ENGINEERING_TERMS)


def _extract_lever_jobs_from_html(html: str, company: str) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, str]] = []
    for card in soup.select("a.posting-title"):
        url = str(card.get("href", "") or "").strip()
        title_node = card.select_one("[data-qa='posting-name']")
        title = title_node.get_text(" ", strip=True) if title_node else card.get_text(" ", strip=True)
        if not url or not title or not _is_relevant_title(title):
            continue

        location_node = card.select_one(".location")
        location = location_node.get_text(" ", strip=True) if location_node else "Remote"
        description = card.get_text(" ", strip=True)[:300]
        jobs.append(
            {
                "id": f"lever:{company}:{url[-40:]}",
                "title": title.strip(),
                "company": company,
                "location": location.strip() or "Remote",
                "url": url,
                "description": description,
                "source": "lever",
                "posted_at": "",
            }
        )
    return jobs


async def _extract_jobs(content: str, company: str, source: str) -> list[dict[str, str]]:
    global _EXTRACTION_DISABLED_REASON

    if not content or len(content) < 50:
        return []
    if _EXTRACTION_DISABLED_REASON:
        return []

    anthropic = _anthropic_client()
    if anthropic is None:
        _EXTRACTION_DISABLED_REASON = "ANTHROPIC_API_KEY not set"
        log.warning("%s — skipping AI extraction for remaining Playwright boards", _EXTRACTION_DISABLED_REASON)
        return []

    try:
        async with _EXTRACTION_SEMAPHORE:
            response = await anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                timeout=60,
                system=EXTRACT_PROMPT,
                messages=[{"role": "user", "content": f"Company: {company}\n\n{content}"}],
            )
        text = "".join(getattr(block, "text", "") for block in getattr(response, "content", []))
        jobs = _extract_json_array(text)
        normalized: list[dict[str, str]] = []
        for job in jobs:
            url = str(job.get("url", "") or "").strip()
            if not url:
                continue
            normalized.append(
                {
                    "id": f"{source}:{company}:{url[-40:]}",
                    "title": str(job.get("title", "") or "").strip(),
                    "company": str(job.get("company", company) or company).strip(),
                    "location": str(job.get("location", "Remote") or "Remote").strip(),
                    "url": url,
                    "description": str(job.get("description", "") or "").strip(),
                    "source": source,
                    "posted_at": "",
                }
            )
        return normalized
    except Exception as exc:
        message = str(exc)
        if "credit balance is too low" in message.lower():
            _EXTRACTION_DISABLED_REASON = "Anthropic credits unavailable"
            log.warning("%s — disabling AI extraction for remaining Playwright boards", _EXTRACTION_DISABLED_REASON)
        else:
            log.warning("Extraction failed for %s: %s", company, exc)
        return []


async def _fetch_one(url: str, company: str, source: str) -> list[dict[str, str]]:
    try:
        content, html = await _scrape_page(url)
        if source == "lever":
            jobs = _extract_lever_jobs_from_html(html, company)
            if jobs:
                log.info("%s/%s: %s jobs", source, company, len(jobs))
                return jobs
        jobs = await _extract_jobs(content, company, source)
        log.info("%s/%s: %s jobs", source, company, len(jobs))
        return jobs
    except Exception as exc:
        log.warning("%s/%s error: %s", source, company, exc)
        return []


async def fetch_lever_jobs(companies: list[str] | None = None) -> list[dict[str, str]]:
    if companies is None:
        companies = LEVER_COMPANIES
    results = await asyncio.gather(
        *[_fetch_one(f"https://jobs.lever.co/{company}", company, "lever") for company in companies],
        return_exceptions=True,
    )
    return [job for result in results if isinstance(result, list) for job in result]


async def fetch_ashby_jobs(companies: list[str] | None = None) -> list[dict[str, str]]:
    if companies is None:
        companies = ASHBY_COMPANIES
    results = await asyncio.gather(
        *[_fetch_one(f"https://jobs.ashbyhq.com/{company}", company, "ashby") for company in companies],
        return_exceptions=True,
    )
    return [job for result in results if isinstance(result, list) for job in result]
