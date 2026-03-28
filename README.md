# upwork-extractor 🦷

Extracts structured job data from saved Upwork job posting HTML files.
Outputs Markdown, YAML, or JSON.

## How to save the HTML file correctly

**You must open the job in its own browser tab before saving.**

1. Click the job title so it opens at a URL like:
   `https://www.upwork.com/freelance-jobs/apply/<slug>_~0<uid>/`
2. Save the page: **File → Save Page As → "Webpage, HTML Only"**

If you save the Find Work page while the job is open as a slide-over panel,
the tool will tell you what went wrong and how to fix it.

## Installation

```bash
uv tool install /absolute/path/to/this-project-directory
```

If `upwork-extract` is not found after installation:

```bash
uv tool update-shell
```

## Local fixture for tests

`tests/fixtures/sample.html` is not committed.

To run the tests, save a real Upwork job posting page there:

```bash
cp /path/to/saved-posting.html tests/fixtures/sample.html
```

## Usage

```bash
upwork-extract posting.html                  # Markdown to stdout (default)
upwork-extract posting.html --format json
upwork-extract posting.html --format yaml
upwork-extract posting.html --out job.md     # write to file
```

## Running tests

```bash
uv sync
uv run pytest tests/
```
