from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run each test from a temp CWD so a stray local .env can't leak in."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _reset_temporal_client() -> Iterator[None]:
    """Reset the process-wide Temporal client cache between tests."""
    import froot.workflow.temporal_client as temporal_client

    temporal_client._CLIENT = None
    yield
    temporal_client._CLIENT = None
