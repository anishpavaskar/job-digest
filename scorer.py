"""Anthropic Haiku job scoring."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any

from anthropic import AsyncAnthropic

from config import ANTHROPIC_API_KEY, MIN_SCORE

MODEL_NAME = "claude-haiku-4-5-20251001"
MAX_CONCURRENCY = 5
MAX_DESCRIPTION_CHARS = 800
MAX_TOKENS = 300
MAX_REQUESTS_PER_MINUTE = 40
MAX_RATE_LIMIT_RETRIES = 3

Profile = dict[str, Any]
Job = dict[str, Any]

SYSTEM_PROMPT = """You are a job-fit scorer. Score this job for the candidate.
Return ONLY a JSON object, no other text:
{
  "score": <int 0-100>,
  "reasons": ["<reason 1>", "<reason 2>", "<reason 3>"],
  "title_match": <int 0-100>,
  "skills_match": <int 0-100>,
  "level_match": <int 0-100>,
  "domain_fit": <int 0-100>,
  "location_fit": <int 0-100>
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
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
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
        f"Description (first 800 chars): {description}\n"
    )


async def _score_single_job(
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    rate_limiter: AnthropicRateLimiter,
    job: Job,
    profile: Profile,
) -> Job:
    async with semaphore:
        parsed = _default_score_payload()
        job_label = job.get("id") or job.get("url") or "job"

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
                is_rate_limited = status_code == 429 or "rate_limit_error" in str(exc)
                if is_rate_limited and attempt < MAX_RATE_LIMIT_RETRIES:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                print(f"Scoring failed for {job_label}: {exc}")
                break

    return _attach_score(job, parsed)


async def score_jobs(jobs: list[Job], profile: Profile) -> list[Job]:
    if not jobs:
        return []

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    rate_limiter = AnthropicRateLimiter(
        max_requests=MAX_REQUESTS_PER_MINUTE,
        window_seconds=60.0,
    )
    scored_jobs = await asyncio.gather(
        *(_score_single_job(client, semaphore, rate_limiter, job, profile) for job in jobs)
    )

    filtered_jobs = [job for job in scored_jobs if job.get("score", 0) >= MIN_SCORE]
    return sorted(filtered_jobs, key=lambda item: item["score"], reverse=True)
