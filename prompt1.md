# job-digest — Prompt 10 (Final v2): Complete Source Architecture
> Adds linkedin-mcp-server on top of JobSpy for deeper LinkedIn coverage.
> Run after core pipeline (Prompts 1-7) is working.

---

## Final Source Map

| Source          | Method                      | Coverage                         |
|-----------------|-----------------------------|----------------------------------|
| Greenhouse      | Direct API                  | Anthropic, Stripe, Anduril, etc. |
| YC Jobs         | Existing scraper            | 4,000+ YC companies              |
| Prospect        | Existing scraper            | Curated startups                 |
| Indeed          | JobSpy (python-jobspy)      | Massive general coverage         |
| ZipRecruiter    | JobSpy (python-jobspy)      | US remote roles                  |
| Google Jobs     | JobSpy (python-jobspy)      | Aggregated from everywhere       |
| LinkedIn        | JobSpy (best-effort)        | Rate limited, worth trying       |
| LinkedIn (deep) | linkedin-mcp-server         | Your real session, better results|
| Lever companies | Playwright                  | Notion, Plaid, Scale, etc.       |
| Ashby companies | Playwright                  | Linear, Ramp, Retool, etc.       |

---

## Step 1: Install everything

```bash
# JobSpy
pip install python-jobspy playwright --break-system-packages
playwright install chromium

# linkedin-mcp-server (uv required)
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx patchright install chromium

# One-time LinkedIn login (opens browser window)
uvx linkedin-scraper-mcp --login
# Log in manually. Session saved to ~/.linkedin-mcp/profile/
# You only need to do this once — re-run if session expires
```

Add to requirements.txt:
  python-jobspy
  playwright
  mcp

NOTE: linkedin-mcp-server is installed globally via uvx, NOT via pip.
Your Python code communicates with it via subprocess + MCP protocol.

---

## Step 2: Add to config.py

```python
JOBSPY_SEARCHES = [
    "backend engineer remote",
    "platform engineer remote",
    "infrastructure engineer remote",
    "SRE site reliability engineer remote",
    "ML infrastructure engineer remote",
    "DevOps engineer remote",
]

# Separate LinkedIn searches for the MCP server
# These use your real session — more targeted, better results
LINKEDIN_MCP_SEARCHES = [
    "backend engineer",
    "platform engineer",
    "infrastructure engineer",
    "ML infrastructure",
    "SRE devops remote",
]

LEVER_COMPANIES = [
    "notion", "plaid", "scale", "figma",
    "checkr", "benchling", "superhuman",
    "cloudflare", "warpdev",
]

ASHBY_COMPANIES = [
    "linear", "ramp", "retool", "mercury",
    "cursor", "hex", "coda", "replit",
    "loom", "dbtlabs",
]
```

---

## Step 3: Build fetchers/jobspy_fetcher.py

```python
"""
JobSpy fetcher — scrapes Indeed, ZipRecruiter, Google Jobs, LinkedIn
concurrently across all search queries.
Indeed is the most reliable (no rate limiting).
LinkedIn is best-effort here — the MCP server gives better LinkedIn results.
"""

import asyncio
from jobspy import scrape_jobs
from config import JOBSPY_SEARCHES

SITES = ["indeed", "zip_recruiter", "google", "linkedin"]
RESULTS_PER_QUERY = 15
HOURS_OLD = 24


def _normalize(row: dict) -> dict:
    url = str(row.get("job_url", "")).strip()
    city = str(row.get("city", "")).strip()
    state = str(row.get("state", "")).strip()
    location = ", ".join(filter(None, [city, state])) or "Remote"
    return {
        "id":          f"jobspy:{row.get('site', '')}:{url[-40:]}",
        "title":       str(row.get("title", "")).strip(),
        "company":     str(row.get("company", "")).strip(),
        "location":    location,
        "url":         url,
        "description": str(row.get("description", ""))[:600],
        "source":      str(row.get("site", "jobspy")).strip(),
        "posted_at":   str(row.get("date_posted", "")).strip(),
    }


async def _search_one(query: str) -> list[dict]:
    try:
        df = await asyncio.to_thread(
            scrape_jobs,
            site_name=SITES,
            search_term=query,
            location="Remote",
            is_remote=True,
            results_wanted=RESULTS_PER_QUERY,
            hours_old=HOURS_OLD,
            job_type="fulltime",
            description_format="markdown",
            country_indeed="USA",
        )
        if df is None or df.empty:
            return []
        jobs = []
        for _, row in df.iterrows():
            j = _normalize(row.to_dict())
            if j["url"] and j["title"]:
                jobs.append(j)
        print(f"  [jobspy] '{query}': {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"  [jobspy] '{query}' failed: {e}")
        return []


async def fetch_jobspy_jobs(queries: list[str] = None) -> list[dict]:
    if queries is None:
        queries = JOBSPY_SEARCHES
    results = await asyncio.gather(
        *[_search_one(q) for q in queries],
        return_exceptions=True,
    )
    seen, jobs = set(), []
    for r in results:
        if isinstance(r, list):
            for j in r:
                if j["url"] and j["url"] not in seen:
                    seen.add(j["url"])
                    jobs.append(j)
    print(f"  [jobspy] Total unique: {len(jobs)}")
    return jobs
```

---

## Step 4: Build fetchers/linkedin_mcp_fetcher.py

```python
"""
LinkedIn fetcher using stickerdaniel/linkedin-mcp-server.
Uses your real LinkedIn session (Patchright) — much better results
than anonymous scraping. Requires one-time login setup.

Setup:
  uvx patchright install chromium
  uvx linkedin-scraper-mcp --login

Repo: https://github.com/stickerdaniel/linkedin-mcp-server
"""

import asyncio
import json
import subprocess
import os
from config import LINKEDIN_MCP_SEARCHES


def _is_mcp_available() -> bool:
    """Check if uvx and linkedin-scraper-mcp are available."""
    try:
        result = subprocess.run(
            ["uvx", "--version"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _normalize_linkedin_job(job: dict) -> dict:
    """Normalize linkedin-mcp-server job format to our schema."""
    # linkedin-mcp-server returns: title, company, location, url,
    # description, job_id, date_posted
    url = str(job.get("url", job.get("job_url", ""))).strip()
    return {
        "id":          f"linkedin_mcp:{url[-40:]}",
        "title":       str(job.get("title", "")).strip(),
        "company":     str(job.get("company", "")).strip(),
        "location":    str(job.get("location", "Remote")).strip(),
        "url":         url,
        "description": str(job.get("description", ""))[:600],
        "source":      "linkedin_mcp",
        "posted_at":   str(job.get("date_posted", "")).strip(),
    }


async def _call_mcp_search(query: str, location: str = "Remote") -> list[dict]:
    """
    Call the linkedin-mcp-server search_jobs tool via subprocess.

    The server accepts JSON-RPC over stdio. We start it, send a
    tool call, read the response, and shut it down.
    """
    # MCP request payload for search_jobs tool
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_jobs",
            "arguments": {
                "keywords": query,
                "location": location,
                "limit": 20,
            }
        }
    }

    try:
        proc = await asyncio.create_subprocess_exec(
            "uvx", "linkedin-scraper-mcp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send initialization handshake first (required by MCP protocol)
        init_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "job-digest", "version": "1.0"}
            }
        }) + "\n"

        tool_request = json.dumps(request) + "\n"

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(
                input=(init_request + tool_request).encode()
            ),
            timeout=60,  # LinkedIn pages can be slow
        )

        if proc.returncode != 0:
            print(f"  [linkedin_mcp] MCP server error: {stderr.decode()[:100]}")
            return []

        # Parse responses — there will be multiple JSON lines
        jobs = []
        for line in stdout.decode().strip().split("\n"):
            if not line.strip():
                continue
            try:
                response = json.loads(line)
                # Skip the init response (id=0)
                if response.get("id") == 0:
                    continue
                # Extract job results from tool response
                result = response.get("result", {})
                content = result.get("content", [])
                for item in content:
                    if item.get("type") == "text":
                        try:
                            job_data = json.loads(item["text"])
                            if isinstance(job_data, list):
                                jobs.extend(job_data)
                            elif isinstance(job_data, dict):
                                jobs.append(job_data)
                        except json.JSONDecodeError:
                            pass
            except json.JSONDecodeError:
                continue

        print(f"  [linkedin_mcp] '{query}': {len(jobs)} jobs")
        return jobs

    except asyncio.TimeoutError:
        print(f"  [linkedin_mcp] '{query}' timed out")
        return []
    except Exception as e:
        print(f"  [linkedin_mcp] '{query}' error: {e}")
        return []


async def fetch_linkedin_mcp_jobs(searches: list[str] = None) -> list[dict]:
    """
    Fetch LinkedIn jobs using your real session via linkedin-mcp-server.
    Falls back gracefully if the MCP server is not set up.
    """
    if searches is None:
        searches = LINKEDIN_MCP_SEARCHES

    if not _is_mcp_available():
        print("  [linkedin_mcp] uvx not found — skipping")
        print("  [linkedin_mcp] Setup: uvx patchright install chromium && uvx linkedin-scraper-mcp --login")
        return []

    results = await asyncio.gather(
        *[_call_mcp_search(q) for q in searches],
        return_exceptions=True,
    )

    seen, jobs = set(), []
    for r in results:
        if isinstance(r, list):
            for raw_job in r:
                normalized = _normalize_linkedin_job(raw_job)
                if normalized["url"] and normalized["url"] not in seen:
                    seen.add(normalized["url"])
                    jobs.append(normalized)

    print(f"  [linkedin_mcp] Total unique: {len(jobs)}")
    return jobs
```

---

## Step 5: Build fetchers/playwright_fetcher.py

```python
"""
Playwright fetcher for Lever and Ashby job boards.
Simple public pages — no bot detection. Haiku extracts structured data.
"""

import asyncio
import json
from playwright.async_api import async_playwright
from anthropic import AsyncAnthropic
import os
from config import LEVER_COMPANIES, ASHBY_COMPANIES

anthropic = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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
"""


async def _scrape_page(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000, wait_until="networkidle")
            content = await page.inner_text("body")
            await browser.close()
            return content[:5000]
        except Exception as e:
            await browser.close()
            raise e


async def _extract_jobs(content: str, company: str, source: str) -> list[dict]:
    if not content or len(content) < 50:
        return []
    try:
        res = await anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=EXTRACT_PROMPT,
            messages=[{"role": "user", "content": f"Company: {company}\n\n{content}"}]
        )
        text = res.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        jobs = json.loads(text.strip())
        if not isinstance(jobs, list):
            return []
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
    except Exception as e:
        print(f"  [playwright] extraction failed {company}: {e}")
        return []


async def _fetch_one(url: str, company: str, source: str) -> list[dict]:
    try:
        content = await _scrape_page(url)
        jobs = await _extract_jobs(content, company, source)
        print(f"  [playwright/{source}] {company}: {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"  [playwright/{source}] {company} error: {e}")
        return []


async def fetch_lever_jobs(companies: list[str] = None) -> list[dict]:
    if companies is None:
        companies = LEVER_COMPANIES
    results = await asyncio.gather(
        *[_fetch_one(f"https://jobs.lever.co/{c}", c, "lever") for c in companies],
        return_exceptions=True,
    )
    return [j for r in results if isinstance(r, list) for j in r]


async def fetch_ashby_jobs(companies: list[str] = None) -> list[dict]:
    if companies is None:
        companies = ASHBY_COMPANIES
    results = await asyncio.gather(
        *[_fetch_one(f"https://jobs.ashby.com/{c}", c, "ashby") for c in companies],
        return_exceptions=True,
    )
    return [j for r in results if isinstance(r, list) for j in r]
```

---

## Step 6: Update main.py

```python
from fetchers.greenhouse import fetch_greenhouse_jobs
from fetchers.yc import fetch_yc
from fetchers.prospect import fetch_prospect
from fetchers.jobspy_fetcher import fetch_jobspy_jobs
from fetchers.linkedin_mcp_fetcher import fetch_linkedin_mcp_jobs
from fetchers.playwright_fetcher import fetch_lever_jobs, fetch_ashby_jobs
from config import GREENHOUSE_COMPANIES

async def run_pipeline():
    print(f"Starting — {datetime.now()}")

    results = await asyncio.gather(
        fetch_greenhouse_jobs(GREENHOUSE_COMPANIES),
        fetch_yc(),
        fetch_prospect(),
        fetch_jobspy_jobs(),          # Indeed + ZipRecruiter + Google + LinkedIn
        fetch_linkedin_mcp_jobs(),    # LinkedIn via real session (deeper)
        fetch_lever_jobs(),           # Playwright
        fetch_ashby_jobs(),           # Playwright
        return_exceptions=True,
    )

    sources = ["greenhouse", "yc", "prospect", "jobspy",
               "linkedin_mcp", "lever", "ashby"]
    all_jobs = []
    for i, r in enumerate(results):
        if isinstance(r, list):
            print(f"  [{sources[i]}] {len(r)} jobs")
            all_jobs.extend(r)
        else:
            print(f"  [{sources[i]}] ERROR: {r}")

    # deduplicate by URL
    seen, jobs = set(), []
    for j in all_jobs:
        if j["url"] and j["url"] not in seen:
            seen.add(j["url"])
            jobs.append(j)

    print(f"  Total unique before scoring: {len(jobs)}")

    scored = await score_jobs(jobs, MY_PROFILE)
    html = render_html(scored, str(datetime.now()))
    send_digest(scored[:TOP_N_EMAIL], html)
    print(f"Pipeline complete — {len(scored)} jobs in digest")
```

---

## Step 7: One-time LinkedIn MCP setup

Run these once before first pipeline run:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Patchright browser
uvx patchright install chromium

# Login to LinkedIn (opens real browser window)
uvx linkedin-scraper-mcp --login
# Complete login manually — 2FA, captcha etc.
# Session saved to ~/.linkedin-mcp/profile/
# Re-run this command if you get auth errors later
```

Add to .env:
  # No new vars needed for LinkedIn MCP — uses saved profile

---

## Step 8: launchd plist (same as before)

~/Library/LaunchAgents/com.anish.job-digest.plist — 7am + 5pm Pacific.
Make sure load_dotenv() is at the very top of main.py.

---

## Step 9: Verify

```bash
# Test LinkedIn MCP alone first
python -c "
import asyncio
from fetchers.linkedin_mcp_fetcher import fetch_linkedin_mcp_jobs
jobs = asyncio.run(fetch_linkedin_mcp_jobs(['backend engineer']))
print(f'LinkedIn MCP: {len(jobs)} jobs')
if jobs: print(jobs[0])
"

# Run full pipeline
python main.py
```

Expected output:
  [greenhouse] 45 jobs
  [yc] 23 jobs
  [prospect] 18 jobs
  [jobspy] Total unique: 185 jobs
  [linkedin_mcp] 'backend engineer': 18 jobs
  [linkedin_mcp] Total unique: 67 jobs
  [playwright/lever] notion: 4 jobs
  [playwright/ashby] linear: 7 jobs
  Total unique before scoring: 310 jobs
  Pipeline complete — 52 jobs in digest

---

## Step 10: If LinkedIn MCP session expires

Sessions expire periodically. When you see auth errors:
```bash
uvx linkedin-scraper-mcp --login
```
Takes 2 minutes. That's it.
```