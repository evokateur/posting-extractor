import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from .extractor import extract_job_posting


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="posting-extract",
        description="Extract a job posting from an HTML file or URL as Markdown.",
    )
    parser.add_argument(
        "input",
        help="Path to the saved HTML file or an http/https URL",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help="Optional path for the generated Markdown file",
    )
    return parser.parse_args(argv)


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _fetch_url_html(url: str) -> str:
    with urlopen(url) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset)


def _build_output_path(input_value: str) -> Path:
    if not _is_url(input_value):
        return Path(input_value).with_suffix(".md")

    parsed = urlparse(input_value)
    slug = Path(parsed.path).name or parsed.netloc or "posting"
    return Path(f"{slug}.md")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if _is_url(args.input):
            job = extract_job_posting(_fetch_url_html(args.input), source_url=args.input)
        else:
            input_file = Path(args.input)
            if not input_file.exists():
                print(f"Error: file not found: {input_file}", file=sys.stderr)
                return 1
            job = extract_job_posting(input_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    output_file = Path(args.output) if args.output else _build_output_path(args.input)
    output_file.write_text(job.to_markdown(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
