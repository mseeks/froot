"""The read-only agentic executor: the jail (security crux) + an offline run.

The jail is the load-bearing safety — the agent must never read outside the
checkout or touch a secret — so it is pinned hard. The offline run (a
``TestModel`` that exercises every tool, then returns the structured output)
proves the wiring without a real model.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from froot.adapters.agentic_executor import (
    _denied,
    _resolve,
    run_readonly_agent,
)


class _Out(BaseModel):
    summary: str


def test_jail_allows_in_scope_blocks_escape_and_secrets(tmp_path: Path):
    (tmp_path / "doc.md").write_text("x")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / ".git").mkdir()
    assert _resolve(tmp_path, "doc.md") is not None
    assert _resolve(tmp_path, "../escape") is None  # escapes the root
    assert _resolve(tmp_path, ".env") is None  # secret denied
    assert _resolve(tmp_path, ".git/config") is None  # vcs denied


def test_denied_flags_keys_and_secret_named_paths():
    assert _denied(("config.key",)) is True
    assert _denied(("my", "secrets.json")) is True
    assert _denied(("private.pem",)) is True
    assert _denied(("src", "app.py")) is False


async def test_run_returns_structured_output_offline(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Title\nbody\n")
    out, status = await run_readonly_agent(
        model=TestModel(),
        root=tmp_path,
        system_prompt="map drift",
        task="review the docs against the code",
        output_type=_Out,
        max_requests=5,
    )
    assert status == "completed"
    assert isinstance(out, _Out)
