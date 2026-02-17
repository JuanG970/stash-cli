.PHONY: test test-integration lint install

test:
	python3 -m pytest tests/ -v

lint:
	ruff check src/stash-cli tests/


build:
	rm -rf dist/
	poetry build

install: build
	pipx install dist/*.whl --force
