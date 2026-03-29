# upwork-extractor

Converts saved Upwork job posting HTML files into Markdown.

## Use Case

Meant to work with the HTML content of job postings opened in their own window, the URL having the form `https://www.upwork.com/jobs/<slug>`. Useful for agentic CV optimization based on the CAPTCHA-protected job posting content or for Obsidian notes.

## Installation

```bash
cd upwork-extractor
make install
```

## Usage

```bash
upwork-extract posting.html > job-posting.md
```

## Running tests

```bash
make test
```
