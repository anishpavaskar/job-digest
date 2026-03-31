from __future__ import annotations

from pathlib import Path

import pytest

import sync_applied
import tracker


@pytest.fixture
def tracker_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "tracker.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    return db_path


def test_sync_applied_creates_file_if_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tracker_db: Path,
) -> None:
    applied_file = tmp_path / "applied.txt"
    monkeypatch.setattr(sync_applied, "APPLIED_FILE", applied_file)

    synced = sync_applied.sync_applied()

    assert synced == 0
    assert applied_file.exists()


def test_sync_applied_marks_greenhouse_urls_as_applied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tracker_db: Path,
) -> None:
    applied_file = tmp_path / "applied.txt"
    applied_file.write_text(
        "# comment\nhttps://boards.greenhouse.io/anthropic/jobs/12345\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_applied, "APPLIED_FILE", applied_file)
    monkeypatch.setattr(sync_applied, "auto_apply_greenhouse", lambda url: True)

    synced = sync_applied.sync_applied()
    job = tracker.get_job("https://boards.greenhouse.io/anthropic/jobs/12345")

    assert synced == 1
    assert job is not None
    assert job["status"] == "applied"
    assert job["notes"] == "auto-applied via Greenhouse API"


def test_sync_applied_skips_urls_already_marked_applied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tracker_db: Path,
) -> None:
    url = "https://boards.greenhouse.io/anthropic/jobs/12345"
    tracker.ensure_job(url)
    tracker.update_status(url, "applied", "existing")

    applied_file = tmp_path / "applied.txt"
    applied_file.write_text(f"{url}\n", encoding="utf-8")
    monkeypatch.setattr(sync_applied, "APPLIED_FILE", applied_file)

    calls: list[str] = []
    monkeypatch.setattr(sync_applied, "auto_apply_greenhouse", lambda value: calls.append(value) or True)

    synced = sync_applied.sync_applied()

    assert synced == 0
    assert calls == []
