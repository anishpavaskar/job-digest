# job-digest

Automated startup job digest that fetches jobs from multiple sources, scores them with Anthropic Claude Haiku, renders a terminal-style HTML report, and emails the top matches via Gmail.

## One-time setup

1. Create and activate the virtual environment if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create a `.env` file or copy from `.env.example`.

3. Add your environment values:

```env
# --- AI / Scoring ---
ANTHROPIC_API_KEY=

# --- Gmail / Output ---
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_FROM=
GMAIL_TO=
DIGEST_URL=
TZ=America/Los_Angeles

# --- Unified.to ---
UNIFIED_API_KEY=
UNIFIED_LEVER_CONN_ID=
UNIFIED_ASHBY_CONN_ID=
```

4. Put your Google OAuth client file at the path referenced by `GMAIL_CREDENTIALS_PATH`.

5. Run the one-time Gmail auth flow:

```bash
python setup_gmail_auth.py
```

This creates `token.json` in the project root.

## Run locally

Run the full pipeline once:

```bash
python main.py
```

Run the twice-daily scheduler:

```bash
python scheduler.py
```

The HTML digest is written to `output/digest.html`.

## Deploy to Railway

1. Push this project to a Git repository.
2. Create a new Railway project from the repo.
3. Railway will use `railway.json` and the `Procfile` worker entry automatically.
4. In the Railway dashboard, set the required environment variables.
5. Add `credentials.json` and `token.json` through your deployment process or another secure secret/file strategy.

Railway starts the worker with:

```bash
python scheduler.py
```

## Railway dashboard env vars

Set these in Railway:

- `ANTHROPIC_API_KEY`
- `GMAIL_CREDENTIALS_PATH`
- `GMAIL_FROM`
- `GMAIL_TO`
- `TZ`
- `DIGEST_URL`
- `UNIFIED_API_KEY`
- `UNIFIED_LEVER_CONN_ID`
- `UNIFIED_ASHBY_CONN_ID`

## Notes

- Gmail OAuth requires both `credentials.json` and the generated `token.json`.
- The scheduler runs at 7:00 AM and 5:00 PM Pacific.
- LinkedIn and Prospect are best-effort sources and may return zero jobs depending on the live site behavior.
- Unified.to covers Lever and Ashby-backed companies when the Unified env vars are configured.
