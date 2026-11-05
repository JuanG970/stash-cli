.PHONY: install test

install:
	uv tool install --force -e .

# pytest is supplied through uv's `--with` overlay so the lockfile stays
# untouched for a test-only dependency.
test:
	uv run --with "pytest>=8,<9" pytest
