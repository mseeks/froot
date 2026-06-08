# froot — developer terrain.
# Short, single-purpose targets: each is one tool, easy to read and approve.

.PHONY: sync fmt fmt-check lint type test check worker start-scan start-review start-a11y

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

# Start the durable scan loop for each FROOT_REPOS repo (one-shot).
start-scan:
	uv run python -m froot.scan_starter

# Start the durable determinism-review loop for each FROOT_REPOS repo (one-shot).
start-review:
	uv run python -m froot.review_starter

# Start the durable a11y-review loop for each FROOT_REPOS repo (one-shot).
# No-op unless FROOT_A11Y_ENABLED is set (the loop opts in deliberately).
start-a11y:
	uv run python -m froot.a11y_review_starter
