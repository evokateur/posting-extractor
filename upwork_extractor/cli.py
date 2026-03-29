import argparse
import sys
from pathlib import Path

from .extractor import UpworkExtractor


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="upwork-extract",
        description="Extract a saved Upwork job posting as Markdown.",
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Path to the saved HTML file",
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

    sys.stdout.write(job.to_markdown())
    return 0


if __name__ == "__main__":
    sys.exit(main())
