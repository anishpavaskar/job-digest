"""LinkedIn fetcher via linkedin-mcp-server using a real session."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import LINKEDIN_MCP_SEARCHES
from logging_config import get_logger

SUBPROCESS_TIMEOUT = 60
READ_TIMEOUT = 60
log = get_logger("linkedin_mcp")


def _uvx_command() -> str | None:
    command = shutil.which("uvx")
    if command:
        return command

    local_uvx = Path.home() / ".local" / "bin" / "uvx"
    if local_uvx.exists():
        return str(local_uvx)
    return None


def _is_mcp_available() -> bool:
    uvx = _uvx_command()
    if uvx is None:
        return False

    try:
        result = subprocess.run(
            [uvx, "--version"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _load_json(raw_text: str, context: str) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        preview = raw_text[:100].replace("\n", " ")
        log.warning("%s returned invalid JSON: %s", context, preview)
        return None


def _normalize_linkedin_job(job: dict[str, Any]) -> dict[str, str]:
    url = str(job.get("url", job.get("job_url", "")) or "").strip()
    return {
        "id": f"linkedin_mcp:{url[-40:]}",
        "title": str(job.get("title", "") or "").strip(),
        "company": str(job.get("company", "") or "").strip(),
        "location": str(job.get("location", "Remote") or "Remote").strip(),
        "url": url,
        "description": str(job.get("description", "") or "")[:600],
        "source": "linkedin_mcp",
        "posted_at": str(job.get("date_posted", "") or "").strip(),
    }


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\xa0", " ")).strip()


def _is_metadata_line(line: str) -> bool:
    lowered = line.lower()
    return (
        not line
        or lowered in {"viewed", "promoted", "easy apply", "previous", "next", "set alert"}
        or lowered.startswith("set job alert")
        or lowered.startswith("jump to active")
        or lowered.startswith("see jobs where")
        or lowered.startswith("try premium")
        or lowered.startswith("dismiss premium")
        or "connections work here" in lowered
        or "connection works here" in lowered
        or "alumni work here" in lowered
        or "benefit" in lowered
        or "actively reviewing applicants" in lowered
        or "within the past" in lowered
        or lowered.endswith("results")
        or lowered.isdigit()
        or bool(re.search(r"\$\d", line))
    )


def _looks_like_location(line: str) -> bool:
    lowered = line.lower()
    return (
        "remote" in lowered
        or "united states" in lowered
        or "bay area" in lowered
        or "new york" in lowered
        or "san francisco" in lowered
        or "seattle" in lowered
        or "austin" in lowered
        or "miami" in lowered
        or ", " in line
        or " area" in lowered
        or "/" in line
        or bool(re.search(r"\b[A-Z]{2}\b", line))
    )


def _linkedin_url(ref_url: str) -> str:
    if ref_url.startswith("http"):
        return ref_url
    if ref_url.startswith("/"):
        return f"https://www.linkedin.com{ref_url}"
    return ""


def _find_line_index(lines: list[str], candidates: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        if lines[index] in candidates:
            return index
    return -1


def _expand_search_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    references = payload.get("references", {}).get("search_results", [])
    section_text = (
        payload.get("structuredContent", {}).get("sections", {}).get("search_results")
        or payload.get("sections", {}).get("search_results")
        or ""
    )
    lines = [_clean_line(line) for line in str(section_text).splitlines()]
    lines = [line for line in lines if line]

    jobs: list[dict[str, str]] = []
    cursor = 0
    for reference in references:
        if reference.get("kind") != "job":
            continue

        raw_title = _clean_line(str(reference.get("text", "") or ""))
        title = raw_title.removesuffix(" with verification").strip()
        if not title:
            continue

        index = _find_line_index(lines, [raw_title, title], cursor)
        if index == -1:
            continue
        cursor = index + 1

        company = ""
        location = "Remote"
        block_lines = [title]
        for line in lines[index + 1 : index + 10]:
            if line in {raw_title, title} or _is_metadata_line(line):
                continue
            block_lines.append(line)
            if not company:
                company = line
                continue
            if _looks_like_location(line):
                location = line
                break
            if company and location == "Remote":
                location = line
                break

        url = _linkedin_url(str(reference.get("url", "") or ""))
        jobs.append(
            {
                "id": f"linkedin_mcp:{url[-40:]}",
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "description": " ".join(block_lines)[:600],
                "source": "linkedin_mcp",
                "posted_at": "",
            }
        )

    return [job for job in jobs if job["url"] and job["title"]]


def _normalize_linkedin_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    if payload.get("references") or payload.get("structuredContent"):
        return _expand_search_payload(payload)
    return [_normalize_linkedin_job(payload)]


async def _call_mcp_search(query: str, location: str = "Remote") -> list[dict[str, Any]]:
    uvx = _uvx_command()
    if uvx is None:
        return []

    init_request = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "job-digest", "version": "1.0"},
        },
    }
    initialized_notification = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    tool_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_jobs",
            "arguments": {
                "keywords": query,
                "location": location,
            },
        },
    }

    try:
        process = await asyncio.create_subprocess_exec(
            uvx,
            "linkedin-scraper-mcp",
            "--transport",
            "stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PATH": f"{Path.home() / '.local' / 'bin'}:{os.environ.get('PATH', '')}"},
        )
        payload = "".join(
            json.dumps(message) + "\n"
            for message in (init_request, initialized_notification, tool_request)
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        process.stdin.write(payload.encode())
        await process.stdin.drain()

        jobs: list[dict[str, Any]] = []
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=READ_TIMEOUT)
            if not line:
                break

            response = _load_json(line.decode().strip(), f"{query} MCP line")
            if not isinstance(response, dict):
                return []

            if response.get("id") == 0:
                continue

            result = response.get("result", {})
            for item in result.get("content", []):
                if item.get("type") != "text":
                    continue
                payload = _load_json(str(item.get("text", "")), f"{query} MCP payload")
                if payload is None:
                    return []
                if isinstance(payload, list):
                    jobs.extend(item for item in payload if isinstance(item, dict))
                elif isinstance(payload, dict):
                    jobs.append(payload)

            if response.get("id") == 1:
                break

        process.stdin.close()
        try:
            await process.stdin.wait_closed()
        except AttributeError:
            pass

        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=SUBPROCESS_TIMEOUT)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        error = (await process.stderr.read()).decode().strip()
        if process.returncode not in (0, -15) and not jobs:
            log.warning("MCP server error: %s", error[:400])
            return []

        log.info("'%s': %s jobs", query, len(jobs))
        return jobs
    except asyncio.TimeoutError:
        log.warning("'%s' timed out", query)
        return []
    except Exception as exc:
        log.warning("'%s' error: %s", query, exc)
        return []


async def fetch_linkedin_mcp_jobs(searches: list[str] | None = None) -> list[dict[str, str]]:
    if searches is None:
        searches = LINKEDIN_MCP_SEARCHES

    if not _is_mcp_available():
        log.warning("uvx not found — skipping")
        log.info("Setup: uvx patchright install chromium && uvx linkedin-scraper-mcp --login")
        return []

    results = await asyncio.gather(*[_call_mcp_search(query) for query in searches], return_exceptions=True)
    seen_urls: set[str] = set()
    jobs: list[dict[str, str]] = []
    for result in results:
        if isinstance(result, list):
            for raw_job in result:
                for job in _normalize_linkedin_payload(raw_job):
                    if job["url"] and job["url"] not in seen_urls:
                        seen_urls.add(job["url"])
                        jobs.append(job)

    log.info("Total unique: %s", len(jobs))
    return jobs
