from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

import scorer
from config import MY_PROFILE


def _fake_anthropic_factory(raw_responses: list[str]):
    queue = deque(raw_responses)

    class FakeAnthropic:
        def __init__(self, api_key: str):
            self.api_key = api_key
            self.messages = self

        async def create(self, **kwargs):
            if not queue:
                raise AssertionError("No fake Anthropic responses left.")
            return SimpleNamespace(content=[SimpleNamespace(text=queue.popleft())])

    return FakeAnthropic


def _mock_anthropic(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> None:
    monkeypatch.setattr(scorer, "AsyncAnthropic", _fake_anthropic_factory(responses))
    monkeypatch.setattr(scorer, "ANTHROPIC_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_score_is_integer_between_0_and_100(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
) -> None:
    _mock_anthropic(
        monkeypatch,
        [
            """[
              {
                "score": 88,
                "reasons": ["Strong fit", "Good stack overlap", "Remote friendly"],
                "title_match": 90,
                "skills_match": 92,
                "level_match": 80,
                "domain_fit": 78,
                "location_fit": 100
              }
            ]""",
        ],
    )
    monkeypatch.setattr(scorer, "MIN_SCORE", 0)

    result = await scorer.score_jobs([sample_jobs[0]], MY_PROFILE)

    assert len(result) == 1
    assert isinstance(result[0]["score"], int)
    assert 0 <= result[0]["score"] <= 100


@pytest.mark.slow
@pytest.mark.asyncio
async def test_perfect_match_scores_higher_than_poor_match(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
) -> None:
    if not scorer.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY is not configured.")

    monkeypatch.setattr(scorer, "MIN_SCORE", 0)
    jobs = [sample_jobs[0], sample_jobs[4]]
    scored_jobs = await scorer.score_jobs(jobs, MY_PROFILE)
    by_id = {job["id"]: job for job in scored_jobs}

    assert by_id[sample_jobs[0]["id"]]["score"] > by_id[sample_jobs[4]["id"]]["score"]


@pytest.mark.asyncio
async def test_invalid_haiku_response_assigns_score_zero(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
) -> None:
    _mock_anthropic(monkeypatch, ["not-json-at-all"])
    monkeypatch.setattr(scorer, "MIN_SCORE", 0)

    result = await scorer.score_jobs([sample_jobs[0]], MY_PROFILE)

    assert len(result) == 1
    assert result[0]["score"] == 0
    assert result[0]["reasons"] == []


@pytest.mark.asyncio
async def test_jobs_below_min_score_are_filtered(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
) -> None:
    _mock_anthropic(
        monkeypatch,
        [
            """[
              {"score": 20, "reasons": [], "title_match": 20, "skills_match": 20, "level_match": 20, "domain_fit": 20, "location_fit": 20},
              {"score": 80, "reasons": ["good"], "title_match": 80, "skills_match": 80, "level_match": 80, "domain_fit": 80, "location_fit": 80}
            ]""",
        ],
    )
    monkeypatch.setattr(scorer, "MIN_SCORE", 55)

    result = await scorer.score_jobs(sample_jobs[:2], MY_PROFILE)

    assert len(result) == 1
    assert result[0]["id"] == sample_jobs[1]["id"]
    assert result[0]["score"] == 80


@pytest.mark.asyncio
async def test_jobs_sorted_by_score_descending(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
) -> None:
    _mock_anthropic(
        monkeypatch,
        [
            """[
              {"score": 60, "reasons": [], "title_match": 60, "skills_match": 60, "level_match": 60, "domain_fit": 60, "location_fit": 60},
              {"score": 95, "reasons": [], "title_match": 95, "skills_match": 95, "level_match": 95, "domain_fit": 95, "location_fit": 95},
              {"score": 80, "reasons": [], "title_match": 80, "skills_match": 80, "level_match": 80, "domain_fit": 80, "location_fit": 80}
            ]""",
        ],
    )
    monkeypatch.setattr(scorer, "MIN_SCORE", 0)

    result = await scorer.score_jobs(sample_jobs[:3], MY_PROFILE)
    scores = [job["score"] for job in result]

    assert scores == sorted(scores, reverse=True)


def test_pre_filter_jobs_skips_obvious_mismatches(sample_jobs: list[dict]) -> None:
    jobs_to_score, skipped = scorer.pre_filter_jobs(sample_jobs)

    assert skipped >= 1
    assert all("Account Executive" not in job["title"] for job in jobs_to_score)


@pytest.mark.asyncio
async def test_score_jobs_batches_multiple_calls(
    monkeypatch: pytest.MonkeyPatch,
    sample_jobs: list[dict],
) -> None:
    expanded_jobs = [
        {
            "id": f"good:{index}",
            "title": f"Platform Engineer {index}",
            "company": f"Company {index}",
            "location": "Remote",
            "url": f"https://example.com/jobs/good-{index}",
            "description": "Python Go Kubernetes platform role.",
            "source": "greenhouse",
            "posted_at": "2026-01-16",
        }
        for index in range(6)
    ]
    _mock_anthropic(
        monkeypatch,
        [
            """[
              {"score": 90, "reasons": ["a"], "title_match": 90, "skills_match": 90, "level_match": 90, "domain_fit": 90, "location_fit": 90},
              {"score": 85, "reasons": ["b"], "title_match": 85, "skills_match": 85, "level_match": 85, "domain_fit": 85, "location_fit": 85},
              {"score": 80, "reasons": ["c"], "title_match": 80, "skills_match": 80, "level_match": 80, "domain_fit": 80, "location_fit": 80},
              {"score": 75, "reasons": ["d"], "title_match": 75, "skills_match": 75, "level_match": 75, "domain_fit": 75, "location_fit": 75},
              {"score": 70, "reasons": ["e"], "title_match": 70, "skills_match": 70, "level_match": 70, "domain_fit": 70, "location_fit": 70}
            ]""",
            """[
              {"score": 65, "reasons": ["f"], "title_match": 65, "skills_match": 65, "level_match": 65, "domain_fit": 65, "location_fit": 65}
            ]""",
        ],
    )
    monkeypatch.setattr(scorer, "MIN_SCORE", 0)

    result = await scorer.score_jobs(expanded_jobs, MY_PROFILE)

    assert len(result) == 6
    assert result[0]["score"] == 90
    assert result[-1]["score"] == 65
