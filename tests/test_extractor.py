import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from upwork_extractor import UpworkExtractor
from upwork_extractor import cli


def make_saved_page(description: str, title: str = "Test Job") -> str:
    payload = [
        ["Reactive", 1],
        {"vuex": 2},
        {"jobDetails": 3},
        {"job": 4},
        {
            "uid": 5,
            "title": 6,
            "description": 7,
        },
        "123456",
        title,
        description,
    ]
    raw_json = json.dumps(payload)
    return f'<html><body><script type="application/json">{raw_json}</script></body></html>'


def test_extracts_title_and_markdown_body():
    html = make_saved_page(
        "<p>Hello <strong>world</strong>.</p><ul><li>One</li><li>Two</li></ul>"
    )

    job = UpworkExtractor.from_string(html).extract()

    assert job.title == "Test Job"
    assert job.to_markdown() == "# Test Job\n\nHello **world**.\n\n- One\n- Two\n"


def test_preserves_plain_text_descriptions():
    html = make_saved_page("First paragraph.\n\nSecond paragraph.")

    job = UpworkExtractor.from_string(html).extract()

    assert job.to_markdown() == "# Test Job\n\nFirst paragraph.\n\nSecond paragraph.\n"


def test_renders_links_and_ordered_lists():
    html = make_saved_page(
        "<p>Read <a href=\"https://example.com\">this brief</a>.</p>"
        "<ol><li>First</li><li>Second</li></ol>"
    )

    job = UpworkExtractor.from_string(html).extract()

    assert "[this brief](https://example.com)" in job.to_markdown()
    assert "1. First" in job.to_markdown()
    assert "2. Second" in job.to_markdown()


def test_cli_outputs_markdown(capsys, tmp_path: Path):
    saved_page = tmp_path / "posting.html"
    saved_page.write_text(make_saved_page("<p>Converted</p>"), encoding="utf-8")

    exit_code = cli.main([str(saved_page)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "# Test Job\n\nConverted\n"
    assert captured.err == ""


def test_wrong_file_error():
    with pytest.raises(ValueError, match="slide-over"):
        UpworkExtractor.from_string("<html><body>no payload here</body></html>").extract()
