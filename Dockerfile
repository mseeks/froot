# The Temporal worker image. Built and pushed to ghcr.io by CI; deployed to the
# DOKS cluster. The GitHub token and the model/OTEL endpoints are read from the
# environment at runtime (never baked in); the worker connects to Temporal.
#
# Unlike a pure-Python worker, froot's image also carries `git`, `npm`, and `uv`
# (the base image): the loop shallow-clones the target repo and regenerates its
# lockfile only — `npm install --package-lock-only --ignore-scripts` for npm,
# `uv lock --upgrade-package` for Python — so no node_modules, no virtualenv,
# and no install scripts: no project or dependency code ever runs here. The real
# install + tests run in the target repo's own CI (the verification oracle).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# git: clone/branch/push the bump PR. nodejs+npm: npm lockfile-only regen +
# version lookups (npm view); uv (from the base image) does the same for Python.
# Slim — no project/dependency code executes in this image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# knip: the dead-code loop's signal for npm — a static analyzer (no install, no
# project code) that lists unused dependencies. Pinned and baked in so the scan
# is reproducible and never fetches at runtime; it reads source only, so it needs
# no node_modules, fitting the clone-only worker. (Debian's nodejs 18.19 meets
# knip 5's `>=18.18` engine.)
RUN npm install -g knip@5

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Runtime extras only (model judge, GitHub/HTTP, OTEL, e2b sandbox) — not dev.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-editable \
    --extra ai --extra github --extra otel --extra sandbox

# Default entrypoint: the worker. The scan starter runs as a one-shot via a
# `command:` override (uv run --no-sync python -m froot.scan_starter).
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "froot.worker"]
