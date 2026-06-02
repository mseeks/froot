# froot — developer terrain.
# Short, single-purpose targets: each is one tool, easy to read and approve.

.PHONY: sync fmt fmt-check lint type test check worker start-scan

# Install/refresh the dev env (dev tooling + ai + github + otel extras).
sync:
	uv sync --extra dev --extra ai --extra github --extra otel

# Auto-format (ruff formatter) and fix lint where safe.
fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

# Verify formatting without writing (CI-friendly).
fmt-check:
	uv run ruff format --check src tests

# Lint only (no fixes).
lint:
	uv run ruff check src tests

# Strict type check (the DDD safety net; covers src and tests).
type:
	uv run mypy

# Run the test suite with coverage.
test:
	uv run pytest

# The full gate: format check, lint, types, tests. Keep this green.
check: fmt-check lint type test

# Run the Temporal worker (needs a reachable Temporal server + env config).
worker:
	uv run python -m froot.worker

# Start the durable scan loop for each FROOT_REPOS repo (one-shot).
start-scan:
	uv run python -m froot.scan_starter
