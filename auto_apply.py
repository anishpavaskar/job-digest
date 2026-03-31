"""Greenhouse auto-apply helpers."""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

from config import ANTHROPIC_API_KEY, GMAIL_FROM, PHONE, RESUME_PATH
from logging_config import get_logger

load_dotenv(Path(__file__).parent / ".env")

GH_BASE = "https://boards-api.greenhouse.io/v1/boards"
RESUME_FILE = Path(RESUME_PATH).expanduser()
APPLICANT = {
    "first_name": "Anish",
    "last_name": "Pavaskar",
    "email": GMAIL_FROM,
    "phone": PHONE,
    "location": "Milpitas, CA",
    "linkedin_profile": "https://linkedin.com/in/anishpavaskar",
    "github_profile": "https://github.com/anishpavaskar",
    "website": "",
}
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
log = get_logger("auto-apply")

JobDetails = dict[str, Any]


def parse_greenhouse_url(url: str) -> tuple[str | None, str | None]:
    """Return (slug, job_id) for a Greenhouse job URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if "greenhouse.io" not in netloc:
        return None, None

    match = re.search(r"/(?:boards/)?([^/]+)/jobs/(\d+)", parsed.path)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def fetch_job_details(slug: str, job_id: str) -> JobDetails:
    """Fetch Greenhouse job details and application questions."""
    url = f"{GH_BASE}/{slug}/jobs/{job_id}"
    response = httpx.get(url, params={"questions": "true"}, timeout=30)
    response.raise_for_status()
    try:
        data = response.json()
    except json.JSONDecodeError:
        log.error("Invalid Greenhouse job JSON for %s/%s: %s", slug, job_id, response.text[:100])
        return {}
    return data if isinstance(data, dict) else {}


def _fallback_cover_letter(job: JobDetails, company: str) -> str:
    title = str(job.get("title", "the role") or "the role")
    return (
        f"{company}'s {title} role lines up closely with the backend and infrastructure work I enjoy most. "
        "Across three years as a software engineer, I have focused on Python, Go, Kubernetes, Docker, and AWS while "
        "building reliable developer-facing systems.\n\n"
        "I like working on practical infrastructure problems, from platform tooling to service reliability and CI/CD. "
        "This role stands out because it combines strong backend fundamentals with the kind of systems work I want to keep growing in.\n\n"
        "I would be excited to contribute quickly, learn the stack deeply, and help ship dependable products with the team."
    )


def generate_cover_letter(job: JobDetails) -> str:
    """Generate a short tailored cover letter using Haiku."""
    company = str(job.get("company_name", "") or "the company")
    title = str(job.get("title", "") or "the role")
    description = str(job.get("content", "") or "")[:1500]

    if anthropic is None:
        log.warning("ANTHROPIC_API_KEY not set; using fallback cover letter")
        return _fallback_cover_letter(job, company)

    prompt = f"""Write a concise, genuine cover letter for this job.

Job: {title} at {company}
Description: {description}

Candidate profile:
- Name: Anish Pavaskar
- Experience: 3 years, formerly Dell EMC (SWE II)
- Skills: Python, Go, TypeScript, Kubernetes, Docker, AWS, PostgreSQL
- Projects: Recurse (LeetCode diagnostic platform), ATC Semantic Radar
- Interests: AI/ML infrastructure, backend systems, developer tools

Rules:
- 3 short paragraphs max
- No "Dear Hiring Manager" opener — start with a hook
- Be specific about the role and company
- Sound like a human, not a template
- End with genuine enthusiasm, not boilerplate
- 150-200 words total

Return only the cover letter text, no subject line."""

    response = anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(block, "text", "") for block in getattr(response, "content", []))
    return text.strip() or _fallback_cover_letter(job, company)


def _fallback_answer(question: str) -> str:
    normalized = question.lower()
    if "authorized" in normalized:
        return "Yes, I am authorized to work in the United States."
    if "sponsor" in normalized:
        return "I do not require visa sponsorship for this role."
    return "I am excited about this role because it matches my backend and infrastructure experience, and I would be glad to discuss the fit in more detail."


def answer_custom_question(question: str, job_title: str, company: str) -> str:
    """Generate a brief answer for a custom Greenhouse question."""
    if anthropic is None:
        log.warning("ANTHROPIC_API_KEY not set; using fallback answer for %s", question[:60])
        return _fallback_answer(question)

    response = anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": f"""Answer this job application question briefly and authentically.

Role: {job_title} at {company}
Question: {question}

About me: Anish Pavaskar, SWE II, Python/Go/K8s/AWS stack,
3 years experience, formerly Dell EMC, based in Bay Area.
Open to remote or Bay Area roles.

Answer in 1-3 sentences. Be direct and genuine. No fluff.""",
            }
        ],
    )
    text = "".join(getattr(block, "text", "") for block in getattr(response, "content", []))
    return text.strip() or _fallback_answer(question)


def _resume_file_payload() -> tuple[str, bytes, str] | None:
    if not RESUME_FILE.exists():
        log.warning("Resume not found at %s; set RESUME_PATH in .env", RESUME_FILE)
        return None

    mime_type = mimetypes.guess_type(RESUME_FILE.name)[0] or "application/octet-stream"
    return (RESUME_FILE.name, RESUME_FILE.read_bytes(), mime_type)


def build_application(job: JobDetails, slug: str) -> dict[str, Any]:
    """Build a Greenhouse application form payload."""
    title = str(job.get("title", "Unknown Role") or "Unknown Role")
    company = str(job.get("company_name", slug) or slug)
    questions = job.get("questions", [])

    log.info("Generating cover letter for %s @ %s", title, company)
    cover_letter = generate_cover_letter(job)
    answers: list[dict[str, str]] = []

    if not isinstance(questions, list):
        questions = []

    for question in questions:
        label = str(question.get("label", "") or "")
        required = bool(question.get("required", False))
        fields = question.get("fields", [])
        if not isinstance(fields, list) or not fields:
            continue

        field = fields[0] if isinstance(fields[0], dict) else {}
        field_type = str(field.get("type", "") or "")
        field_name = str(field.get("name", "") or "")
        field_name_lower = field_name.lower()

        if not field_name:
            continue
        if field_name in {"resume", "cover_letter"}:
            continue
        if field_name == "first_name":
            answers.append({"name": field_name, "value": APPLICANT["first_name"]})
        elif field_name == "last_name":
            answers.append({"name": field_name, "value": APPLICANT["last_name"]})
        elif field_name == "email":
            answers.append({"name": field_name, "value": APPLICANT["email"]})
        elif field_name == "phone":
            answers.append({"name": field_name, "value": APPLICANT["phone"]})
        elif field_name == "location":
            answers.append({"name": field_name, "value": APPLICANT["location"]})
        elif field_name == "linkedin_profile":
            answers.append({"name": field_name, "value": APPLICANT["linkedin_profile"]})
        elif field_name == "website":
            answers.append({"name": field_name, "value": APPLICANT["website"]})
        elif field_name == "github_profile" or "github" in field_name_lower:
            answers.append({"name": field_name, "value": APPLICANT["github_profile"]})
        elif field_type == "boolean" and "authorized" in label.lower():
            answers.append({"name": field_name, "value": "1"})
        elif field_type == "boolean" and "sponsor" in label.lower():
            answers.append({"name": field_name, "value": "0"})
        elif field_type in {"input_text", "textarea"} and required:
            log.info("Answering custom question: %s", label[:60])
            answers.append({"name": field_name, "value": answer_custom_question(label, title, company)})

    return {
        "answers": answers,
        "cover_letter": cover_letter,
        "resume_file": _resume_file_payload(),
    }


def submit_application(slug: str, job_id: str, payload: dict[str, Any]) -> bool:
    """Submit a Greenhouse application via the public board API."""
    url = f"{GH_BASE}/{slug}/jobs/{job_id}"
    form_data: dict[str, str] = {}
    for answer in payload.get("answers", []):
        name = str(answer.get("name", "") or "")
        if name:
            form_data[name] = str(answer.get("value", "") or "")

    cover_letter = str(payload.get("cover_letter", "") or "").strip()
    if cover_letter:
        form_data["cover_letter"] = cover_letter

    files = None
    resume_file = payload.get("resume_file")
    if isinstance(resume_file, tuple):
        files = {"resume": resume_file}

    try:
        response = httpx.post(url, data=form_data, files=files, timeout=30)
        if response.status_code in {200, 201, 202}:
            log.info("Application submitted successfully for %s/%s", slug, job_id)
            return True
        log.error("Submission failed for %s/%s: %s %s", slug, job_id, response.status_code, response.text[:200])
        return False
    except httpx.HTTPError as exc:
        log.error("Submission failed for %s/%s: %s", slug, job_id, exc)
        return False


def auto_apply_greenhouse(url: str) -> bool:
    """Run the full auto-apply flow for a Greenhouse URL."""
    slug, job_id = parse_greenhouse_url(url)
    if not slug or not job_id:
        return False

    log.info("Greenhouse detected: %s / job %s", slug, job_id)
    try:
        job = fetch_job_details(slug, job_id)
        if not job:
            return False

        title = str(job.get("title", "Unknown") or "Unknown")
        company = str(job.get("company_name", slug) or slug)
        log.info("Role: %s @ %s", title, company)

        payload = build_application(job, slug)
        success = submit_application(slug, job_id, payload)
        if not success:
            return False

        log_dir = Path(__file__).parent / "output" / "applications"
        log_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{slug}_{job_id}.txt"
        with (log_dir / safe_name).open("w", encoding="utf-8") as handle:
            handle.write(f"Role: {title} @ {company}\n")
            handle.write(f"URL: {url}\n\n")
            handle.write("COVER LETTER:\n")
            handle.write(str(payload.get("cover_letter", "") or ""))
        log.info("Saved application record to output/applications/%s", safe_name)
        return True
    except httpx.HTTPError as exc:
        log.error("Greenhouse HTTP error for %s: %s", url, exc)
        return False
    except Exception as exc:
        log.error("Unexpected auto-apply error for %s: %s", url, exc)
        return False
