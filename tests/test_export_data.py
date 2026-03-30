from __future__ import annotations

import json
from pathlib import Path

import pytest

import export_data


def test_export_jobs_writes_dashboard_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_scored_jobs: list[dict],
) -> None:
    data_dir = tmp_path / "dashboard" / "data"
    jobs_json = data_dir / "jobs.json"

    monkeypatch.setattr(export_data, "DASHBOARD_DATA", data_dir)
    monkeypatch.setattr(export_data, "JOBS_JSON", jobs_json)
    monkeypatch.setattr(export_data, "init_db", lambda: None)
    monkeypatch.setattr(export_data, "search_jobs", lambda **kwargs: sample_scored_jobs[:2])
    monkeypatch.setattr(
        export_data,
        "get_stats",
        lambda: {"total_seen": 2, "by_status": {"new": 1, "applied": 1}, "top_sources": {}, "recent": []},
    )

    count = export_data.export_jobs()

    assert count == 2
    assert jobs_json.exists()
    payload = json.loads(jobs_json.read_text(encoding="utf-8"))
    assert payload["stats"]["total_seen"] == 2
    assert len(payload["jobs"]) == 2
    assert payload["jobs"][0]["url"] == sample_scored_jobs[0]["url"]


def test_export_and_push_skips_git_when_no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(export_data, "export_jobs", lambda: 0)
    monkeypatch.setattr(export_data, "git_push", lambda: calls.append("pushed"))

    export_data.export_and_push()

    assert calls == []
