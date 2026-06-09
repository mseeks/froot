from __future__ import annotations

import pytest

from froot.domain.loop import Loop
from froot.trigger import oneshot_plans, parse_trigger_loops
from tests.support import make_repo


def test_parse_trigger_loops_none_for_empty():
    assert parse_trigger_loops(None) is None
    assert parse_trigger_loops("") is None
    assert parse_trigger_loops("   ") is None


def test_parse_trigger_loops_named():
    assert parse_trigger_loops("dead-code") == (Loop.DEAD_CODE,)
    assert parse_trigger_loops("dead-code, security-patch") == (
        Loop.DEAD_CODE,
        Loop.SECURITY_PATCH,
    )


def test_parse_trigger_loops_unknown_raises():
    # A typo fails loudly rather than silently scanning nothing.
    with pytest.raises(ValueError):
        parse_trigger_loops("not-a-loop")


def test_oneshot_plans_one_per_acting_loop_and_repo():
    repos = (make_repo("a/one"), make_repo("b/two"))
    loops = (Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH, Loop.DEAD_CODE)
    plans = oneshot_plans(repos=repos, loops=loops)
    # 3 acting loops x 2 repos = 6; advisory loops (determinism/a11y) excluded.
    assert len(plans) == 6
    assert all(p.params.continuous is False for p in plans)
    assert all(p.workflow_id.endswith("-now") for p in plans)
    deadcode = next(
        p
        for p in plans
        if p.params.loop is Loop.DEAD_CODE and p.slug == "a/one"
    )
    # The one-shot id is the loop's scan id plus a distinct -now suffix.
    assert deadcode.workflow_id == "froot-scan-dead-code-a-one-now"


def test_oneshot_plans_only_filter_narrows():
    repos = (make_repo("a/one"),)
    loops = (Loop.DEPENDENCY_PATCH, Loop.DEAD_CODE)
    plans = oneshot_plans(repos=repos, loops=loops, only=(Loop.DEAD_CODE,))
    assert [p.params.loop for p in plans] == [Loop.DEAD_CODE]


def test_oneshot_plans_skips_loops_not_configured():
    # A loop in `only` but absent from FROOT_LOOPS is not scanned — you can't
    # nudge a loop that isn't configured to run.
    repos = (make_repo("a/one"),)
    plans = oneshot_plans(
        repos=repos, loops=(Loop.DEPENDENCY_PATCH,), only=(Loop.DEAD_CODE,)
    )
    assert plans == ()
