# The Temporal worker image. Built and pushed to ghcr.io by CI; deployed to the
# DOKS cluster. The GitHub token and the model/OTEL endpoints are read from the
# environment at runtime (never baked in); the worker connects to Temporal.
#
# Unlike a pure-Python worker, froot's image also carries `git` and `npm`: the
# loop shallow-clones the target repo and regenerates its lockfile with
# `npm install --package-lock-only --ignore-scripts` — no node_modules and no
# install scripts, so no project or dependency code ever runs here. The real
# install + tests run in the target repo's own CI (the verification oracle).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# git: clone/branch/push the bump PR. nodejs+npm: lockfile-only regen + version
# lookups (npm view). Slim — no project/dependency code executes in this image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Runtime extras only (the model judge, GitHub/HTTP, OTEL) — not the dev tooling.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-editable \
    --extra ai --extra github --extra otel

# Default entrypoint: the worker. The scan starter runs as a one-shot via a
# `command:` override (uv run --no-sync python -m froot.scan_starter).
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "froot.worker"]
