.PHONY: install uninstall test

install:
	uv tool install --editable .

uninstall:
	uv tool uninstall posting-extract

test:
	uv run pytest
