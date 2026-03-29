# upwork-extractor 🦷

Converts saved Upwork job posting HTML files into Markdown.

## Use Case

Useful for Obsidian notes, or using the CAPTCHA-protected job posting content for a CV optimization pipeline.

Meant to work with the HTML content of job postings opened in their own window (i.e. the URL having the form `https://www.upwork.com/jobs/<slug>`)

Saving the HTML as "Web page, complete" preserves the full HTTP URLs of attachment links, which will be added to the Markdown in an Attachments section.

## Installation

```bash
cd upwork-extractor
make install
```

## Usage

```bash
upwork-extract posting.html # generates posting.md
```

## Running tests

```bash
make test
```
