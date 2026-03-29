.PHONY: install uninstall test

install:
	uv tool install --editable .

uninstall:
	uv tool uninstall upwork-extractor

test:
	uv run pytest
