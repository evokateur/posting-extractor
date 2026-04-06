# posting-extractor

Converts job posting HTML into Markdown.

## Use Case

Useful for Obsidian notes, or job posting content for a CV optimization pipeline.

Works with saved HTML files and direct `http` or `https` job posting URLs.

## Installation

```bash
cd posting-extract
make install
```

## Usage

```bash
posting-extract posting.html
posting-extract posting.html custom.md
```

## Running tests

```bash
make test
```
