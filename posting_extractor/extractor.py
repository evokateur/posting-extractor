from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from markdownify import markdownify


_DEVALUE_SPECIAL_TAGS = frozenset({
    "Reactive", "Set", "Map", "Date", "RegExp", "Error",
    "URL", "BigInt", "undefined", "NaN", "Infinity", "-Infinity", "-0",
})

_WRONG_FILE_ERROR = """\
Could not find the expected Upwork job data in this HTML file.
"""
_GENERIC_EXTRACTION_ERROR = "Could not find recognizable job posting content in this HTML file."
_NOT_HTML_ERROR = "Input file does not contain HTML."
_UPWORK_BASE_URL = "https://www.upwork.com"
_WELCOME_TO_THE_JUNGLE_HOSTS = frozenset({
    "app.welcometothejungle.com",
    "welcometothejungle.com",
})
_WELCOME_TO_THE_JUNGLE_EXPERIENCE_LEVELS = (
    ("Junior", re.compile(r"\bJunior\b", re.IGNORECASE)),
    ("Mid", re.compile(r"\bMid\b", re.IGNORECASE)),
    ("Senior", re.compile(r"\bSenior\b", re.IGNORECASE)),
    ("Expert", re.compile(r"\bExpert\b", re.IGNORECASE)),
)
_WELCOME_TO_THE_JUNGLE_TESTIDS = (
    "job-technology-used",
    "company-sector-tags",
    "experience-section",
    "job-locations",
    "salary-section",
)
_CONTENT_KEYWORDS = (
    "job description",
    "about the role",
    "about this role",
    "responsibilities",
    "requirements",
    "qualifications",
    "what you'll do",
    "what you will do",
    "about you",
)
_JUNK_TAGS = ("script", "style", "nav", "footer", "noscript", "svg", "form")
_JUNK_CLASS_PATTERNS = (
    "cookie",
    "consent",
    "newsletter",
    "share",
    "social",
    "banner",
    "header",
    "footer",
    "menu",
    "modal",
)
_ATTACHMENT_PATTERNS = (".pdf", ".doc", ".docx", ".rtf", "attachment", "download")


class ExtractorMismatchError(ValueError):
    pass


class _DataTestIdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._stack: list[dict[str, Any]] = []
        self.results: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        self._stack.append(
            {
                "tag": tag,
                "testid": attrs_dict.get("data-testid"),
                "parts": [],
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return

        frame = self._stack.pop()
        if frame["tag"] != tag:
            return

        testid = frame["testid"]
        if not testid:
            return

        value = _normalize_whitespace("".join(frame["parts"]))
        if not value:
            return

        values = self.results.setdefault(testid, [])
        if value not in values:
            values.append(value)

        for parent in reversed(self._stack):
            if not parent["testid"]:
                continue
            if parent["parts"] and not parent["parts"][-1].endswith((", ", " ", "\n", "\t")):
                parent["parts"].append(", ")
            parent["parts"].append(value)

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return

        for frame in reversed(self._stack):
            if not frame["testid"]:
                continue
            frame["parts"].append(data)
            break


class _ChildTextExtractor(HTMLParser):
    def __init__(self, container_testid: str):
        super().__init__()
        self._container_testid = container_testid
        self._container_depth = 0
        self._child_depth = 0
        self._child_parts: list[str] = []
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if attrs_dict.get("data-testid") == self._container_testid:
            self._container_depth += 1
            return

        if self._container_depth == 1:
            self._child_depth = 1
            self._child_parts = []
            return

        if self._child_depth > 0:
            self._child_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._child_depth > 0:
            self._child_depth -= 1
            if self._child_depth == 0:
                value = _normalize_whitespace("".join(self._child_parts))
                if value and value not in self.values:
                    self.values.append(value)
            return

        if self._container_depth > 0:
            self._container_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._child_depth > 0:
            self._child_parts.append(data)


class _FlatTextExtractor(HTMLParser):
    def __init__(self, container_testid: str):
        super().__init__()
        self._container_testid = container_testid
        self._capture_depth = 0
        self._parts: list[str] = []
        self.value = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if attrs_dict.get("data-testid") == self._container_testid:
            self._capture_depth = 1
            return

        if self._capture_depth > 0:
            self._capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture_depth == 0:
            return

        self._capture_depth -= 1
        if self._capture_depth == 0:
            self.value = _normalize_whitespace(" ".join(self._parts))

    def handle_data(self, data: str) -> None:
        if self._capture_depth == 0:
            return

        value = data.strip()
        if value:
            self._parts.append(value)


def _contains_upwork_job_payload(flat_data: Any) -> bool:
    if not isinstance(flat_data, list):
        return False

    try:
        root = _revive_devalue(flat_data)
        return bool(root["vuex"]["jobDetails"]["job"]["uid"])
    except (KeyError, TypeError, IndexError):
        return False


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_tags(value: str) -> str:
    return _normalize_whitespace(re.sub(r"<[^>]+>", " ", value))


def _dedupe_repeated_phrase(value: str) -> str:
    normalized = _normalize_whitespace(value)
    words = normalized.split()
    if len(words) % 2 == 0:
        midpoint = len(words) // 2
        if words[:midpoint] == words[midpoint:]:
            return " ".join(words[:midpoint])
    return normalized


def _contains_html(content: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][^>]*>", content))


def _render_markdown(html: str) -> str:
    content = html.strip()
    if not content:
        return ""
    if "<" not in content or ">" not in content:
        return content
    markdown = markdownify(
        content,
        heading_style="ATX",
        bullets="-",
        strong_em_symbol="*",
    )
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


def _extract_json_ld_blocks(html: str) -> list[Any]:
    blocks = []
    pattern = re.compile(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        raw_json = match.group(1).strip()
        if '"JobPosting"' not in raw_json:
            continue

        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, list):
            blocks.extend(item for item in parsed if isinstance(item, dict))
            continue

        if isinstance(parsed, dict):
            blocks.append(parsed)

    return blocks


def _resolve_relative_links(html: str, source_url: str | None) -> str:
    if not source_url:
        return html

    def replace(match: re.Match[str]) -> str:
        attr_name = match.group(1)
        quote = match.group(2)
        raw_value = match.group(3)
        resolved = urljoin(source_url, raw_value)
        return f'{attr_name}={quote}{resolved}{quote}'

    return re.sub(r'(href|src)=(["\'])(.*?)\2', replace, html, flags=re.IGNORECASE)


def _extract_tag_content(html: str, tag_name: str) -> list[str]:
    pattern = re.compile(
        rf"<{tag_name}\b[^>]*>(.*?)</{tag_name}>",
        re.IGNORECASE | re.DOTALL,
    )
    return [match.group(1).strip() for match in pattern.finditer(html)]


def _extract_tag_blocks(html: str, tag_name: str) -> list[str]:
    pattern = re.compile(
        rf"<{tag_name}\b[^>]*>.*?</{tag_name}>",
        re.IGNORECASE | re.DOTALL,
    )
    return [match.group(0).strip() for match in pattern.finditer(html)]


def _remove_junk_blocks(html: str) -> str:
    cleaned = html
    for tag_name in _JUNK_TAGS:
        cleaned = re.sub(
            rf"<{tag_name}\b[^>]*>.*?</{tag_name}>",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )

    class_pattern = "|".join(re.escape(pattern) for pattern in _JUNK_CLASS_PATTERNS)
    cleaned = re.sub(
        rf"<(?P<tag>\w+)\b[^>]*(?:class|id)=['\"][^'\"]*(?:{class_pattern})[^'\"]*['\"][^>]*>.*?</(?P=tag)>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned


def _extract_title_from_html(html: str) -> str:
    for candidate in _extract_tag_content(html, "h1"):
        text = _strip_tags(candidate)
        if text:
            return text

    title_matches = _extract_tag_content(html, "title")
    if title_matches:
        return _strip_tags(title_matches[0])

    return ""


def _extract_heading_texts(html: str, tag_name: str) -> list[str]:
    headings = []
    for candidate in _extract_tag_content(html, tag_name):
        text = _strip_tags(candidate)
        if text:
            headings.append(text)
    return headings


def _score_candidate_block(block_html: str) -> int:
    text = _strip_tags(block_html)
    if not text:
        return 0

    text_lower = text.lower()
    score = len(text)
    if any(keyword in text_lower for keyword in _CONTENT_KEYWORDS):
        score += 1000
    if "<h1" in block_html.lower():
        score += 500
    if "<h2" in block_html.lower():
        score += 250
    return score


def _extract_description_block(html: str) -> str:
    candidates: list[str] = []
    for tag_name in ("main", "article"):
        candidates.extend(_extract_tag_blocks(html, tag_name))

    role_pattern = re.compile(
        r"<(?P<tag>\w+)\b[^>]*role=['\"]main['\"][^>]*>.*?</(?P=tag)>",
        re.IGNORECASE | re.DOTALL,
    )
    candidates.extend(match.group(0).strip() for match in role_pattern.finditer(html))

    section_pattern = re.compile(
        r"<(?P<tag>section|div)\b[^>]*>.*?</(?P=tag)>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in section_pattern.finditer(html):
        block_html = match.group(0).strip()
        block_text = _strip_tags(block_html).lower()
        if any(keyword in block_text for keyword in _CONTENT_KEYWORDS):
            candidates.append(block_html)

    candidates.append(html)

    best_block = ""
    best_score = 0
    for candidate in candidates:
        cleaned = _remove_junk_blocks(candidate)
        score = _score_candidate_block(cleaned)
        if score > best_score:
            best_block = cleaned
            best_score = score

    return best_block.strip()


def _extract_links(html: str, source_url: str | None) -> list["Attachment"]:
    links: list[Attachment] = []
    link_pattern = re.compile(
        r"<a\b[^>]*href=['\"](.*?)['\"][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in link_pattern.finditer(html):
        href = match.group(1).strip()
        label = _strip_tags(match.group(2))
        if not href:
            continue

        resolved_href = urljoin(source_url, href) if source_url else href
        href_text = f"{resolved_href} {label}".lower()
        if not any(pattern in href_text for pattern in _ATTACHMENT_PATTERNS):
            continue

        file_name = label or Path(resolved_href).name or resolved_href
        links.append(Attachment(file_name=file_name, url=resolved_href))

    return links


def _extract_data_testid_values(html: str) -> dict[str, list[str]]:
    parser = _DataTestIdParser()
    parser.feed(html)
    parser.close()
    return parser.results


def _extract_child_texts_from_testid_container(html: str, container_testid: str) -> list[str]:
    parser = _ChildTextExtractor(container_testid)
    parser.feed(html)
    parser.close()
    return parser.values


def _extract_flat_text_from_testid_container(html: str, container_testid: str) -> str:
    parser = _FlatTextExtractor(container_testid)
    parser.feed(html)
    parser.close()
    return _dedupe_repeated_phrase(parser.value)


def _revive_devalue(data: list[Any]) -> Any:
    cache: dict[int, Any] = {}

    def resolve(index: int) -> Any:
        if index in cache:
            return cache[index]

        item = data[index]

        if isinstance(item, dict):
            result: dict[str, Any] = {}
            cache[index] = result
            for key, value in item.items():
                result[key] = resolve(value)
            return result

        if isinstance(item, list):
            if item and isinstance(item[0], str) and item[0] in _DEVALUE_SPECIAL_TAGS:
                tag = item[0]
                if tag == "Reactive":
                    resolved = resolve(item[1])
                    cache[index] = resolved
                    return resolved
                if tag == "Date":
                    cache[index] = item[1]
                    return item[1]
                cache[index] = None
                return None

            result_list: list[Any] = []
            cache[index] = result_list
            for value in item:
                result_list.append(resolve(value))
            return result_list

        cache[index] = item
        return item

    header = data[0]
    root_index = header[1] if isinstance(header, list) and header[0] == "Reactive" else 1
    return resolve(root_index)


@dataclass
class Attachment:
    file_name: str
    url: str


@dataclass
class JobPosting:
    title: str
    description_html: str
    attachments: list[Attachment]
    company: str = ""
    salary: str = ""
    experience: str = ""
    locations: list[str] | None = None
    technologies: list[str] | None = None
    company_sector_tags: list[str] | None = None
    data_testid_values: dict[str, list[str]] | None = None

    def to_markdown(self) -> str:
        body = _render_markdown(self.description_html)
        attachments = self._render_attachments()
        metadata = self._render_metadata()
        if self.title and body:
            return f"# {self.title}\n\n{metadata}{body}{attachments}"
        if self.title:
            return f"# {self.title}{attachments}" if not metadata else f"# {self.title}\n\n{metadata.rstrip()}{attachments}"
        if self.company and body:
            return f"{metadata}{body}{attachments}"
        if metadata:
            return f"{metadata.rstrip()}{attachments}"
        if body:
            return f"{body}{attachments}"
        return attachments.lstrip("\n") if attachments else ""

    def _render_metadata(self) -> str:
        lines = []
        if self.company:
            lines.append(f"- **Company:** {self.company}")
        if self.salary:
            lines.append(f"- **Salary:** {self.salary}")
        if self.experience:
            lines.append(f"- **Experience:** {self.experience}")
        if self.locations:
            lines.append(f"- **Locations:** {', '.join(self.locations)}")
        if self.technologies:
            lines.append(f"- **Technologies:** {', '.join(self.technologies)}")
        if self.company_sector_tags:
            lines.append(f"- **Sectors:** {', '.join(self.company_sector_tags)}")
        if not lines:
            return ""
        return "\n".join(lines) + "\n\n"

    def _render_attachments(self) -> str:
        if not self.attachments:
            return "\n"

        lines = ["", "", "## Attachments", ""]
        for attachment in self.attachments:
            lines.append(f"- [{attachment.file_name}]({attachment.url})")
        return "\n".join(lines) + "\n"


ExtractedJob = JobPosting


class UpworkExtractor:
    _PAYLOAD_RE = re.compile(
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        re.DOTALL,
    )

    def __init__(self, html: str):
        self._html = html
        self._state: dict[str, Any] | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "UpworkExtractor":
        return cls(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def from_string(cls, html: str, source_url: str | None = None) -> "UpworkExtractor":
        return cls(html)

    @classmethod
    def matches(cls, html: str, source_url: str | None = None) -> bool:
        if not _contains_html(html):
            return False

        for raw_json in cls._PAYLOAD_RE.findall(html):
            try:
                flat = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            if _contains_upwork_job_payload(flat):
                return True

        return False

    def _get_state(self) -> dict[str, Any]:
        if self._state is not None:
            return self._state

        if not _contains_html(self._html):
            raise ValueError(_NOT_HTML_ERROR)

        for raw_json in self._PAYLOAD_RE.findall(self._html):
            try:
                flat = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            if not _contains_upwork_job_payload(flat):
                continue

            self._state = _revive_devalue(flat)
            return self._state

        raise ExtractorMismatchError(_WRONG_FILE_ERROR)

    def extract(self) -> JobPosting:
        try:
            return self.extract_or_raise_mismatch()
        except ExtractorMismatchError as error:
            raise ValueError(str(error)) from error

    def extract_or_raise_mismatch(self) -> JobPosting:
        job = self._get_state()["vuex"]["jobDetails"]["job"]
        description_html = self._extract_description(job)
        return JobPosting(
            title=job.get("title", "").strip(),
            description_html=description_html,
            attachments=self._extract_attachments(job),
        )

    def _extract_description(self, job: dict[str, Any]) -> str:
        for field_name in ("descriptionHtml", "description", "legacyCiphertextDescription"):
            value = job.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _extract_attachments(self, job: dict[str, Any]) -> list[Attachment]:
        attachments = job.get("attachments")
        if not isinstance(attachments, list):
            return []

        extracted_attachments = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue

            file_name = attachment.get("fileName")
            uri = attachment.get("uri")
            if not isinstance(file_name, str) or not file_name.strip():
                continue
            if not isinstance(uri, str) or not uri.startswith("/"):
                continue

            extracted_attachments.append(
                Attachment(
                    file_name=file_name.strip(),
                    url=f"{_UPWORK_BASE_URL}{uri}",
                )
            )

        return extracted_attachments


class GenericHtmlExtractor:
    def __init__(self, html: str, source_url: str | None = None):
        self._html = html
        self._source_url = source_url

    @classmethod
    def from_string(cls, html: str, source_url: str | None = None) -> "GenericHtmlExtractor":
        return cls(html, source_url=source_url)

    @classmethod
    def matches(cls, html: str, source_url: str | None = None) -> bool:
        if not _contains_html(html):
            return False

        description_html = _extract_description_block(html)
        body_text = _strip_tags(description_html)
        title = _extract_title_from_html(html)
        return len(body_text) >= 80 or bool(title)

    def extract(self) -> JobPosting:
        if not _contains_html(self._html):
            raise ValueError(_NOT_HTML_ERROR)

        description_html = _extract_description_block(self._html)
        description_html = _resolve_relative_links(description_html, self._source_url)
        title = _extract_title_from_html(self._html)
        attachments = _extract_links(description_html, self._source_url)
        body_text = _strip_tags(description_html)

        if len(body_text) < 80 and not title:
            raise ValueError(_GENERIC_EXTRACTION_ERROR)

        return JobPosting(
            title=title,
            description_html=description_html,
            attachments=attachments,
        )


class WelcomeToTheJungleExtractor:
    _FIELD_EXTRACTORS = {
        "technologies": ("job-technology-used", "container_children"),
        "company_sector_tags": ("company-sector-tags", "container_children"),
        "salary": ("salary-section", "bucket_first"),
        "experience": ("experience-section", "experience_levels"),
        "locations": ("job-locations", "container_children"),
    }

    def __init__(self, html: str, source_url: str | None = None):
        self._html = html
        self._source_url = source_url
        self._job_posting: dict[str, Any] | None = None

    @classmethod
    def from_string(
        cls,
        html: str,
        source_url: str | None = None,
    ) -> "WelcomeToTheJungleExtractor":
        return cls(html, source_url=source_url)

    @classmethod
    def matches(cls, html: str, source_url: str | None = None) -> bool:
        if not _contains_html(html):
            return False

        has_job_posting = cls._find_job_posting(html) is not None
        if not has_job_posting:
            return False

        has_wttj_marker = cls._is_wttj_source(source_url) or "Welcome to the Jungle" in html
        if has_wttj_marker:
            return True

        data_testid_values = _extract_data_testid_values(html)
        return any(testid in data_testid_values for testid in _WELCOME_TO_THE_JUNGLE_TESTIDS)

    @classmethod
    def _is_wttj_source(cls, source_url: str | None) -> bool:
        if not source_url:
            return False

        host = urlparse(source_url).netloc.lower()
        return any(host == allowed_host or host.endswith(f".{allowed_host}") for allowed_host in _WELCOME_TO_THE_JUNGLE_HOSTS)

    @classmethod
    def _find_job_posting(cls, html: str) -> dict[str, Any] | None:
        for block in _extract_json_ld_blocks(html):
            if block.get("@type") != "JobPosting":
                continue
            if not isinstance(block.get("hiringOrganization"), dict):
                continue
            return block
        return None

    def extract(self) -> JobPosting:
        if not _contains_html(self._html):
            raise ValueError(_NOT_HTML_ERROR)

        job_posting = self._job_posting or self._find_job_posting(self._html)
        if job_posting is None:
            raise ValueError(_GENERIC_EXTRACTION_ERROR)

        self._job_posting = job_posting
        company = self._extract_company(job_posting)
        description_html = self._build_description_html(job_posting)
        attachments = _extract_links(description_html, self._source_url)
        data_testid_values = _extract_data_testid_values(self._html)
        normalized_fields = self._extract_structured_fields(data_testid_values)

        return JobPosting(
            title=_normalize_whitespace(str(job_posting.get("title", ""))),
            company=company,
            salary=self._coerce_string_field(normalized_fields.get("salary")),
            experience=self._coerce_string_field(normalized_fields.get("experience")),
            locations=self._coerce_list_field(normalized_fields.get("locations")),
            description_html=description_html,
            attachments=attachments,
            technologies=self._coerce_list_field(normalized_fields.get("technologies")),
            company_sector_tags=self._coerce_list_field(normalized_fields.get("company_sector_tags")),
            data_testid_values=data_testid_values,
        )

    def _extract_company(self, job_posting: dict[str, Any]) -> str:
        organization = job_posting.get("hiringOrganization")
        if not isinstance(organization, dict):
            return ""
        return _normalize_whitespace(str(organization.get("name", "")))

    def _build_description_html(self, job_posting: dict[str, Any]) -> str:
        sections = []
        description = self._clean_html_field(job_posting.get("description"))
        responsibilities = self._clean_html_field(job_posting.get("responsibilities"))
        skills = self._clean_html_field(job_posting.get("skills"))
        benefits = self._clean_html_field(job_posting.get("jobBenefits"))

        if description:
            sections.append(description)
        if responsibilities and responsibilities not in sections:
            sections.append(f"<h1>Responsibilities</h1>\n{responsibilities}")
        if skills and skills not in sections:
            sections.append(f"<h1>Skills</h1>\n{skills}")
        if benefits and benefits not in sections:
            sections.append(f"<h1>Benefits</h1>\n{benefits}")

        return "\n\n".join(section for section in sections if section).strip()

    def _clean_html_field(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""

        cleaned = value.strip()
        if not cleaned:
            return ""

        cleaned = re.sub(r"</li>\s*,\s*<li", "</li><li", cleaned)
        return cleaned.strip()

    def _extract_structured_fields(
        self,
        data_testid_values: dict[str, list[str]],
    ) -> dict[str, list[str] | str]:
        structured_fields: dict[str, list[str] | str] = {}
        for field_name, (testid, strategy) in self._FIELD_EXTRACTORS.items():
            if strategy == "container_children":
                values = _extract_child_texts_from_testid_container(self._html, testid)
                if values:
                    structured_fields[field_name] = values
                continue

            if strategy == "bucket_first":
                value = _extract_flat_text_from_testid_container(self._html, testid)
                if value:
                    structured_fields[field_name] = value
                    continue

                values = data_testid_values.get(testid, [])
                if values:
                    structured_fields[field_name] = values[0]
                continue

            if strategy == "experience_levels":
                value = _extract_flat_text_from_testid_container(self._html, testid)
                if value:
                    levels = self._extract_experience_levels(value)
                    if levels:
                        structured_fields[field_name] = ", ".join(levels)
                        continue
                    structured_fields[field_name] = value

        return structured_fields

    def _coerce_list_field(self, value: list[str] | str | None) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value:
            return [value]
        return []

    def _coerce_string_field(self, value: list[str] | str | None) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            return value[0]
        return ""

    def _extract_experience_levels(self, value: str) -> list[str]:
        levels = []
        for label, pattern in _WELCOME_TO_THE_JUNGLE_EXPERIENCE_LEVELS:
            if pattern.search(value):
                levels.append(label)
        return levels


def select_extractor(html: str, source_url: str | None = None) -> type[Any]:
    if not _contains_html(html):
        raise ValueError(_NOT_HTML_ERROR)

    extractors = (UpworkExtractor, WelcomeToTheJungleExtractor, GenericHtmlExtractor)
    for extractor in extractors:
        if extractor.matches(html, source_url=source_url):
            return extractor

    raise ValueError(_GENERIC_EXTRACTION_ERROR)


def extract_job_posting(html: str, source_url: str | None = None) -> JobPosting:
    extractor = select_extractor(html, source_url=source_url)
    return extractor.from_string(html, source_url=source_url).extract()
