"""Anthropic Haiku job scoring."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import date
from typing import Any

from anthropic import AsyncAnthropic

from config import ANTHROPIC_API_KEY, MIN_SCORE, SCORING_WEIGHTS
from logging_config import get_logger

MODEL_NAME = "claude-haiku-4-5-20251001"
MAX_CONCURRENCY = 5
MAX_DESCRIPTION_CHARS = 800
MAX_TOKENS = 300
MAX_REQUESTS_PER_MINUTE = 40
MAX_RATE_LIMIT_RETRIES = 3
PENALTY_KEYWORDS = (
    "frontend",
    "front-end",
    "mobile",
    "android",
    "ios",
    "sales",
    "marketing",
    "qa",
    "quality assurance",
    "test automation",
    "sdet",
)
LEVEL_CAP_KEYWORDS = (
    "6+ years",
    "7+ years",
    "8+ years",
    "9+ years",
    "10+ years",
    "5+ years",
)
CORE_SKILLS = [
    "Python",
    "Go",
    "TypeScript",
    "Kubernetes",
    "Docker",
    "AWS",
    "PostgreSQL",
    "Terraform",
    "CI/CD",
    "gRPC",
    "FastAPI",
]
TARGET_ROLES = [
    "Backend Engineer",
    "Platform Engineer",
    "Infrastructure Engineer",
    "SRE",
    "DevOps",
    "ML Infrastructure",
    "Data Engineering",
]
log = get_logger("scorer")

Profile = dict[str, Any]
Job = dict[str, Any]
ScoringState = dict[str, str | bool]

SYSTEM_PROMPT = """You are a strict job-fit scorer for Anish Pavaskar.

Target roles:
- Backend Engineer
- Platform Engineer
- Infrastructure Engineer
- SRE
- DevOps
- ML Infrastructure
- Data Engineering

Core skills to match:
- Python
- Go
- TypeScript
- Kubernetes
- Docker
- AWS
- PostgreSQL
- Terraform
- CI/CD
- gRPC
- FastAPI

Penalties:
- Score below 40 for frontend roles, mobile roles, sales, marketing, QA/testing only roles, or roles requiring 5+ years.
- If posted_at is available and the job is older than 7 days, reduce score by 10 points.

Return exactly this JSON object and nothing else:
{
  "score": 0,
  "reasons": ["reason 1", "reason 2", "reason 3"],
  "title_match": 0,
  "skills_match": 0,
  "level_match": 0,
  "domain_fit": 0,
  "location_fit": 0
}"""


class AnthropicRateLimiter:
    """Simple sliding-window limiter to avoid API burst failures."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()

    async def wait_for_slot(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self._window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return

                sleep_for = self._window_seconds - (now - self._timestamps[0])

            await asyncio.sleep(max(sleep_for, 0.05))


def _default_score_payload() -> dict[str, Any]:
    return {
        "score": 0,
        "reasons": [],
        "title_match": 0,
        "skills_match": 0,
        "level_match": 0,
        "domain_fit": 0,
        "location_fit": 0,
    }


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", "")
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        log.warning("Invalid scoring JSON: %s", cleaned[:100])

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        log.warning("Invalid scoring JSON snippet: %s", cleaned[:100])
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_score(value: Any) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def _normalize_reasons(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = [str(item).strip() for item in value if str(item).strip()]
    return reasons[:3]


def _attach_score(job: Job, payload: dict[str, Any]) -> Job:
    reasons = _normalize_reasons(payload.get("reasons"))
    enriched = dict(job)
    enriched["score"] = _coerce_score(payload.get("score"))
    enriched["reasons"] = reasons
    enriched["title_match"] = _coerce_score(payload.get("title_match"))
    enriched["skills_match"] = _coerce_score(payload.get("skills_match"))
    enriched["level_match"] = _coerce_score(payload.get("level_match"))
    enriched["domain_fit"] = _coerce_score(payload.get("domain_fit"))
    enriched["location_fit"] = _coerce_score(payload.get("location_fit"))
    enriched["rationale"] = " | ".join(reasons)
    return enriched


def _build_user_prompt(job: Job, profile: Profile) -> str:
    description = str(job.get("description", "") or "")[:MAX_DESCRIPTION_CHARS]
    return (
        "CANDIDATE PROFILE:\n"
        f"{json.dumps(profile, indent=2)}\n\n"
        "JOB:\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Posted At: {job.get('posted_at', '')}\n"
        f"Description (first 800 chars): {description}\n"
    )


def _text_blob(job: Job) -> str:
    return " ".join(
        [
            str(job.get("title", "") or ""),
            str(job.get("company", "") or ""),
            str(job.get("location", "") or ""),
            str(job.get("description", "") or ""),
        ]
    ).lower()


def _score_ratio(matches: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round((matches / total) * 100)))


def _posted_is_older_than(posted_at: Any, days: int) -> bool:
    value = str(posted_at or "").strip()
    if not value:
        return False

    try:
        posted_date = date.fromisoformat(value[:10])
    except ValueError:
        return False
    return (date.today() - posted_date).days > days


def _heuristic_payload(job: Job, profile: Profile) -> dict[str, Any]:
    haystack = _text_blob(job)
    title = str(job.get("title", "") or "").lower()
    target_roles = list(profile.get("target_roles", [])) + ["ML Infrastructure", "Data Engineering"]
    all_skills = list(profile.get("skills_tier1", [])) + list(profile.get("skills_tier2", []))
    preferred_domains = list(profile.get("preferred_domains", []))
    preferred_locations = [str(item).lower() for item in profile.get("preferred_locations", [])]

    title_matches = sum(1 for role in target_roles if role.lower() in title or role.lower() in haystack)
    title_match = _score_ratio(title_matches, len(target_roles))

    skills_matches = sum(1 for skill in all_skills if skill.lower() in haystack)
    skills_match = _score_ratio(skills_matches, len(all_skills))

    level_match = 60
    if any(level.lower() in haystack for level in profile.get("target_levels", [])):
        level_match = 95
    elif any(term in haystack for term in ("senior", "staff", "swe ii", "swe iii", "l4", "l5")):
        level_match = 85
    elif any(term in haystack for term in ("principal", "director", "manager")):
        level_match = 30

    domain_matches = sum(1 for domain in preferred_domains if domain.lower() in haystack)
    domain_fit = _score_ratio(domain_matches, len(preferred_domains))
    if domain_fit == 0 and any(keyword in haystack for keyword in ("ai", "ml", "infra", "developer tools", "fintech", "data")):
        domain_fit = 60

    location_text = str(job.get("location", "") or "").lower()
    location_fit = 20
    if "remote" in location_text:
        location_fit = 100
    elif any(location in location_text for location in preferred_locations):
        location_fit = 90
    elif profile.get("open_to_relocation"):
        location_fit = 70

    weighted_score = round(
        title_match * SCORING_WEIGHTS["title_match"]
        + skills_match * SCORING_WEIGHTS["skills_match"]
        + level_match * SCORING_WEIGHTS["level_match"]
        + domain_fit * SCORING_WEIGHTS["domain_fit"]
        + location_fit * SCORING_WEIGHTS["location_fit"]
    )

    reasons: list[str] = []
    if title_match >= 70:
        reasons.append("Title aligns with backend/platform/infrastructure targets")
    if skills_matches >= 3:
        reasons.append("Strong overlap with Anish's backend and infra stack")
    if location_fit >= 90:
        reasons.append("Location matches remote or preferred hubs")
    if domain_fit >= 60:
        reasons.append("Domain fits preferred infrastructure or fintech/AI themes")

    if any(keyword in haystack for keyword in PENALTY_KEYWORDS):
        weighted_score = min(weighted_score, 35)
        reasons = ["Role is outside target backend/platform scope"]
        title_match = min(title_match, 35)
        skills_match = min(skills_match, 35)
    if any(keyword in haystack for keyword in LEVEL_CAP_KEYWORDS):
        weighted_score = min(weighted_score, 39)
        level_match = min(level_match, 35)
        reasons = ["Role appears to require 5+ years of experience"]
    if _posted_is_older_than(job.get("posted_at"), 7):
        weighted_score = max(weighted_score - 10, 0)
        reasons.append("Posting is older than 7 days")

    if not reasons:
        reasons.append("Partial fit based on title and skill overlap")

    return {
        "score": max(0, min(100, weighted_score)),
        "reasons": reasons[:3],
        "title_match": max(0, min(100, title_match)),
        "skills_match": max(0, min(100, skills_match)),
        "level_match": max(0, min(100, level_match)),
        "domain_fit": max(0, min(100, domain_fit)),
        "location_fit": max(0, min(100, location_fit)),
    }


async def _score_single_job(
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    rate_limiter: AnthropicRateLimiter,
    job: Job,
    profile: Profile,
    scoring_state: ScoringState,
) -> Job:
    async with semaphore:
        parsed = _default_score_payload()
        job_label = job.get("id") or job.get("url") or "job"
        if scoring_state.get("disabled"):
            parsed = _heuristic_payload(job, profile)
            return _attach_score(job, parsed)

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                await rate_limiter.wait_for_slot()
                response = await client.messages.create(
                    model=MODEL_NAME,
                    max_tokens=MAX_TOKENS,
                    temperature=0,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": _build_user_prompt(job, profile)}],
                )
                parsed = _extract_json_object(_extract_text(response)) or _default_score_payload()
                break
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                message = str(exc)
                is_rate_limited = status_code == 429 or "rate_limit_error" in str(exc)
                if is_rate_limited and attempt < MAX_RATE_LIMIT_RETRIES:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue

                if "credit balance is too low" in message.lower():
                    if not scoring_state.get("disabled"):
                        scoring_state["disabled"] = True
                        log.warning("Anthropic credits unavailable; switching remaining jobs to heuristic scoring")
                    parsed = _heuristic_payload(job, profile)
                    break

                parsed = _heuristic_payload(job, profile)
                log.warning("Scoring failed for %s; using heuristic fallback: %s", job_label, exc)
                break

    return _attach_score(job, parsed)


async def score_jobs(jobs: list[Job], profile: Profile) -> list[Job]:
    if not jobs:
        return []

    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY is not configured; using heuristic scoring")
        scored_jobs = [_attach_score(job, _heuristic_payload(job, profile)) for job in jobs]
        filtered_jobs = [job for job in scored_jobs if job.get("score", 0) >= MIN_SCORE]
        ordered = sorted(filtered_jobs, key=lambda item: item["score"], reverse=True)
        log.info("Scored %s jobs (filtered %s below threshold)", len(scored_jobs), len(scored_jobs) - len(ordered))
        return ordered

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    rate_limiter = AnthropicRateLimiter(
        max_requests=MAX_REQUESTS_PER_MINUTE,
        window_seconds=60.0,
    )
    scoring_state: ScoringState = {"disabled": False}
    scored_jobs = await asyncio.gather(
        *(_score_single_job(client, semaphore, rate_limiter, job, profile, scoring_state) for job in jobs)
    )

    filtered_jobs = [job for job in scored_jobs if job.get("score", 0) >= MIN_SCORE]
    ordered = sorted(filtered_jobs, key=lambda item: item["score"], reverse=True)
    log.info("Scored %s jobs (filtered %s below threshold)", len(scored_jobs), len(scored_jobs) - len(ordered))
    return ordered
