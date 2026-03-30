from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (requires live API calls)"
    )


@pytest.fixture
def sample_jobs() -> list[dict]:
    return json.loads((FIXTURES_DIR / "sample_jobs.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_scored_jobs() -> list[dict]:
    return json.loads((FIXTURES_DIR / "sample_scored.json").read_text(encoding="utf-8"))
