from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import tracker


@pytest.fixture
def tracker_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "tracker.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    return db_path


def test_filter_new_jobs_only_returns_unseen_jobs(
    sample_jobs: list[dict],
    tracker_db: Path,
) -> None:
    first_run = tracker.filter_new_jobs(sample_jobs[:2])
    second_run = tracker.filter_new_jobs([sample_jobs[0]])

    assert tracker_db.exists()
    assert len(first_run) == 2
    assert second_run == []
    assert tracker.get_stats()["total_seen"] == 2


def test_filter_new_jobs_updates_last_seen_for_existing_jobs(
    sample_jobs: list[dict],
    tracker_db: Path,
) -> None:
    tracker.filter_new_jobs([sample_jobs[0]])
    with sqlite3.connect(tracker_db) as conn:
        first_last_seen = conn.execute("SELECT last_seen FROM jobs WHERE url = ?", (sample_jobs[0]["url"],)).fetchone()[0]

    tracker.filter_new_jobs([sample_jobs[0]])
    with sqlite3.connect(tracker_db) as conn:
        second_last_seen = conn.execute("SELECT last_seen FROM jobs WHERE url = ?", (sample_jobs[0]["url"],)).fetchone()[0]

    assert second_last_seen >= first_last_seen


def test_update_scores_persists_job_scores(
    sample_scored_jobs: list[dict],
    tracker_db: Path,
) -> None:
    tracker.filter_new_jobs(sample_scored_jobs[:2])
    tracker.update_scores(sample_scored_jobs[:2])

    jobs = tracker.search_jobs(limit=5)
    by_url = {job["url"]: job for job in jobs}

    assert by_url[sample_scored_jobs[0]["url"]]["score"] == sample_scored_jobs[0]["score"]
    assert by_url[sample_scored_jobs[1]["url"]]["score"] == sample_scored_jobs[1]["score"]


def test_update_status_tracks_applied_jobs(
    sample_jobs: list[dict],
    tracker_db: Path,
) -> None:
    tracker.filter_new_jobs([sample_jobs[0]])
    tracker.update_status(sample_jobs[0]["url"], "applied", "submitted via portal")

    applied_jobs = tracker.get_applied_jobs()

    assert len(applied_jobs) == 1
    assert applied_jobs[0]["url"] == sample_jobs[0]["url"]
    assert applied_jobs[0]["notes"] == "submitted via portal"
    assert applied_jobs[0]["applied_at"]


def test_search_jobs_filters_by_query_and_status(
    sample_scored_jobs: list[dict],
    tracker_db: Path,
) -> None:
    tracker.filter_new_jobs(sample_scored_jobs[:3])
    tracker.update_scores(sample_scored_jobs[:3])
    tracker.update_status(sample_scored_jobs[1]["url"], "skipped", "too senior")

    results = tracker.search_jobs(query="Brex", status="skipped", limit=5)

    assert len(results) == 1
    assert results[0]["company"] == "Brex"
    assert results[0]["status"] == "skipped"
