"""
tests/test_extractor.py

Run with:  pytest tests/
Requires:  tests/fixtures/sample.html  (a correctly saved Upwork job page)

How to save the fixture correctly
----------------------------------
Open the job in its own tab (URL contains /freelance-jobs/apply/…),
then File → Save Page As → "Webpage, HTML Only".
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from upwork_extractor import UpworkExtractor
from upwork_extractor import cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample.html"


@pytest.fixture(scope="module")
def job():
    if not FIXTURE.exists():
        pytest.skip(f"Fixture not found: {FIXTURE}")
    return UpworkExtractor.from_file(FIXTURE).extract()


# ------------------------------------------------------------------
# Identity
# ------------------------------------------------------------------

def test_title(job):
    assert "PDF" in job.posting.title or "Data Extraction" in job.posting.title

def test_uid_numeric(job):
    assert job.posting.uid.isdigit()

def test_url_contains_ciphertext(job):
    assert job.posting.ciphertext in job.posting.url

def test_posted_on_display(job):
    assert "2026" in job.posting.posted_on_display()


# ------------------------------------------------------------------
# Budget
# ------------------------------------------------------------------

def test_budget_type(job):
    assert job.posting.budget.job_type == "Fixed-price"

def test_budget_amount(job):
    assert job.posting.budget.fixed_amount == 5000.0

def test_budget_currency(job):
    assert job.posting.budget.currency == "USD"

def test_budget_not_hidden(job):
    assert not job.posting.budget.hidden

def test_budget_display(job):
    assert "$5,000" in job.posting.budget.display()


# ------------------------------------------------------------------
# Job terms
# ------------------------------------------------------------------

def test_duration_label(job):
    assert job.posting.duration_label is not None
    assert "month" in job.posting.duration_label.lower()

def test_duration_weeks(job):
    assert job.posting.duration_weeks == 9

def test_contractor_tier(job):
    assert job.posting.contractor_tier == "Intermediate"

def test_project_type(job):
    assert job.posting.project_type  # non-empty


# ------------------------------------------------------------------
# Skills
# ------------------------------------------------------------------

def test_skills_non_empty(job):
    assert len(job.posting.skills) > 0

def test_mandatory_skill_present(job):
    assert "AI App Development" in job.posting.mandatory_skills()

def test_python_in_all_skills(job):
    assert "Python" in job.posting.all_skill_names()

def test_no_duplicate_skills(job):
    names = job.posting.all_skill_names()
    assert len(names) == len(set(names))


# ------------------------------------------------------------------
# Description
# ------------------------------------------------------------------

def test_description_non_empty(job):
    assert len(job.posting.description) > 100

def test_description_content(job):
    assert "PDF" in job.posting.description


# ------------------------------------------------------------------
# Client
# ------------------------------------------------------------------

def test_client_country(job):
    assert job.posting.client.location_country == "Canada"

def test_client_city(job):
    assert job.posting.client.location_city == "Brossard"

def test_client_payment_verified(job):
    assert job.posting.client.payment_verified is True

def test_client_rating(job):
    assert job.posting.client.rating == pytest.approx(4.99, abs=0.01)

def test_client_hire_rate(job):
    rate = job.posting.client.hire_rate()
    assert rate is not None
    assert 0 < rate <= 100


# ------------------------------------------------------------------
# Activity
# ------------------------------------------------------------------

def test_activity_applicants(job):
    assert job.posting.activity.total_applicants > 0

def test_activity_bids_ordered(job):
    a = job.posting.activity
    assert a.bid_min is not None
    assert a.bid_avg is not None
    assert a.bid_max is not None
    assert a.bid_min <= a.bid_avg <= a.bid_max


# ------------------------------------------------------------------
# Attachments
# ------------------------------------------------------------------

def test_attachments_exist(job):
    assert len(job.posting.attachments) > 0

def test_pdf_attachment(job):
    assert any(".pdf" in a.file_name.lower() for a in job.posting.attachments)


# ------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------

def test_to_dict_keys(job):
    d = job.to_dict()
    assert {"uid", "url", "title", "budget", "skills", "client", "activity"}.issubset(d)
    assert isinstance(d["skills"]["mandatory"], list)
    assert isinstance(d["client"]["rating"], float)

def test_to_json_roundtrip(job):
    parsed = json.loads(job.to_json())
    assert parsed["title"] == job.posting.title

def test_to_yaml(job):
    out = job.to_yaml()
    assert "title:" in out
    assert "description:" in out

def test_to_markdown_structure(job):
    md = job.to_markdown()
    assert md.startswith("#")
    assert "## Job Description" in md
    assert "## About the Client" in md
    assert "## Activity" in md
    assert "## Skills" in md


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def test_cli_defaults_to_markdown(capsys):
    exit_code = cli.main([str(FIXTURE)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.startswith("#")
    assert "## Job Description" in captured.out
    assert captured.err == ""


def test_cli_yaml_output(capsys):
    exit_code = cli.main([str(FIXTURE), "--format", "yaml"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "title:" in captured.out
    assert "description:" in captured.out
    assert captured.err == ""


def test_cli_out_writes_markdown_file(tmp_path, capsys):
    out_path = tmp_path / "job.md"

    exit_code = cli.main([str(FIXTURE), "--out", str(out_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8").startswith("#")
    assert f"Written to {out_path}" in captured.err
    assert captured.out == ""


# ------------------------------------------------------------------
# Wrong-file error
# ------------------------------------------------------------------

def test_wrong_file_error():
    """Saving the overlay page instead of the standalone tab raises a clear error."""
    with pytest.raises(ValueError, match="slide-over"):
        UpworkExtractor.from_string("<html><body>no payload here</body></html>").extract()
