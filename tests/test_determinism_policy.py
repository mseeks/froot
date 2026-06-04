"""Pure tests for the transitive determinism analyzer.

Build synthetic module sets from source strings, then assert what the call-graph
walk surfaces: transitive hazards (depth 1 and 2), the depth bound, lexical
separation (self-methods are the kernel's), and the third-party frontier.
"""

from __future__ import annotations

import ast

from froot.policy.determinism import LoadedModule, analyze_workflow_surface


def _modules(sources: dict[str, str]) -> dict[str, LoadedModule]:
    return {
        qual: LoadedModule(
            qualname=qual,
            tree=ast.parse(src),
            lines=tuple(src.splitlines()),
        )
        for qual, src in sources.items()
    }


_WF_CALLS_STAMP = """
from temporalio import workflow
from app.util import stamp

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return stamp()
"""

_UTIL_STAMP_DIRTY = """
import datetime

def stamp():
    return datetime.datetime.now()
"""


def test_transitive_hazard_depth_one():
    result = analyze_workflow_surface(
        _modules(
            {"app.workflow": _WF_CALLS_STAMP, "app.util": _UTIL_STAMP_DIRTY}
        ),
        max_depth=2,
    )
    assert len(result.hazards) == 1
    hazard = result.hazards[0]
    assert hazard.impurity.rule == "datetime.datetime.now"
    assert hazard.impurity.module == "app.util"
    assert hazard.via == ("stamp",)
    assert hazard.workflow == "app.workflow:W"
    assert result.lexical == ()


def test_transitive_hazard_depth_two():
    util = """
import random

def outer():
    return inner()

def inner():
    return random.random()
"""
    result = analyze_workflow_surface(
        _modules({"app.workflow": _wf_calling("outer"), "app.util": util}),
        max_depth=2,
    )
    assert len(result.hazards) == 1
    assert result.hazards[0].via == ("outer", "inner")
    assert result.hazards[0].impurity.rule == "random.random"


def _wf_calling(symbol: str) -> str:
    return f"""
from temporalio import workflow
from app.util import {symbol}

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return {symbol}()
"""


def test_depth_bound_misses_deeper_and_max_depth_finds_it():
    sources = {
        "app.workflow": _chain_wf(),
        "app.a": "from app.b import b\n\ndef a():\n    return b()\n",
        "app.b": "from app.c import c\n\ndef b():\n    return c()\n",
        "app.c": (
            "import datetime\n\ndef c():\n    return datetime.datetime.now()\n"
        ),
    }
    shallow = analyze_workflow_surface(_modules(sources), max_depth=2)
    assert shallow.hazards == ()  # c is three calls out — beyond the bound
    deep = analyze_workflow_surface(_modules(sources), max_depth=3)
    assert len(deep.hazards) == 1
    assert deep.hazards[0].via == ("a", "b", "c")


def _chain_wf() -> str:
    return """
from temporalio import workflow
from app.a import a

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return a()
"""


def test_self_method_is_lexical_not_transitive():
    source = """
import datetime
from temporalio import workflow

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return self._helper()

    def _helper(self):
        return datetime.datetime.now()
"""
    result = analyze_workflow_surface(_modules({"app.workflow": source}))
    # The hazard is lexically inside the class (kernel territory), so it
    # lands in `lexical`, not a transitive hazard the brain claims credit for.
    assert result.hazards == ()
    assert len(result.lexical) == 1
    assert result.lexical[0].rule == "datetime.datetime.now"


def test_third_party_import_is_frontier():
    source = """
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    import httpx

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return 1
"""
    result = analyze_workflow_surface(_modules({"app.workflow": source}))
    assert len(result.frontier) == 1
    item = result.frontier[0]
    assert item.kind == "third_party_import"
    assert item.symbol == "httpx"
    assert item.workflow == "app.workflow:W"
    assert result.hazards == ()


def test_clean_surface_is_empty():
    wf = """
from temporalio import workflow
from app.util import pure

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return pure(workflow.now())
"""
    util = "def pure(value):\n    return value\n"
    result = analyze_workflow_surface(
        _modules({"app.workflow": wf, "app.util": util})
    )
    assert result.hazards == ()
    assert result.frontier == ()
    assert result.lexical == ()


def test_relative_imports_are_out_of_scope():
    # A relative import whose tail collides with a risky root (`http`) must not
    # be mistaken for one (no false frontier), and a relative-imported helper is
    # simply not chased rather than mis-resolved to a bogus module.
    source = """
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..http import fetch
    from ..util import stamp

@workflow.defn
class W:
    @workflow.run
    async def run(self):
        return fetch(), stamp()
"""
    result = analyze_workflow_surface(_modules({"app.workflow": source}))
    assert result.frontier == ()
    assert result.hazards == ()


def test_non_workflow_class_is_ignored():
    source = """
import datetime

class NotAWorkflow:
    def run(self):
        return datetime.datetime.now()
"""
    result = analyze_workflow_surface(_modules({"app.thing": source}))
    assert result.hazards == ()
    assert result.lexical == ()
    assert result.frontier == ()
