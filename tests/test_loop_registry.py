"""The loop registry — the spine reads it instead of branching on the enum.

These guard the per-loop seams the registry now owns: the disposition (which
the gate machinery keys on), the workflow-id namespace segment (which must agree
with ``naming.py``, the spine's own deterministic derivation), and the
changelog-judge framing — so a loop's identity stays single-sourced as loops
multiply. Behavior equivalence of each loop's ``observe`` is covered by the
existing scan tests, which now route through the registry.
"""

from __future__ import annotations

from froot.adapters.model_judge import _loop_context
from froot.domain.loop import Loop
from froot.loops import registry
from froot.loops.registry import Disposition
from froot.policy.naming import _loop_id_segment

_ACTING = (Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH, Loop.DEAD_CODE)


def test_acting_loops_registered_as_commit_or_revert() -> None:
    specs = {spec.loop: spec for spec in registry.all_specs()}
    for loop in _ACTING:
        assert specs[loop].disposition is Disposition.COMMIT_OR_REVERT


def test_id_segment_agrees_with_naming() -> None:
    # The spine's deterministic ids (naming.py) and the registered spec must
    # never drift — the segment is the loop's namespace, single-sourced.
    for loop in _ACTING:
        assert registry.get(loop).id_segment == _loop_id_segment(loop)


def test_dependency_patch_keeps_the_empty_legacy_segment() -> None:
    # The first loop's ids predate a second loop; an empty segment keeps them
    # byte-for-byte so a running loop is never orphaned.
    assert registry.get(Loop.DEPENDENCY_PATCH).id_segment == ()


def test_judge_context_present_for_changelog_loops_absent_for_dead_code() -> (
    None
):
    # Dependency- and security-patch judge a changelog in-loop (a framing line);
    # dead-code judges at the signal (a removal veto), so it carries no context.
    assert registry.get(Loop.DEPENDENCY_PATCH).judge_context is not None
    assert registry.get(Loop.SECURITY_PATCH).judge_context is not None
    assert registry.get(Loop.DEAD_CODE).judge_context is None


def test_loop_context_reads_the_registry() -> None:
    for loop in (Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH):
        assert _loop_context(loop) == registry.get(loop).judge_context


def test_reconciles_true_for_bump_loops_false_for_dead_code() -> None:
    # Version-supersession reconcile only applies to version-bearing bumps; a
    # removal has no version to be overtaken, so dead-code declares it skips.
    assert registry.get(Loop.DEPENDENCY_PATCH).reconciles is True
    assert registry.get(Loop.SECURITY_PATCH).reconciles is True
    assert registry.get(Loop.DEAD_CODE).reconciles is False
