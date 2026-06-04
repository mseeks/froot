"""The transitive determinism analyzer — pure logic over parsed modules.

This is froot's own embedded copy of the kernel matcher (the
``scripts/check_determinism.py`` tables + resolution), wrapped in a bounded
call-graph walk. The kernel finds banned calls *lexically* inside an
``@workflow.defn`` class; here we additionally chase first-party free-function
calls **out** of each workflow, up to ``max_depth`` levels, and run the same
matcher on each reachable body — so an imported helper that hides
``datetime.now()`` is caught even though it is invisible to the lexical kernel.

The matcher is deliberately a copy, not an import: the kernel script is vendored
per-repo (it must run standalone in any monitored repo's CI), so froot keeps its
own authoritative tables here. The two are kept in sync by the same rule set.

All functions are pure: the file/AST I/O is done by an adapter
(:mod:`froot.adapters.source_tree`), which hands this module already-parsed
:class:`LoadedModule` values. Self-method calls (``self.helper()``) are *not*
chased — their bodies are lexically inside the workflow class, so the kernel
already covers them; this loop only follows calls that leave the class.
"""

from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from froot.domain.determinism import (
    AnalysisResult,
    FrontierItem,
    HazardPath,
    Impurity,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# ── The banned tables (kept in sync with scripts/check_determinism.py) ───────
BANNED_CALLS: dict[str, str] = {
    "datetime.datetime.now": "use workflow.now()",
    "datetime.datetime.utcnow": "use workflow.now()",
    "datetime.datetime.today": "use workflow.now()",
    "datetime.date.today": "use workflow.now().date()",
    "time.time": "use workflow.now()",
    "time.time_ns": "use workflow.now()",
    "time.monotonic": "use workflow.now()",
    "time.monotonic_ns": "use workflow.now()",
    "time.perf_counter": "use workflow.now()",
    "time.perf_counter_ns": "use workflow.now()",
    "time.process_time": "use workflow.now()",
    "time.sleep": "use workflow.sleep()",
    "uuid.uuid1": "use workflow.uuid4()",
    "uuid.uuid3": "use workflow.uuid4()",
    "uuid.uuid4": "use workflow.uuid4()",
    "uuid.uuid5": "use workflow.uuid4()",
    "os.getenv": "read env in an activity and pass it in",
    "os.urandom": "use workflow.random()",
    "asyncio.sleep": "use workflow.sleep()",
    "socket.socket": "do network I/O in an activity",
}
BANNED_CALL_MODULES: dict[str, str] = {
    "random": "use workflow.random()",
    "threading": "workflows are single-threaded; use workflow APIs",
    "requests": "do network I/O in an activity",
    "httpx": "do network I/O in an activity",
    "subprocess": "run external processes in an activity",
}
BANNED_ATTRS: dict[str, str] = {
    "os.environ": "read env in an activity and pass it in",
}
BANNED_BUILTINS: dict[str, str] = {
    "open": "do file I/O in an activity",
    "input": "workflows cannot block on input",
}

# Third-party roots with no deterministic surface worth importing into a
# workflow module. Their presence at module scope is the model's frontier: is it
# actually reached from the workflow, or dead weight?
_RISKY_THIRD_PARTY: frozenset[str] = frozenset(
    {
        "httpx",
        "requests",
        "aiohttp",
        "urllib",
        "http",
        "socket",
        "subprocess",
        "boto3",
        "redis",
        "psycopg",
        "psycopg2",
        "pymongo",
        "sqlalchemy",
        "smtplib",
        "ftplib",
        "paramiko",
    }
)


@dataclass(frozen=True)
class LoadedModule:
    """A first-party module parsed by the source-tree adapter."""

    qualname: str
    tree: ast.Module
    lines: tuple[str, ...]


# ── The matcher (ported verbatim in spirit from the kernel script) ───────────
def _import_map(tree: ast.Module) -> dict[str, str]:
    """Map each bound name to the dotted module/symbol path it refers to."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    bindings[root] = root
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (``from . import x`` / ``from ..pkg import x``)
            # are out of scope: a bare/level path can't be resolved to a loaded
            # module, and a bogus binding could collide with a real one.
            if node.module is None or node.level > 0:
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                bindings[bound] = f"{node.module}.{alias.name}"
    return bindings


def _dotted(node: ast.AST) -> str | None:
    """The literal dotted path of a Name/Attribute chain, or None."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _resolve(node: ast.AST, imports: Mapping[str, str]) -> str | None:
    """Dotted path with the root name substituted via the import map."""
    dotted = _dotted(node)
    if dotted is None:
        return None
    root, _, rest = dotted.partition(".")
    if root not in imports:
        return None
    base = imports[root]
    return f"{base}.{rest}" if rest else base


def check_node(
    node: ast.expr, imports: Mapping[str, str]
) -> tuple[str, str] | None:
    """Return ``(rule, hint)`` if ``node`` is a banned call/attr, else None."""
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Name)
            and func.id in BANNED_BUILTINS
            and func.id not in imports
        ):
            return func.id, BANNED_BUILTINS[func.id]
        resolved = _resolve(func, imports)
        if resolved is None:
            return None
        if resolved in BANNED_CALLS:
            return resolved, BANNED_CALLS[resolved]
        if resolved.split(".")[0] in BANNED_CALL_MODULES:
            return resolved, BANNED_CALL_MODULES[resolved.split(".")[0]]
        return None
    if isinstance(node, ast.Attribute):
        resolved = _resolve(node, imports)
        if resolved in BANNED_ATTRS:
            return resolved, BANNED_ATTRS[resolved]
    return None


def _is_workflow_class(node: ast.ClassDef, imports: Mapping[str, str]) -> bool:
    """True if the class carries an ``@workflow.defn`` decorator."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        resolved = _resolve(target, imports) or _dotted(target)
        if resolved and resolved.endswith("workflow.defn"):
            return True
    return False


# ── The call graph ───────────────────────────────────────────────────────────
def _module_functions(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index the module's top-level free functions by name."""
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name] = node
    return out


def _split_qual(qual: str) -> tuple[str, str] | None:
    """Split ``a.b.c`` into module ``a.b`` and symbol ``c`` (None if no dot)."""
    module, _, symbol = qual.rpartition(".")
    if not module or not symbol:
        return None
    return module, symbol


def _scan_body(
    node: ast.AST, imports: Mapping[str, str], module: str
) -> list[Impurity]:
    """Find every banned call lexically inside ``node`` (a def or class)."""
    found: list[Impurity] = []
    seen: set[tuple[int, str]] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call | ast.Attribute):
            continue
        hit = check_node(child, imports)
        if hit is None:
            continue
        rule, hint = hit
        key = (child.lineno, rule)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            Impurity(rule=rule, hint=hint, module=module, line=child.lineno)
        )
    return found


def _first_party_callees(
    node: ast.AST,
    imports: Mapping[str, str],
    modules: Mapping[str, LoadedModule],
    functions: Mapping[str, Mapping[str, object]],
    current: str,
) -> list[tuple[str, str, str]]:
    """First-party functions ``node`` calls, as ``(module, symbol, label)``.

    Only calls that *leave* the current scope to a known first-party free
    function are returned; ``self.method()`` and stdlib/third-party calls are
    not (the former is the kernel's lexical territory, the latter is not a
    first-party edge to chase).
    """
    edges: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        target: tuple[str, str] | None = None
        if isinstance(func, ast.Name):
            bound = imports.get(func.id)
            if bound is not None:
                target = _split_qual(bound)
            elif func.id in functions.get(current, {}):
                target = (current, func.id)
        elif isinstance(func, ast.Attribute):
            resolved = _resolve(func, imports)
            if resolved is not None:
                target = _split_qual(resolved)
        if target is None:
            continue
        module, symbol = target
        if module not in modules or symbol not in functions.get(module, {}):
            continue
        if (module, symbol) in seen:
            continue
        seen.add((module, symbol))
        edges.append((module, symbol, symbol))
    return edges


def _risky_imports(
    tree: ast.Module, first_party: frozenset[str]
) -> list[tuple[int, str]]:
    """Module-scope risky third-party imports as ``(line, dotted_root)``."""
    out: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.level == 0  # absolute only; a relative tail isn't a module
        ):
            names = [node.module]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            if root in _RISKY_THIRD_PARTY and root not in first_party:
                key = (node.lineno, name)
                if key not in seen:
                    seen.add(key)
                    out.append((node.lineno, name))
    return out


def _line(lines: tuple[str, ...], lineno: int) -> str:
    """The stripped source at ``lineno`` (1-based), or empty if out of range."""
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


def analyze_workflow_surface(
    modules: Mapping[str, LoadedModule], *, max_depth: int = 2
) -> AnalysisResult:
    """Find transitive determinism hazards across a repo's workflow surface.

    Args:
        modules: Every first-party module, parsed, keyed by dotted qualname.
        max_depth: How many first-party call levels to chase out of each
            workflow method (2 = the helper a workflow calls, and the helper
            *that* calls).

    Returns:
        The lexical hits (the kernel's set), the confirmed transitive hazards,
        and the ambiguous frontier (risky third-party imports) for the model.
    """
    functions = {qn: _module_functions(lm.tree) for qn, lm in modules.items()}
    first_party = frozenset(qn.split(".")[0] for qn in modules)

    workflows: list[tuple[str, ast.ClassDef, dict[str, str]]] = []
    for qn, lm in modules.items():
        imports = _import_map(lm.tree)
        for node in ast.walk(lm.tree):
            if isinstance(node, ast.ClassDef) and _is_workflow_class(
                node, imports
            ):
                workflows.append((qn, node, imports))

    lexical: list[Impurity] = []
    hazards: list[HazardPath] = []
    for qn, cls, imports in workflows:
        label = f"{qn}:{cls.name}"
        lexical.extend(_scan_body(cls, imports, qn))
        seen: set[tuple[str, str]] = set()
        queue: deque[tuple[tuple[str, str], tuple[str, ...], int]] = deque(
            ((m, s), (lbl,), 1)
            for m, s, lbl in _first_party_callees(
                cls, imports, modules, functions, qn
            )
        )
        while queue:
            (mod, sym), via, depth = queue.popleft()
            if (mod, sym) in seen:
                continue
            seen.add((mod, sym))
            fn = functions[mod].get(sym)
            if fn is None:
                continue
            fn_imports = _import_map(modules[mod].tree)
            for imp in _scan_body(fn, fn_imports, mod):
                hazards.append(
                    HazardPath(workflow=label, via=via, impurity=imp)
                )
            if depth < max_depth:
                for m2, s2, lbl2 in _first_party_callees(
                    fn, fn_imports, modules, functions, mod
                ):
                    if (m2, s2) not in seen:
                        queue.append(((m2, s2), (*via, lbl2), depth + 1))

    frontier: list[FrontierItem] = []
    wf_class_of: dict[str, str] = {}
    for qn, cls, _ in workflows:
        wf_class_of.setdefault(qn, cls.name)
    for qn in sorted(wf_class_of):
        lm = modules[qn]
        for lineno, root in _risky_imports(lm.tree, first_party):
            frontier.append(
                FrontierItem(
                    kind="third_party_import",
                    workflow=f"{qn}:{wf_class_of[qn]}",
                    module=qn,
                    line=lineno,
                    symbol=root,
                    snippet=_line(lm.lines, lineno),
                )
            )

    return AnalysisResult(
        lexical=tuple(_dedupe_impurities(lexical)),
        hazards=tuple(_dedupe_hazards(hazards)),
        frontier=tuple(frontier),
    )


def _dedupe_impurities(items: Iterable[Impurity]) -> list[Impurity]:
    seen: set[tuple[str, int, str]] = set()
    out: list[Impurity] = []
    for i in sorted(items, key=lambda x: (x.module, x.line, x.rule)):
        key = (i.module, i.line, i.rule)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def _dedupe_hazards(items: Iterable[HazardPath]) -> list[HazardPath]:
    seen: set[tuple[str, str, int, str]] = set()
    out: list[HazardPath] = []
    ordered = sorted(
        items,
        key=lambda h: (
            h.workflow,
            h.impurity.module,
            h.impurity.line,
            h.impurity.rule,
        ),
    )
    for h in ordered:
        key = (h.workflow, h.impurity.module, h.impurity.line, h.impurity.rule)
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out
