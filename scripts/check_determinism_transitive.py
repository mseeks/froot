"""Transitive determinism gate — froot held to the bar it sets for others.

The kernel (``check_determinism.py``) is lexical: it flags banned calls written
directly inside an ``@workflow.defn`` class, high-precision and install-free.
This wrapper runs froot's *own* transitive analyzer — the same
``analyze_workflow_surface`` the determinism-reviewer loop points at other repos
— over froot's source, chasing first-party helpers OUT of each workflow up to a
bounded depth. A confirmed hazard (a banned call reachable from a workflow
through a first-party function) fails the gate.

The risky-third-party-import *frontier* (which froot adjudicates with a model for
other repos) is printed as advisory only and never fails the build: a static gate
must not cry wolf. Unlike the kernel this imports froot, so CI runs it in the
synced environment (``uv run``), not the install-free lexical job.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from froot.adapters.source_tree import load_modules
from froot.policy.determinism import analyze_workflow_surface


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="repo root containing src/ (default: .)",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=2,
        help="first-party call levels to chase out of each workflow",
    )
    args = parser.parse_args(argv)

    modules = load_modules(Path(args.repo))
    result = analyze_workflow_surface(modules, max_depth=args.depth)

    for item in result.frontier:
        print(
            f"advisory (frontier): {item.module}:{item.line} imports "
            f"{item.symbol} — reachability from {item.workflow} not confirmed"
        )

    if not result.hazards:
        print("No transitive determinism hazards reach a workflow. ✓")
        return 0

    for hazard in result.hazards:
        via = " -> ".join(hazard.via)
        imp = hazard.impurity
        print(f"{imp.module}:{imp.line}  {imp.rule}  ->  {imp.hint}")
        print(f"    reached from {hazard.workflow} via {via}")
    noun = "hazard" if len(result.hazards) == 1 else "hazards"
    print(
        f"\n{len(result.hazards)} transitive determinism {noun} "
        "reachable from a workflow.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
