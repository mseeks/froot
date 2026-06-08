# froot — developer terrain.
# Short, single-purpose targets: each is one tool, easy to read and approve.

.PHONY: sync fmt fmt-check lint type test check worker start

# Install/refresh the dev env (dev tooling + ai + github + otel + sandbox).
sync:
	uv sync --extra dev --extra ai --extra github --extra otel --extra sandbox

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

# Start every configured loop for each FROOT_REPOS repo (one-shot): the acting
# loops in FROOT_LOOPS, plus each enabled advisory loop (FROOT_REVIEW_ENABLED /
# FROOT_A11Y_ENABLED). Re-running is safe — a running loop is left untouched.
start:
	uv run python -m froot.starter
