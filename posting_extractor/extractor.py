from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_tags(value: str) -> str:
    return _normalize_whitespace(re.sub(r"<[^>]+>", " ", value))


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

    def to_markdown(self) -> str:
        body = _render_markdown(self.description_html)
        attachments = self._render_attachments()
        if self.title and body:
            return f"# {self.title}\n\n{body}{attachments}"
        if self.title:
            return f"# {self.title}{attachments}"
        if body:
            return f"{body}{attachments}"
        return attachments.lstrip("\n") if attachments else ""

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
    def from_string(cls, html: str) -> "UpworkExtractor":
        return cls(html)

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

            if not isinstance(flat, list):
                continue

            try:
                root = _revive_devalue(flat)
                root["vuex"]["jobDetails"]["job"]["uid"]
            except (KeyError, TypeError, IndexError):
                continue

            self._state = root
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


def extract_job_posting(html: str, source_url: str | None = None) -> JobPosting:
    if not _contains_html(html):
        raise ValueError(_NOT_HTML_ERROR)

    try:
        return UpworkExtractor.from_string(html).extract_or_raise_mismatch()
    except ExtractorMismatchError:
        return GenericHtmlExtractor.from_string(html, source_url=source_url).extract()
