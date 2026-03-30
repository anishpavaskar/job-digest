"""Static HTML renderer for the job digest."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = PROJECT_ROOT / "output" / "digest.html"

TEMPLATE = Environment(autoescape=True).from_string(
    """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Job Digest</title>
    <style>
      :root {
        --bg: #000000;
        --fg: #ffffff;
        --border: #333333;
      }

      * {
        box-sizing: border-box;
      }

      html, body {
        margin: 0;
        background: var(--bg);
        color: var(--fg);
        font-family: "JetBrains Mono", "SFMono-Regular", Consolas, Menlo, Monaco, monospace;
      }

      body {
        min-height: 100vh;
        padding: 32px 20px 48px;
      }

      .wrap {
        max-width: 1320px;
        margin: 0 auto;
      }

      .header {
        border-top: 1px solid var(--border);
        border-bottom: 1px solid var(--border);
        padding: 16px 0 14px;
        margin-bottom: 18px;
      }

      .title {
        margin: 0;
        font-size: clamp(2rem, 5vw, 4rem);
        font-weight: 800;
        letter-spacing: 0.28em;
        text-transform: uppercase;
      }

      .timestamp {
        margin-top: 10px;
        color: rgba(255, 255, 255, 0.72);
        font-size: 0.82rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .table {
        border-top: 1px solid var(--border);
        border-bottom: 1px solid var(--border);
      }

      .row {
        display: grid;
        grid-template-columns: 84px minmax(0, 1.9fr) minmax(0, 1fr) 120px;
        gap: 16px;
        align-items: start;
        min-height: 72px;
        padding: 12px 0;
        border-bottom: 1px solid var(--border);
      }

      .row:last-child {
        border-bottom: 0;
      }

      .score {
        text-align: right;
        font-size: 1.5rem;
        font-weight: 800;
        opacity: 0.56;
        white-space: nowrap;
      }

      .role {
        min-width: 0;
      }

      .role-head {
        line-height: 1.45;
      }

      .role-title {
        font-weight: 700;
      }

      .role-company {
        opacity: 0.78;
      }

      .job-url {
        display: block;
        margin-top: 6px;
        color: rgba(255, 255, 255, 0.72);
        font-size: 0.78rem;
        line-height: 1.5;
        text-decoration: underline;
        text-underline-offset: 0.18em;
        overflow-wrap: anywhere;
        user-select: all;
      }

      .location {
        min-width: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        opacity: 0.74;
      }

      .apply {
        justify-self: end;
        color: var(--fg);
        text-decoration: none;
        white-space: nowrap;
      }

      .apply:hover {
        text-decoration: underline;
      }

      .empty {
        padding: 18px 0;
        opacity: 0.7;
      }

      .footer {
        display: flex;
        justify-content: space-between;
        gap: 18px;
        margin-top: 18px;
        padding-top: 14px;
        border-top: 1px solid var(--border);
        font-size: 0.82rem;
        color: rgba(255, 255, 255, 0.72);
        text-transform: uppercase;
      }

      .footer span {
        display: block;
      }

      @media (max-width: 880px) {
        .row {
          grid-template-columns: 72px minmax(0, 1fr);
          gap: 8px 14px;
          padding: 12px 0;
        }

        .location,
        .apply {
          grid-column: 2;
          justify-self: start;
        }

        .apply {
          margin-top: 2px;
        }

        .footer {
          flex-direction: column;
        }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <header class="header">
        <h1 class="title">Job Digest</h1>
        <div class="timestamp">{{ generated_at }}</div>
      </header>

      <main class="table">
        {% if jobs %}
          {% for job in jobs %}
            <article class="row">
              <div class="score">{{ job.score }}</div>
              <div class="role">
                <div class="role-head">
                  <span class="role-title">{{ job.title }}</span>
                  <span class="role-company"> — {{ job.company or "Unknown Company" }}</span>
                </div>
                <a class="job-url" href="{{ job.url }}" target="_blank" rel="noreferrer">{{ job.url }}</a>
              </div>
              <div class="location">{{ job.location or "Location Unknown" }}</div>
              <a class="apply" href="{{ job.url }}" target="_blank" rel="noreferrer">[APPLY →]</a>
            </article>
          {% endfor %}
        {% else %}
          <div class="empty">No jobs matched the current filters.</div>
        {% endif %}
      </main>

      <footer class="footer">
        <span>Total jobs scanned: {{ total_jobs }}</span>
        <span>Sources: {{ source_breakdown }}</span>
      </footer>
    </div>
  </body>
</html>
"""
)


def _sorted_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(jobs, key=lambda item: item.get("score", 0), reverse=True)


def _source_breakdown(jobs: list[dict[str, Any]]) -> str:
    if not jobs:
        return "none"
    counts = Counter((job.get("source") or "unknown") for job in jobs)
    return " | ".join(f"{source}:{counts[source]}" for source in sorted(counts))


def render_html(jobs: list[dict[str, Any]], generated_at: str) -> str:
    ordered_jobs = _sorted_jobs(jobs)
    html = TEMPLATE.render(
        jobs=ordered_jobs,
        generated_at=generated_at,
        total_jobs=len(ordered_jobs),
        source_breakdown=_source_breakdown(ordered_jobs),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    return html


def render_digest_html(jobs: list[dict[str, Any]]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return render_html(jobs, timestamp)
