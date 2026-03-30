from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import main


def _scored_job(job: dict[str, Any], score: int) -> dict[str, Any]:
    enriched = dict(job)
    enriched.update(
        {
            "score": score,
            "reasons": ["Mocked score"],
            "title_match": score,
            "skills_match": score,
            "level_match": score,
            "domain_fit": score,
            "location_fit": score,
            "rationale": "Mocked score",
        }
    )
    return enriched


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _async_raise(exc: Exception):
    async def _inner(*args, **kwargs):
        raise exc

    return _inner


def _patch_render(monkeypatch: pytest.MonkeyPatch, output_path: Path) -> None:
    def fake_render_html(jobs: list[dict[str, Any]], generated_at: str) -> str:
        titles = "".join(f"<div>{job['title']}</div>" for job in jobs)
        html = f"<html><body><span>{generated_at}</span>{titles}</body></html>"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return html

    monkeypatch.setattr(main, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(main, "render_html", fake_render_html)


@pytest.mark.asyncio
async def test_full_pipeline_runs_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
    tmp_path: Path,
) -> None:
    sent: list[tuple[list[dict[str, Any]], str]] = []
    output_path = tmp_path / "output" / "digest.html"

    async def fake_score_jobs(jobs: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
        return [_scored_job(job, 90 - index) for index, job in enumerate(jobs)]

    def fake_send_digest(jobs: list[dict[str, Any]], html_page_path: str) -> None:
        sent.append((jobs, html_page_path))

    monkeypatch.setattr(main, "fetch_greenhouse_jobs", _async_return(sample_jobs))
    monkeypatch.setattr(main, "fetch_yc_jobs", _async_return(sample_jobs))
    monkeypatch.setattr(main, "fetch_prospect_jobs", _async_return(sample_jobs))
    monkeypatch.setattr(main, "fetch_linkedin_jobs", _async_return(sample_jobs))
    monkeypatch.setattr(main, "fetch_unified_jobs", _async_return(sample_jobs))
    monkeypatch.setattr(main, "score_jobs", fake_score_jobs)
    monkeypatch.setattr(main, "send_digest", fake_send_digest)
    _patch_render(monkeypatch, output_path)

    result = await main.run_pipeline()

    assert output_path.exists()
    assert sent
    assert sent[0][1] == str(output_path)
    assert len(result) == len(sample_jobs) - 1
    assert all(job["title"] != sample_jobs[3]["title"] for job in result)


@pytest.mark.asyncio
async def test_pipeline_handles_fetcher_exception_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
    tmp_path: Path,
) -> None:
    sent: list[list[dict[str, Any]]] = []
    output_path = tmp_path / "output" / "digest.html"

    async def fake_score_jobs(jobs: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
        return [_scored_job(job, 75) for job in jobs]

    def fake_send_digest(jobs: list[dict[str, Any]], html_page_path: str) -> None:
        sent.append(jobs)

    monkeypatch.setattr(main, "fetch_greenhouse_jobs", _async_raise(Exception("boom")))
    monkeypatch.setattr(main, "fetch_yc_jobs", _async_return(sample_jobs[:2]))
    monkeypatch.setattr(main, "fetch_prospect_jobs", _async_return(sample_jobs[2:4]))
    monkeypatch.setattr(main, "fetch_linkedin_jobs", _async_return(sample_jobs[4:]))
    monkeypatch.setattr(main, "fetch_unified_jobs", _async_return([]))
    monkeypatch.setattr(main, "score_jobs", fake_score_jobs)
    monkeypatch.setattr(main, "send_digest", fake_send_digest)
    _patch_render(monkeypatch, output_path)

    result = await main.run_pipeline()

    assert output_path.exists()
    assert sent
    assert len(result) == len(sample_jobs) - 1
    assert all(job["title"] != sample_jobs[3]["title"] for job in result)


@pytest.mark.asyncio
async def test_pipeline_deduplicates_jobs(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
    tmp_path: Path,
) -> None:
    sent: list[list[dict[str, Any]]] = []
    output_path = tmp_path / "output" / "digest.html"
    duplicate_job = dict(sample_jobs[0], id="yc:duplicate:9999", source="yc")

    async def fake_score_jobs(jobs: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
        return [_scored_job(job, 88) for job in jobs]

    def fake_send_digest(jobs: list[dict[str, Any]], html_page_path: str) -> None:
        sent.append(jobs)

    monkeypatch.setattr(main, "fetch_greenhouse_jobs", _async_return([sample_jobs[0]]))
    monkeypatch.setattr(main, "fetch_yc_jobs", _async_return([duplicate_job]))
    monkeypatch.setattr(main, "fetch_prospect_jobs", _async_return([]))
    monkeypatch.setattr(main, "fetch_linkedin_jobs", _async_return([]))
    monkeypatch.setattr(main, "fetch_unified_jobs", _async_return([]))
    monkeypatch.setattr(main, "score_jobs", fake_score_jobs)
    monkeypatch.setattr(main, "send_digest", fake_send_digest)
    _patch_render(monkeypatch, output_path)

    result = await main.run_pipeline()

    assert len(result) == 1
    assert sent
    assert len(sent[0]) == 1
    assert output_path.read_text(encoding="utf-8").count(sample_jobs[0]["title"]) == 1
