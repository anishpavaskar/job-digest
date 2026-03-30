# job-digest

Twice-daily job digest — finds, scores, and emails top engineering
roles from Greenhouse, YC, Prospect, Indeed, LinkedIn, Lever, and Ashby.

## Setup

### 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

### 2. Gmail auth (one-time)
python setup_gmail_auth.py

### 3. LinkedIn MCP auth (one-time)
uvx patchright install chromium
uvx linkedin-scraper-mcp --login

### 4. Configure
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, GMAIL_FROM, GMAIL_TO

### 5. Run manually
python main.py

### 6. Schedule (7am + 5pm daily)
launchctl load ~/Library/LaunchAgents/com.anish.job-digest.plist

## CLI

python cli.py stats              # funnel overview
python cli.py list --status new  # new jobs
python cli.py apply <url>        # mark applied
python cli.py skip <url>         # not interested
python cli.py search "anthropic" # search by company/title
python cli.py run                # run pipeline now

## Sources

| Source     | Method              |
|------------|---------------------|
| Greenhouse | Direct public API   |
| YC Jobs    | Scraper             |
| Prospect   | Scraper             |
| Indeed     | JobSpy              |
| ZipRecruiter | JobSpy            |
| Google Jobs | JobSpy             |
| LinkedIn   | JobSpy + MCP server |
| Lever      | Playwright          |
| Ashby      | Playwright          |

## Tech stack
Python, Haiku (scoring), Playwright, JobSpy, SQLite, Gmail API, launchd
