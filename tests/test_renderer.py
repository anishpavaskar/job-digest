from __future__ import annotations

import renderer


def test_html_output_is_valid_string(sample_scored_jobs: list[dict]) -> None:
    html = renderer.render_html(sample_scored_jobs, "2026-01-01")
    assert isinstance(html, str)
    assert len(html) > 500


def test_html_contains_all_job_titles(sample_scored_jobs: list[dict]) -> None:
    html = renderer.render_html(sample_scored_jobs, "2026-01-01")
    for job in sample_scored_jobs:
        assert job["title"] in html


def test_html_contains_apply_links(sample_scored_jobs: list[dict]) -> None:
    html = renderer.render_html(sample_scored_jobs, "2026-01-01")
    for job in sample_scored_jobs:
        assert f'href="{job["url"]}"' in html


def test_html_contains_visible_job_urls(sample_scored_jobs: list[dict]) -> None:
    html = renderer.render_html(sample_scored_jobs, "2026-01-01")
    for job in sample_scored_jobs:
        assert html.count(job["url"]) >= 2


def test_html_file_is_saved_to_disk(sample_scored_jobs: list[dict]) -> None:
    html = renderer.render_html(sample_scored_jobs, "2026-01-01")
    assert renderer.OUTPUT_PATH.exists()
    assert renderer.OUTPUT_PATH.read_text(encoding="utf-8") == html


def test_html_has_no_external_dependencies(sample_scored_jobs: list[dict]) -> None:
    html = renderer.render_html(sample_scored_jobs, "2026-01-01").lower()
    assert "cdn." not in html
    assert "bootstrap" not in html
