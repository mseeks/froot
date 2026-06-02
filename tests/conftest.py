from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_temporal_client() -> Iterator[None]:
    """Reset the process-wide Temporal client cache between tests."""
    import froot.workflow.temporal_client as temporal_client

    temporal_client._CLIENT = None
    yield
    temporal_client._CLIENT = None
