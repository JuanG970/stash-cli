.PHONY: install test test-emacs

install:
	uv tool install --force -e .

# pytest is supplied through uv's `--with` overlay so the lockfile stays
# untouched for a test-only dependency.
test:
	uv run --with "pytest>=8,<9" pytest

test-emacs:
	emacs -Q --batch -L . -L tests -l tests/stash-cli-tests.el -f ert-run-tests-batch-and-exit
