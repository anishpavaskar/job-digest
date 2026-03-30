# job-digest — Prompt 9 (Final): Steel.dev Fetcher
> Replaces Unified.to and OpenClaw entirely.
> Run after Prompt 8 (tests) is complete.

---

## Why Steel

Steel is a hosted headless browser API with a free tier (100 hrs/month).
It has a /scrape endpoint that returns cleaned markdown from any URL.
No sessions needed for read-only job board scraping.
Works on Railway with zero infrastructure setup.

Lever, Ashby, and LinkedIn are all public pages — Steel just browses them
and returns the content. You then pass that markdown to Haiku to extract jobs.

---

## Setup

Install:
  pip install steel-sdk --break-system-packages

Add to requirements.txt:
  steel-sdk

Add to .env.example:
  STEEL_API_KEY=      # get free key at app.steel.dev

---

## Add to config.py

```python
LEVER_COMPANIES = [
    "notion", "plaid", "scale", "figma",
    "checkr", "benchling", "superhuman",
]

ASHBY_COMPANIES = [
    "linear", "ramp", "retool", "mercury",
    "cursor", "hex", "coda", "replit",
]

LINKEDIN_QUERIES = [
    "backend engineer remote",
    "platform engineer remote",
    "infrastructure engineer remote",
    "ML infrastructure engineer",
]
```

---

## Build fetchers/steel_scraper.py

```python
"""
Steel.dev fetcher for Lever, Ashby, and LinkedIn.
Uses Steel /scrape endpoint to get page markdown, then Haiku to extract jobs.
Never crashes the pipeline — returns [] on any failure.
"""

import os
import asyncio
import json
import httpx
from anthropic import AsyncAnthropic

STEEL_API_KEY    = os.getenv("STEEL_API_KEY")
ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY")
STEEL_SCRAPE_URL = "https://api.steel.dev/v1/scrape"

anthropic = AsyncAnthropic(api_key=ANTHROPIC_KEY)

# ── Steel scrape ────────────────────────────────────────────────

async def _scrape_url(url: str) -> str:
    """
    Call Steel /scrape and return cleaned markdown.
    Returns empty string on failure.
    """
    if not STEEL_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                STEEL_SCRAPE_URL,
                headers={
                    "Steel-Api-Key": STEEL_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "format": ["markdown"],
                    "useProxy": True,
                }
            )
            res.raise_for_status()
            data = res.json()
            return data.get("content", {}).get("markdown", "")
    except Exception as e:
        print(f"  [steel] scrape failed for {url}: {e}")
        return ""


# ── Haiku extraction ────────────────────────────────────────────

EXTRACT_PROMPT = """
You are parsing a job board page. Extract all engineering job listings.

Return ONLY a JSON array. Each item must have exactly these fields:
{
  "title": "job title",
  "company": "company name",
  "location": "location or Remote",
  "url": "full https:// apply URL",
  "description": "first 400 chars of description, or empty string"
}

Rules:
- Only include: engineering, infrastructure, platform, SRE, DevOps, ML/AI roles
- Skip: sales, marketing, HR, finance, legal, design, operations
- If no apply URL found, skip the job
- If no relevant jobs found, return []
- Return ONLY the JSON array, no markdown, no explanation
"""

async def _extract_jobs(markdown: str, company: str, source: str) -> list[dict]:
    """Pass markdown to Haiku and extract structured jobs."""
    if not markdown or len(markdown) < 100:
        return []
    try:
        res = await anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=EXTRACT_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Company: {company}\n\nPage content:\n{markdown[:4000]}"
            }]
        )
        text = res.content[0].text.strip()
        # strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        jobs = json.loads(text)
        if not isinstance(jobs, list):
            return []
        # normalize to standard schema
        normalized = []
        for j in jobs:
            if not j.get("url"):
                continue
            normalized.append({
                "id":          f"{source}:{company}:{j['url'][-40:]}",
                "title":       str(j.get("title", "")).strip(),
                "company":     str(j.get("company", company)).strip(),
                "location":    str(j.get("location", "Remote")).strip(),
                "url":         str(j.get("url", "")).strip(),
                "description": str(j.get("description", "")).strip(),
                "source":      source,
                "posted_at":   "",
            })
        return normalized
    except (json.JSONDecodeError, Exception) as e:
        print(f"  [steel] extraction failed for {company}: {e}")
        return []


# ── Public fetcher functions ────────────────────────────────────

async def _fetch_one(url: str, company: str, source: str) -> list[dict]:
    markdown = await _scrape_url(url)
    jobs = await _extract_jobs(markdown, company, source)
    print(f"  [steel/{source}] {company}: {len(jobs)} jobs")
    return jobs


async def fetch_lever_jobs(companies: list[str]) -> list[dict]:
    if not STEEL_API_KEY:
        print("  [steel/lever] STEEL_API_KEY not set — skipping")
        return []
    tasks = [
        _fetch_one(
            url=f"https://jobs.lever.co/{company}",
            company=company,
            source="lever",
        )
        for company in companies
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    jobs = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
    return jobs


async def fetch_ashby_jobs(companies: list[str]) -> list[dict]:
    if not STEEL_API_KEY:
        print("  [steel/ashby] STEEL_API_KEY not set — skipping")
        return []
    tasks = [
        _fetch_one(
            url=f"https://jobs.ashby.com/{company}",
            company=company,
            source="ashby",
        )
        for company in companies
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    jobs = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
    return jobs


async def fetch_linkedin_jobs(queries: list[str]) -> list[dict]:
    """
    LinkedIn best-effort — may get blocked.
    Uses 24hr filter (f_TPR=r86400) and remote filter (f_WT=2).
    """
    if not STEEL_API_KEY:
        print("  [steel/linkedin] STEEL_API_KEY not set — skipping")
        return []

    base = (
        "https://www.linkedin.com/jobs/search/"
        "?keywords={q}&location=Remote&f_TPR=r86400&f_WT=2"
    )
    tasks = [
        _fetch_one(
            url=base.format(q=q.replace(" ", "%20")),
            company="linkedin",
            source="linkedin",
        )
        for q in queries
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # deduplicate by URL
    seen, jobs = set(), []
    for r in results:
        if isinstance(r, list):
            for j in r:
                if j["url"] not in seen:
                    seen.add(j["url"])
                    jobs.append(j)
    print(f"  [steel/linkedin] {len(jobs)} unique jobs total")
    return jobs
```

---

## Wire into main.py

```python
# Remove any old linkedin/unified/openclaw imports

from fetchers.steel_scraper import (
    fetch_lever_jobs,
    fetch_ashby_jobs,
    fetch_linkedin_jobs,
)
from config import LEVER_COMPANIES, ASHBY_COMPANIES, LINKEDIN_QUERIES

# In run_pipeline(), update asyncio.gather:
results = await asyncio.gather(
    fetch_greenhouse_jobs(GREENHOUSE_COMPANIES),
    fetch_yc(),
    fetch_prospect(),
    fetch_lever_jobs(LEVER_COMPANIES),
    fetch_ashby_jobs(ASHBY_COMPANIES),
    fetch_linkedin_jobs(LINKEDIN_QUERIES),
    return_exceptions=True
)
```

---

## Update companies.txt

Remove from companies.txt (now in config.py LEVER/ASHBY lists):
  notion, plaid, scale, figma, linear, ramp, retool,
  mercury, cursor, hex, replit, coda

Add comment at top:
  # GREENHOUSE companies only — direct public API, no auth needed
  # Lever  → config.py LEVER_COMPANIES  (fetched via Steel.dev)
  # Ashby  → config.py ASHBY_COMPANIES  (fetched via Steel.dev)
  # LinkedIn → config.py LINKEDIN_QUERIES (fetched via Steel.dev)

---

## Add to .env (Railway)

In Railway dashboard, add:
  STEEL_API_KEY=your_key_from_app_steel_dev

---

## Add tests to tests/test_fetchers.py

```python
def test_lever_skips_gracefully_without_api_key(monkeypatch):
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    jobs = asyncio.run(fetch_lever_jobs(["notion"]))
    assert jobs == []

def test_ashby_skips_gracefully_without_api_key(monkeypatch):
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    jobs = asyncio.run(fetch_ashby_jobs(["linear"]))
    assert jobs == []

def test_linkedin_skips_gracefully_without_api_key(monkeypatch):
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    jobs = asyncio.run(fetch_linkedin_jobs(["backend engineer"]))
    assert jobs == []

def test_extracted_jobs_pass_schema(sample_jobs):
    # re-use existing schema validation
    for job in sample_jobs:
        errors = validate_job(job)
        assert errors == [], f"Schema errors: {errors}"

@pytest.mark.slow
async def test_lever_notion_live():
    jobs = await fetch_lever_jobs(["notion"])
    assert isinstance(jobs, list)
    if jobs:  # may be empty if notion has no eng roles
        assert all(j["source"] == "lever" for j in jobs)
        assert all(j["url"].startswith("https://") for j in jobs)

@pytest.mark.slow
async def test_ashby_linear_live():
    jobs = await fetch_ashby_jobs(["linear"])
    assert isinstance(jobs, list)

@pytest.mark.slow
async def test_linkedin_does_not_crash():
    # passes even if linkedin blocks
    jobs = await fetch_linkedin_jobs(["backend engineer remote"])
    assert isinstance(jobs, list)
```

---

## Verify

Run fast tests:
  pytest -m "not slow" -v

Run full pipeline:
  python main.py

Expected log:
  [greenhouse] anthropic: 12 jobs
  [steel/lever] notion: 5 jobs
  [steel/lever] plaid: 3 jobs
  [steel/ashby] linear: 8 jobs
  [steel/ashby] ramp: 4 jobs
  [steel/linkedin] 14 unique jobs total
  Scoring 142 jobs with Haiku...
  Pipeline complete — 31 jobs in digest

Check output/digest.html includes jobs from lever/ashby/linkedin sources.
```