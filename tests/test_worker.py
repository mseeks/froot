"""The worker entrypoint's process-wide logging configuration.

These pin the one behaviour the deploy depends on: after ``configure_logging``
the structured ``loop_outcome`` lines the activities emit at INFO actually reach
stdout (so the ClickStack filelog and ``kubectl logs`` are not empty), while the
chatty Temporal SDK is held at WARNING so they are not buried.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import pytest

from froot.worker import configure_logging

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Save and restore global logger state so these tests don't leak."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_root_level = root.level
    saved_temporal_level = logging.getLogger("temporalio").level
    # Start from a clean slate so a handler we add binds to the test's stdout.
    root.handlers.clear()
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_root_level)
        logging.getLogger("temporalio").setLevel(saved_temporal_level)


def test_configure_logging_sets_info_stdout_handler_and_quiets_temporalio() -> (
    None
):
    configure_logging()

    root = logging.getLogger()
    assert root.level == logging.INFO
    assert any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
        for h in root.handlers
    )
    assert logging.getLogger("temporalio").level == logging.WARNING


def test_outcome_line_reaches_stdout_verbatim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()

    # Mirrors what activities.record_outcome emits: a JSON line at INFO.
    logging.getLogger("froot.outcome").info('{"event": "loop_outcome", "n": 1}')

    out = capsys.readouterr().out
    assert '{"event": "loop_outcome", "n": 1}' in out


def test_info_is_dropped_without_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The bug this guards against: an unconfigured logger defaults to WARNING,
    # so the INFO outcome line is silently dropped. (No configure_logging call.)
    logging.getLogger("froot.outcome").info('{"event": "loop_outcome"}')

    assert "loop_outcome" not in capsys.readouterr().out


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()

    stdout_handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
    ]
    assert len(stdout_handlers) == 1
