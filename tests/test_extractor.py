import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from posting_extractor import (
    GenericHtmlExtractor,
    UpworkExtractor,
    WelcomeToTheJungleExtractor,
    extract_job_posting,
    select_extractor,
)
from posting_extractor import cli


def make_saved_page(
    description: str,
    title: str = "Test Job",
    attachments: list[dict[str, object]] | None = None,
) -> str:
    attachments = attachments or []
    payload: list[object] = [
        ["Reactive", 1],
        {"vuex": 2},
        {"jobDetails": 3},
        {"job": 4},
        {
            "uid": 5,
            "title": 6,
            "description": 7,
            "attachments": 8,
        },
        "123456",
        title,
        description,
        [],
    ]

    attachment_indexes = []
    for attachment in attachments:
        file_name_index = len(payload)
        payload.append(attachment["fileName"])

        uri_index = len(payload)
        payload.append(attachment["uri"])

        attachment_index = len(payload)
        payload.append(
            {
                "fileName": file_name_index,
                "uri": uri_index,
            }
        )
        attachment_indexes.append(attachment_index)

    payload[8] = attachment_indexes
    raw_json = json.dumps(payload)
    return f'<html><body><script type="application/json">{raw_json}</script></body></html>'


def make_generic_job_page() -> str:
    return """\
<html>
  <head>
    <title>Senior Python Developer | Example Co</title>
  </head>
  <body>
    <nav>Home Jobs Sign in</nav>
    <main>
      <section>
        <h1>Senior Python Developer</h1>
        <p>Join the platform team building backend services for job seekers.</p>
      </section>
      <section>
        <h2>Responsibilities</h2>
        <ul>
          <li>Build APIs</li>
          <li>Improve reliability</li>
        </ul>
      </section>
      <section>
        <h2>Requirements</h2>
        <p>Python, SQL, and clear communication.</p>
        <a href="/files/brief.pdf">Download brief</a>
      </section>
    </main>
    <footer>Privacy Terms</footer>
  </body>
</html>
"""


def make_welcome_to_the_jungle_job_page() -> str:
    job_posting = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": "Software Engineer",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Example Co",
        },
        "description": (
            "<h1>Requirements</h1>"
            "<ul>"
            "<li>Strong Python experience</li>,"
            "<li>Clear written communication</li>"
            "</ul>"
        ),
        "responsibilities": (
            "<ul>"
            "<li>Build internal tools</li>,"
            "<li>Work across distributed teams</li>"
            "</ul>"
        ),
        "skills": (
            "<ul>"
            "<li>Python</li>,"
            "<li>APIs</li>"
            "</ul>"
        ),
        "jobBenefits": (
            "<ul>"
            "<li>Remote work</li>,"
            "<li>Home office stipend</li>"
            "</ul>"
        ),
    }
    raw_json = json.dumps(job_posting)
    return f"""\
<html>
  <head>
    <title>Example Co Software Engineer | Welcome to the Jungle</title>
    <meta property="og:site_name" content="Welcome to the Jungle" />
    <script type="application/ld+json">{raw_json}</script>
  </head>
  <body>
    <main><h1>Software Engineer</h1></main>
    <div data-testid="salary-section"><span>$120k</span><span> + Equity</span></div>
    <div data-testid="experience-section">Junior and Mid level</div>
    <div data-testid="job-locations">
      <div>Remote from US</div>
      <div>Remote from Canada</div>
    </div>
    <div data-testid="job-technology-used">
      <div disabled="">Python</div>
      <div disabled="">GraphQL</div>
      <div disabled="">AWS</div>
    </div>
    <div data-testid="company-sector-tags">
      <span>SaaS</span>
      <span>Developer Tools</span>
    </div>
  </body>
</html>
"""


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


def test_renders_attachments_as_markdown_links():
    html = make_saved_page(
        "<p>Converted</p>",
        attachments=[
            {
                "fileName": "brief.pdf",
                "uri": "/att/download/openings/123/attachments/abc/download",
            },
            {
                "fileName": "screenshot.png",
                "uri": "/att/download/openings/123/attachments/def/download",
            },
        ],
    )

    job = UpworkExtractor.from_string(html).extract()

    assert "## Attachments" in job.to_markdown()
    assert "- [brief.pdf](https://www.upwork.com/att/download/openings/123/attachments/abc/download)" in job.to_markdown()
    assert "- [screenshot.png](https://www.upwork.com/att/download/openings/123/attachments/def/download)" in job.to_markdown()


def test_extract_job_posting_falls_back_to_generic_html():
    job = extract_job_posting(
        make_generic_job_page(),
        source_url="https://example.com/jobs/senior-python-developer",
    )

    assert job.title == "Senior Python Developer"
    assert "Responsibilities" in job.to_markdown()
    assert "[Download brief](https://example.com/files/brief.pdf)" in job.to_markdown()
    assert "Home Jobs Sign in" not in job.to_markdown()
    assert "Privacy Terms" not in job.to_markdown()


def test_select_extractor_returns_upwork_for_upwork_payload():
    extractor = select_extractor(make_saved_page("<p>Converted</p>"))

    assert extractor is UpworkExtractor


def test_select_extractor_returns_generic_for_generic_page():
    extractor = select_extractor(
        make_generic_job_page(),
        source_url="https://example.com/jobs/senior-python-developer",
    )

    assert extractor is GenericHtmlExtractor


def test_select_extractor_returns_wttj_for_wttj_payload():
    extractor = select_extractor(
        make_welcome_to_the_jungle_job_page(),
        source_url="https://app.welcometothejungle.com/jobs/example",
    )

    assert extractor is WelcomeToTheJungleExtractor


def test_upwork_matches_checks_content_signature():
    assert UpworkExtractor.matches(make_saved_page("<p>Converted</p>")) is True
    assert UpworkExtractor.matches(make_generic_job_page()) is False


def test_generic_matches_checks_content_signature():
    assert GenericHtmlExtractor.matches(make_generic_job_page()) is True
    assert GenericHtmlExtractor.matches("<html><body><p>Too short</p></body></html>") is False


def test_wttj_matches_checks_content_signature():
    assert WelcomeToTheJungleExtractor.matches(
        make_welcome_to_the_jungle_job_page(),
        source_url="https://app.welcometothejungle.com/jobs/example",
    ) is True
    assert WelcomeToTheJungleExtractor.matches(make_generic_job_page()) is False


def test_wttj_extractor_extracts_company_and_structured_sections():
    job = WelcomeToTheJungleExtractor.from_string(
        make_welcome_to_the_jungle_job_page(),
        source_url="https://app.welcometothejungle.com/jobs/example",
    ).extract()

    assert job.title == "Software Engineer"
    assert job.company == "Example Co"
    assert job.salary == "$120k + Equity"
    assert job.experience == "Junior, Mid"
    assert job.locations == ["Remote from US", "Remote from Canada"]
    assert job.technologies == ["Python", "GraphQL", "AWS"]
    assert job.company_sector_tags == ["SaaS", "Developer Tools"]
    assert job.data_testid_values is not None
    assert job.data_testid_values["salary-section"] == ["$120k + Equity"]
    assert "job-technology-used" in job.data_testid_values
    assert "company-sector-tags" in job.data_testid_values
    assert "Build internal tools" in job.to_markdown()
    assert "Home office stipend" in job.to_markdown()
    assert "- **Company:** Example Co" in job.to_markdown()
    assert "- **Salary:** $120k + Equity" in job.to_markdown()
    assert "- **Experience:** Junior, Mid" in job.to_markdown()
    assert "- **Locations:** Remote from US, Remote from Canada" in job.to_markdown()
    assert "- **Technologies:** Python, GraphQL, AWS" in job.to_markdown()
    assert "- **Sectors:** SaaS, Developer Tools" in job.to_markdown()


def test_extract_job_posting_prefers_wttj_extractor_when_available():
    job = extract_job_posting(
        make_welcome_to_the_jungle_job_page(),
        source_url="https://app.welcometothejungle.com/jobs/example",
    )

    assert job.company == "Example Co"
    assert job.salary == "$120k + Equity"
    assert "# Skills" in job.to_markdown()
    assert job.technologies == ["Python", "GraphQL", "AWS"]


def test_generic_html_extractor_uses_title_when_h1_is_missing():
    html = """\
<html>
  <head><title>Staff Data Engineer</title></head>
  <body>
    <article>
      <p>This role owns the analytics platform and event pipelines for internal teams.</p>
      <h2>Qualifications</h2>
      <p>Python, SQL, and warehouse design experience.</p>
    </article>
  </body>
</html>
"""

    job = GenericHtmlExtractor.from_string(html).extract()

    assert job.title == "Staff Data Engineer"
    assert "analytics platform" in job.to_markdown()


def test_cli_writes_markdown_file(capsys, tmp_path: Path):
    saved_page = tmp_path / "posting.html"
    saved_page.write_text(make_saved_page("<p>Converted</p>"), encoding="utf-8")

    exit_code = cli.main([str(saved_page)])
    captured = capsys.readouterr()
    output_file = tmp_path / "posting.md"

    assert exit_code == 0
    assert output_file.read_text(encoding="utf-8") == "# Test Job\n\nConverted\n"
    assert output_file.exists()
    assert captured.out == "Using UpworkExtractor...\n"
    assert captured.err == ""


def test_cli_writes_markdown_file_to_explicit_output_path(capsys, tmp_path: Path):
    saved_page = tmp_path / "posting.html"
    output_file = tmp_path / "custom-output.md"
    saved_page.write_text(make_saved_page("<p>Converted</p>"), encoding="utf-8")

    exit_code = cli.main([str(saved_page), str(output_file)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == "# Test Job\n\nConverted\n"
    assert captured.out == "Using UpworkExtractor...\n"
    assert captured.err == ""
    assert not (tmp_path / "posting.md").exists()


def test_cli_writes_markdown_file_for_url(monkeypatch, capsys, tmp_path: Path):
    html = make_saved_page("<p>Converted</p>", title="Remote Role")

    class MockHeaders:
        @staticmethod
        def get_content_charset() -> str:
            return "utf-8"

    class MockResponse:
        headers = MockHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return html.encode("utf-8")

    def mock_urlopen(url: str) -> MockResponse:
        assert url == "https://example.com/jobs/senior-python-developer"
        return MockResponse()

    monkeypatch.setattr(cli, "urlopen", mock_urlopen)
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["https://example.com/jobs/senior-python-developer"])
    captured = capsys.readouterr()
    output_file = tmp_path / "senior-python-developer.md"

    assert exit_code == 0
    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == "# Remote Role\n\nConverted\n"
    assert captured.out == "Using UpworkExtractor...\n"
    assert captured.err == ""


def test_cli_writes_url_markdown_file_to_explicit_output_path(monkeypatch, capsys, tmp_path: Path):
    html = make_generic_job_page()

    class MockHeaders:
        @staticmethod
        def get_content_charset() -> str:
            return "utf-8"

    class MockResponse:
        headers = MockHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return html.encode("utf-8")

    output_file = tmp_path / "named-output.md"
    monkeypatch.setattr(cli, "urlopen", lambda _: MockResponse())
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["https://example.com/jobs/senior-python-developer", str(output_file)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert output_file.exists()
    assert "Senior Python Developer" in output_file.read_text(encoding="utf-8")
    assert captured.out == "Using GenericHtmlExtractor...\n"
    assert captured.err == ""
    assert not (tmp_path / "senior-python-developer.md").exists()


def test_cli_writes_index_markdown_file_for_trailing_slash_url(monkeypatch, tmp_path: Path):
    html = make_saved_page("<p>Converted</p>")

    class MockHeaders:
        @staticmethod
        def get_content_charset() -> str:
            return "utf-8"

    class MockResponse:
        headers = MockHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return html.encode("utf-8")

    monkeypatch.setattr(cli, "urlopen", lambda _: MockResponse())
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["https://example.com/jobs/"])

    assert exit_code == 0
    assert (tmp_path / "jobs.md").exists()


def test_cli_writes_markdown_file_for_generic_url(monkeypatch, capsys, tmp_path: Path):
    html = make_generic_job_page()

    class MockHeaders:
        @staticmethod
        def get_content_charset() -> str:
            return "utf-8"

    class MockResponse:
        headers = MockHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return html.encode("utf-8")

    monkeypatch.setattr(cli, "urlopen", lambda _: MockResponse())
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["https://example.com/jobs/senior-python-developer"])
    captured = capsys.readouterr()
    output_file = tmp_path / "senior-python-developer.md"

    assert exit_code == 0
    assert output_file.exists()
    assert "Senior Python Developer" in output_file.read_text(encoding="utf-8")
    assert captured.out == "Using GenericHtmlExtractor...\n"
    assert captured.err == ""


def test_cli_reports_url_fetch_errors(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setattr(cli, "urlopen", lambda _: (_ for _ in ()).throw(OSError("HTTP Error 403: Forbidden")))
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["https://www.upwork.com/jobs/example"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Error: HTTP Error 403: Forbidden\n"


def test_wrong_file_error():
    with pytest.raises(ValueError, match="expected Upwork job data"):
        UpworkExtractor.from_string("<html><body>no payload here</body></html>").extract()


def test_cli_fails_when_input_does_not_contain_html(capsys, tmp_path: Path):
    saved_page = tmp_path / "posting.txt"
    saved_page.write_text("plain text only", encoding="utf-8")

    exit_code = cli.main([str(saved_page)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Error: Input file does not contain HTML.\n"
    assert not (tmp_path / "posting.md").exists()


def test_cli_fails_when_html_has_no_recognizable_job_content(capsys, tmp_path: Path):
    saved_page = tmp_path / "posting.html"
    saved_page.write_text("<html><body><main><p>Too short</p></main></body></html>", encoding="utf-8")

    exit_code = cli.main([str(saved_page)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Error: Could not find recognizable job posting content in this HTML file.\n"
