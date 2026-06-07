"""Catch-tests for the vendored kernel script, and the kernel/brain boundary.

``scripts/check_determinism.py`` runs standalone in CI (``check_determinism.py
src``), which only proves it PASSES on clean code. These tests pin the other
half — that it actually FAILS on hazards, across every banned category — and
demonstrate the one thing the lexical kernel structurally cannot see: a
transitive hazard, which only the brain's analyzer catches.

The kernel is a vendored, package-free script, so it is loaded by file path.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from froot.policy.determinism import LoadedModule, analyze_workflow_surface

if TYPE_CHECKING:
    from collections.abc import Mapping

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_determinism.py"
)


def _load_kernel() -> Any:
    spec = importlib.util.spec_from_file_location("_froot_kernel", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the script's @dataclass can resolve its module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_KERNEL = _load_kernel()


# A workflow class touching every banned category, including the tricky
# resolutions: an aliased import (dt.now) and a from-import (date.today).
_HAZARDS = """
import datetime
import time
import random
import uuid
import os
import asyncio
import threading
import subprocess
import socket
import httpx
from datetime import datetime as dt, date
from temporalio import workflow


@workflow.defn
class Hazards:
    @workflow.run
    async def run(self) -> None:
        datetime.datetime.now()
        datetime.datetime.utcnow()
        date.today()
        dt.now()
        time.time()
        time.sleep(1)
        random.randint(1, 6)
        uuid.uuid4()
        os.getenv("X")
        os.environ["Y"]
        await asyncio.sleep(1)
        threading.Thread()
        subprocess.run(["ls"])
        socket.socket()
        httpx.get("http://x")
        open("/tmp/x")
"""

# Things that LOOK like hazards but aren't: the sanctioned `workflow.*`
# replacements, a type annotation, and wall-clock inside an @activity.defn.
_NEGATIVES = """
import datetime
import os
from temporalio import workflow, activity


@workflow.defn
class Clean:
    @workflow.run
    async def run(self) -> datetime.datetime:  # annotation, not a call
        workflow.now()
        workflow.uuid4()
        workflow.random()
        return workflow.now()


@activity.defn
async def legit() -> None:
    datetime.datetime.now()  # wall-clock is legal in an activity
    os.environ["Z"]
"""


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source)
    return path


def test_kernel_catches_every_banned_category(tmp_path: Path) -> None:
    path = _write(tmp_path, "wf.py", _HAZARDS)
    rules = {finding.rule for finding in _KERNEL.scan_file(path)}
    assert rules == {
        "datetime.datetime.now",  # plain and via the `dt` alias
        "datetime.datetime.utcnow",
        "datetime.date.today",  # via the `date` from-import
        "time.time",
        "time.sleep",
        "random.randint",
        "uuid.uuid4",
        "os.getenv",
        "os.environ",  # attribute access, not a call
        "asyncio.sleep",
        "threading.Thread",
        "subprocess.run",
        "socket.socket",
        "httpx.get",
        "open",
    }


def test_kernel_exit_code_is_nonzero_on_hazards(tmp_path: Path) -> None:
    path = _write(tmp_path, "wf.py", _HAZARDS)
    assert _KERNEL.main([str(path)]) == 1


def test_kernel_ignores_sanctioned_annotations_and_activities(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "wf.py", _NEGATIVES)
    assert _KERNEL.scan_file(path) == []
    assert _KERNEL.main([str(path)]) == 0


# ── The kernel/brain boundary — only the brain catches this ──────────────────
_TRANSITIVE_WORKFLOW = """
from temporalio import workflow
from app.util import stamp


@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return stamp()
"""

_TRANSITIVE_HELPER = """
import datetime


def stamp():
    return datetime.datetime.now()
"""


def _modules(sources: Mapping[str, str]) -> dict[str, LoadedModule]:
    return {
        qual: LoadedModule(
            qualname=qual,
            tree=ast.parse(src),
            lines=tuple(src.splitlines()),
        )
        for qual, src in sources.items()
    }


def test_transitive_hazard_is_invisible_to_kernel_but_caught_by_brain(
    tmp_path: Path,
) -> None:
    # Same code, two layers. The workflow file has NO banned call lexically —
    # the hazard hides one call out, in a plain helper — and the helper file
    # has no @workflow.defn, so the kernel ignores it there too. The lexical,
    # workflow-scoped kernel is structurally blind to this.
    wf_path = _write(tmp_path, "workflow.py", _TRANSITIVE_WORKFLOW)
    helper_path = _write(tmp_path, "util.py", _TRANSITIVE_HELPER)
    assert _KERNEL.scan_file(wf_path) == []
    assert _KERNEL.scan_file(helper_path) == []

    # The brain's call-graph chases the import into the helper and finds it.
    result = analyze_workflow_surface(
        _modules(
            {
                "app.workflow": _TRANSITIVE_WORKFLOW,
                "app.util": _TRANSITIVE_HELPER,
            }
        )
    )
    assert len(result.hazards) == 1
    hazard = result.hazards[0]
    assert hazard.impurity.rule == "datetime.datetime.now"
    assert hazard.via == ("stamp",)


def test_banned_tables_match_the_brain() -> None:
    """The vendored kernel and the brain's analyzer must ban the SAME symbols.

    ``scripts/check_determinism.py`` (the blocking CI gate) and
    :mod:`froot.policy.determinism` (the advisory reviewer) each define four
    hand-copied ``BANNED_*`` tables. If they drift, froot's own gate and its
    reviewer disagree about what "deterministic" means — the exact class of
    decay froot exists to catch, uncaught in froot itself. Pin them equal so the
    duplication can never silently diverge.
    """
    from froot.policy import determinism as brain

    for name in (
        "BANNED_CALLS",
        "BANNED_CALL_MODULES",
        "BANNED_ATTRS",
        "BANNED_BUILTINS",
    ):
        assert getattr(_KERNEL, name) == getattr(brain, name), name
