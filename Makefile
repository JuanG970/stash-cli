build:
	poetry build

install: build
	pipx install dist/*.whl --force
