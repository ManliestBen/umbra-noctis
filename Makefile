.PHONY: check lint test
check: lint test
lint:
	.venv/bin/python -m ruff check .
test:
	.venv/bin/python -m pytest -q
