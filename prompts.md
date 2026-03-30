# job-digest — Claude Code Build Prompts
> Run these in order in Claude Code. Each prompt assumes the previous is complete.

---

## Prompt 0: Project Scaffold

```
Create a new Python project called `job-digest` at ~/job-digest/.

Structure:
```
job-digest/
├── main.py                  # entrypoint — runs full pipeline
├── config.py                # profile, company list, weights
├── fetchers/
│   ├── __init__.py
│   ├── greenhouse.py        # Greenhouse public API
│   ├── yc.py               # YC jobs board
│   ├── prospect.py         # joinprospect.com scraper
│   └── linkedin.py         # LinkedIn (best-effort scrape)
├── scorer.py               # Haiku scoring, async, parallel
├── renderer.py             # HTML page generator
├── emailer.py              # Gmail API sender
├── scheduler.py            # APScheduler cron (twice daily)
├── requirements.txt
└── .env.example
```

Install dependencies:
- httpx (async HTTP)
- anthropic (Haiku scoring)
- apscheduler (cron)
- google-auth, google-auth-oauthlib, google-api-python-client (Gmail)
- beautifulsoup4 (scraping)
- jinja2 (HTML templating)
- python-dotenv

Create requirements.txt and install all deps.

Create .env.example with:
ANTHROPIC_API_KEY=
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_FROM=
GMAIL_TO=
```

---

## Prompt 1: Config + Profile

```
In config.py, define:

1. MY_PROFILE dict:
   - name: "Anish Pavaskar"
   - title: "Software Engineer II"
   - years_experience: 3
   - skills_tier1: ["Python", "Go", "TypeScript", "Kubernetes", "Docker", "Terraform", "AWS"]
   - skills_tier2: ["Helm", "CI/CD", "PostgreSQL", "Redis", "gRPC", "FastAPI"]
   - target_roles: ["Backend Engineer", "Platform Engineer", "Infrastructure Engineer", "SRE", "DevOps"]
   - target_levels: ["L4", "L5", "SWE II", "SWE III", "Staff", "Senior"]
   - preferred_domains: ["AI/ML infra", "developer tools", "fintech", "defense tech", "data infrastructure"]
   - open_to_relocation: True
   - preferred_locations: ["Remote", "San Francisco", "Bay Area", "New York", "Seattle"]

2. GREENHOUSE_COMPANIES list of dicts { slug, name }:
   Include: anthropic, anduril, brex, figma, notion, ramp, scale, stripe, vercel,
   rippling, plaid, chime, databricks, openai, cohere, mistral, modal, 
   replit, linear, retool, mercury, watershed, hex, dbt-labs

3. SCORING_WEIGHTS dict:
   - title_match: 0.30
   - skills_match: 0.25
   - level_match: 0.20
   - domain_fit: 0.15
   - location_fit: 0.10

4. TOP_N_EMAIL = 8  (jobs to include in email)
5. MIN_SCORE = 55   (minimum score to include in HTML page)
```

---

## Prompt 2: Fetchers

```
Build all 4 fetchers. Each must return a list of dicts conforming to this normalized schema:

{
  "id": str,           # unique — source:company:job_id
  "title": str,
  "company": str,
  "location": str,
  "url": str,          # direct apply link
  "description": str,  # full JD text, as much as available
  "source": str,       # "greenhouse" | "yc" | "prospect" | "linkedin"
  "posted_at": str,    # ISO date string or empty string
}

--- fetchers/greenhouse.py ---
Use the public Greenhouse API (no auth needed):
  List: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
  Detail: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}

IMPORTANT: The list endpoint returns jobs with empty `content`. Always fetch the 
individual job detail endpoint to get full description. This is critical for scoring.

Use httpx async. Fetch all companies from GREENHOUSE_COMPANIES in config.py concurrently.
For each company, fetch job list, then fetch each job's detail concurrently (semaphore 
limit: 10 concurrent requests to avoid rate limiting).

--- fetchers/yc.py ---
Fetch from: https://www.ycombinator.com/jobs
Parse the JSON embedded in the page or use their API if available.
Filter to engineering roles only.

--- fetchers/prospect.py ---
Scrape https://www.joinprospect.com/explore
Use BeautifulSoup. Paginate through all pages (url pattern: ?ef34f5f2_page=N).
Extract company name, role title, and apply URL. Description may be minimal — that's ok.

--- fetchers/linkedin.py ---
Best-effort only. Scrape:
https://www.linkedin.com/jobs/search/?keywords=backend+engineer&location=Remote&f_TPR=r86400
Extract job title, company, location, URL.
If blocked, return empty list and log a warning — do not crash the pipeline.

All fetchers should be async functions. main.py will await them all concurrently.
```

---

## Prompt 3: Haiku Scorer

```
Build scorer.py with async parallel scoring using Claude Haiku.

Function signature:
  async def score_jobs(jobs: list[dict], profile: dict) -> list[dict]

For each job, call Claude Haiku (claude-haiku-4-5-20251001) with this prompt structure:

System:
  You are a job-fit scorer. Score this job for the candidate. 
  Return ONLY a JSON object, no other text:
  {
    "score": <int 0-100>,
    "reasons": ["<reason 1>", "<reason 2>", "<reason 3>"],
    "title_match": <int 0-100>,
    "skills_match": <int 0-100>,
    "level_match": <int 0-100>,
    "domain_fit": <int 0-100>,
    "location_fit": <int 0-100>
  }

User:
  CANDIDATE PROFILE:
  {json.dumps(profile, indent=2)}

  JOB:
  Title: {job['title']}
  Company: {job['company']}
  Location: {job['location']}
  Description (first 800 chars): {job['description'][:800]}

Rules:
- Run ALL jobs concurrently using asyncio.gather with a semaphore of 20
- Parse JSON response safely — if parsing fails, assign score: 0
- Attach score fields back onto the job dict
- Sort results by score descending
- Filter out jobs with score < MIN_SCORE from config.py
- Return sorted, filtered list

Use ANTHROPIC_API_KEY from env. Use the anthropic AsyncAnthropic client.
```

---

## Prompt 4: HTML Renderer

```
Build renderer.py that generates a clean, striking single-page HTML report.

Function signature:
  def render_html(jobs: list[dict], generated_at: str) -> str

Design brief — IMPORTANT, follow this exactly:
- Pure black background (#000000)
- Pure white text (#FFFFFF)  
- Monospace font throughout (use "JetBrains Mono" from Google Fonts)
- No colors except black, white, and one accent: a dim gray (#333333) for borders/dividers
- Score displayed as a large number, right-aligned, slightly transparent
- Each job is a row: SCORE | TITLE — COMPANY | LOCATION | [APPLY →]
- Jobs sorted by score descending
- A small header: "JOB DIGEST" in large caps, with generated timestamp below it
- Footer: total jobs scanned, sources breakdown
- Completely static HTML — no JS, no frameworks
- Must look like a Bloomberg terminal crossed with a hacker news clone
- Compact — each job is ONE line, not a card
- The [APPLY →] is a direct link

The HTML should be self-contained (inline CSS, no external deps except the Google Font).

Save the rendered HTML to ~/job-digest/output/digest.html (create dir if needed).
Return the HTML string.
```

---

## Prompt 5: Gmail Emailer

```
Build emailer.py to send the top N jobs via Gmail API.

Function signature:
  def send_digest(jobs: list[dict], html_page_path: str) -> None

Setup:
- Use OAuth2 credentials from GMAIL_CREDENTIALS_PATH in env
- Store token in ~/job-digest/token.json (auto-refresh)
- Scope: https://www.googleapis.com/auth/gmail.send

Email format:
- Subject: "Job Digest — {date} — {len(jobs)} matches"
- Body is HTML email
- Show top TOP_N_EMAIL jobs from config.py
- Each job: score badge | role title | company | location | APPLY link
- Same black/white aesthetic as the HTML page but email-safe (inline styles, table layout)
- Bottom of email: "View full digest →" linking to the hosted HTML page URL
  (read DIGEST_URL from env, or omit the link if not set)

Also write a setup_gmail_auth.py script that handles the one-time OAuth flow and saves token.json.
```

---

## Prompt 6: Main Pipeline + Scheduler

```
Build main.py and scheduler.py.

--- main.py ---
async def run_pipeline():
  1. Log "Starting job digest pipeline — {datetime.now()}"
  2. Fetch all sources concurrently:
     results = await asyncio.gather(
       fetch_greenhouse(GREENHOUSE_COMPANIES),
       fetch_yc(),
       fetch_prospect(),
       fetch_linkedin(),
       return_exceptions=True
     )
  3. Flatten results, skip any exceptions (log them)
  4. Deduplicate by job URL
  5. Log total jobs fetched per source
  6. Score all jobs with Haiku
  7. Log total jobs after scoring filter
  8. Render HTML → save to output/digest.html
  9. Send email with top TOP_N_EMAIL jobs
  10. Log "Pipeline complete — {len(scored_jobs)} jobs in digest"

if __name__ == "__main__":
  asyncio.run(run_pipeline())

--- scheduler.py ---
Use APScheduler to run run_pipeline() twice daily:
- 7:00 AM Pacific
- 5:00 PM Pacific

if __name__ == "__main__":
  scheduler starts, logs next run times, blocks forever

--- .env additions needed ---
Add to .env.example:
DIGEST_URL=           # optional: URL where digest.html is hosted
TZ=America/Los_Angeles
```

---

## Prompt 7: Deployment to Railway

```
Set up Railway deployment for the scheduler.

1. Create Procfile:
   worker: python scheduler.py

2. Create railway.json:
   {
     "build": { "builder": "NIXPACKS" },
     "deploy": { "startCommand": "python scheduler.py", "restartPolicyType": "ON_FAILURE" }
   }

3. Create a README.md with:
   - One-time setup steps (Gmail OAuth, env vars)
   - How to run locally: python main.py
   - How to deploy to Railway
   - List of env vars required

4. Verify the full pipeline runs locally end-to-end:
   python main.py

   Fix any import errors, missing env vars, or API failures.
   The pipeline should complete without crashing.

5. List all env vars that need to be set in Railway dashboard.
```