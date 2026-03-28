"""
upwork_extractor.cli
~~~~~~~~~~~~~~~~~~~~
Command-line interface for the Upwork job posting extractor.

Usage:
    upwork-extract posting.html
    upwork-extract posting.html --format json
    upwork-extract posting.html --format markdown
    upwork-extract posting.html --format yaml
    upwork-extract posting.html --out job.md
"""

import argparse
import sys
from pathlib import Path

from .extractor import UpworkExtractor


FORMATS = ("yaml", "json", "markdown", "md")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="upwork-extract",
        description="Extract structured data from a saved Upwork job posting HTML file.",
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Path to the saved HTML file",
    )
    parser.add_argument(
        "--format", "-f",
        choices=FORMATS,
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--out", "-o",
        type=Path,
        default=None,
        help="Write output to file instead of stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.file.exists():
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        return 1

    try:
        extractor = UpworkExtractor.from_file(args.file)
        job = extractor.extract()
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    fmt = args.format
    if fmt == "yaml":
        output = job.to_yaml()
    elif fmt == "json":
        output = job.to_json()
    elif fmt in ("markdown", "md"):
        output = job.to_markdown()
    else:
        output = job.to_markdown()

    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"Written to {args.out}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
