from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from markdownify import markdownify


_DEVALUE_SPECIAL_TAGS = frozenset({
    "Reactive", "Set", "Map", "Date", "RegExp", "Error",
    "URL", "BigInt", "undefined", "NaN", "Infinity", "-Infinity", "-0",
})

_WRONG_FILE_ERROR = """\
Could not find Upwork job data in this HTML file.

This usually means the page was saved while the job was open as a slide-over
panel on the Find Work page, rather than as a standalone tab.

To fix this:
  1. Click the job title to open it in its own browser tab.
     (The URL should contain /freelance-jobs/apply/...)
  2. Save that page as HTML: File → Save Page As → "Webpage, HTML Only".
  3. Re-run this tool on the newly saved file.
"""


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


@dataclass
class ExtractedJob:
    title: str
    description_html: str

    def to_markdown(self) -> str:
        body = _render_markdown(self.description_html)
        if self.title and body:
            return f"# {self.title}\n\n{body}\n"
        if self.title:
            return f"# {self.title}\n"
        return f"{body}\n" if body else ""


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

        raise ValueError(_WRONG_FILE_ERROR)

    def extract(self) -> ExtractedJob:
        job = self._get_state()["vuex"]["jobDetails"]["job"]
        description_html = self._extract_description(job)
        return ExtractedJob(
            title=job.get("title", "").strip(),
            description_html=description_html,
        )

    def _extract_description(self, job: dict[str, Any]) -> str:
        for field_name in ("descriptionHtml", "description", "legacyCiphertextDescription"):
            value = job.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
