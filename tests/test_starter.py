"""The unified starter's pure plan — which loops start, with what.

The starter's I/O (connect, ``start_workflow``) is thin glue; its *decision* is
the pure :func:`~froot.starter.plans`, derived from the registry and the
settings. These guard that decision: an acting loop starts iff it is in
``FROOT_LOOPS``, an advisory loop iff its enable flag is on, and each lands on
its own workflow type, id, and params — so the one entrypoint covers all five
loops without a per-family starter.
"""

from __future__ import annotations

from froot.domain.loop import Loop
from froot.domain.repo import TargetRepo
from froot.policy.naming import (
    a11y_review_workflow_id,
    doc_coherence_review_workflow_id,
    doc_refs_review_workflow_id,
    review_workflow_id,
    scan_workflow_id,
)
from froot.starter import _Start, advisory_wiring, plans
from froot.workflow.types import (
    A11yReviewScanParams,
    DocCoherenceReviewScanParams,
    DocRefsReviewScanParams,
    ReviewScanParams,
    ScanParams,
)
from tests.support import make_repo

REPO = make_repo("mseeks/revisionist")
REPO2 = make_repo("mseeks/froot")

_ACTING = (Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH, Loop.DEAD_CODE)


def _plans(
    *,
    loops: tuple[Loop, ...] = (Loop.DEPENDENCY_PATCH,),
    repos: tuple[TargetRepo, ...] = (REPO,),
    review: bool = True,
    a11y: bool = False,
    doc_refs: bool = False,
    doc_coherence: bool = False,
    scan_interval: int = 86_400,
):
    return plans(
        repos=repos,
        loops=loops,
        scan_interval_seconds=scan_interval,
        advisory=advisory_wiring(
            review_enabled=review,
            review_interval_seconds=300,
            a11y_enabled=a11y,
            a11y_interval_seconds=600,
            doc_refs_enabled=doc_refs,
            doc_refs_interval_seconds=600,
            doc_coherence_enabled=doc_coherence,
            doc_coherence_interval_seconds=600,
        ),
    )


def _by_id(ps: tuple[_Start, ...]) -> dict[str, _Start]:
    return {p.workflow_id: p for p in ps}


def test_default_starts_dependency_scan_and_determinism_review():
    # The defaults — FROOT_LOOPS=dependency-patch, review on, a11y off — start
    # one acting scan and one advisory review per repo, and nothing else.
    ps = _plans()
    assert sorted(p.workflow_type for p in ps) == [
        "ReviewWorkflow",
        "ScanWorkflow",
    ]
    ids = _by_id(ps)
    assert scan_workflow_id(REPO, Loop.DEPENDENCY_PATCH) in ids
    assert review_workflow_id(REPO) in ids


def test_acting_loop_not_in_froot_loops_is_skipped():
    # security-patch and dead-code are registered but only start when listed.
    ps = _plans(loops=(Loop.DEPENDENCY_PATCH,))
    scan_loops = {p.params.loop for p in ps if isinstance(p.params, ScanParams)}
    assert scan_loops == {Loop.DEPENDENCY_PATCH}


def test_advisory_loop_in_froot_loops_does_not_spawn_a_scan():
    # Routing is by disposition, not FROOT_LOOPS membership: an advisory loop
    # mistakenly listed in FROOT_LOOPS must never get an acting ScanWorkflow
    # (the old scan starter would have tried to start one).
    ps = _plans(
        loops=(Loop.DEPENDENCY_PATCH, Loop.DETERMINISM_REVIEW),
        review=False,
    )
    assert [p.workflow_type for p in ps] == ["ScanWorkflow"]
    scan_loops = {p.params.loop for p in ps if isinstance(p.params, ScanParams)}
    assert scan_loops == {Loop.DEPENDENCY_PATCH}


def test_every_configured_acting_loop_gets_its_own_scan_namespace():
    ps = _plans(loops=_ACTING)
    scan_loops = {p.params.loop for p in ps if isinstance(p.params, ScanParams)}
    assert scan_loops == set(_ACTING)
    ids = {p.workflow_id for p in ps}
    for loop in _ACTING:
        assert scan_workflow_id(REPO, loop) in ids


def test_a11y_starts_only_when_enabled():
    off = {p.workflow_type for p in _plans(a11y=False)}
    assert "A11yReviewWorkflow" not in off
    on = _by_id(_plans(a11y=True))
    assert a11y_review_workflow_id(REPO) in on


def test_determinism_review_skipped_when_disabled():
    ps = _plans(review=False)
    assert all(p.workflow_type != "ReviewWorkflow" for p in ps)


def test_no_acting_and_no_advisory_yields_nothing():
    # The empty heartbeat: no configured acting loop, both advisory off.
    assert _plans(loops=(), review=False, a11y=False) == ()


def test_params_carry_each_loop_own_interval_and_continuous():
    ps = _by_id(_plans(loops=(Loop.DEPENDENCY_PATCH,), a11y=True))
    scan = ps[scan_workflow_id(REPO, Loop.DEPENDENCY_PATCH)]
    assert isinstance(scan.params, ScanParams)
    assert scan.params.interval_seconds == 86_400
    assert scan.params.continuous is True
    review = ps[review_workflow_id(REPO)]
    assert isinstance(review.params, ReviewScanParams)
    assert review.params.interval_seconds == 300
    a11y = ps[a11y_review_workflow_id(REPO)]
    assert isinstance(a11y.params, A11yReviewScanParams)
    assert a11y.params.interval_seconds == 600


def test_one_plan_per_repo():
    ps = _plans(repos=(REPO, REPO2), loops=(Loop.DEPENDENCY_PATCH,), a11y=True)
    # 2 repos x (dependency scan + determinism + a11y) = 6
    assert len(ps) == 6
    assert {p.slug for p in ps} == {"mseeks/revisionist", "mseeks/froot"}


def test_advisory_wiring_routes_each_loop_to_its_own_workflow():
    w = advisory_wiring(
        review_enabled=True,
        review_interval_seconds=1,
        a11y_enabled=True,
        a11y_interval_seconds=2,
        doc_refs_enabled=True,
        doc_refs_interval_seconds=3,
        doc_coherence_enabled=True,
        doc_coherence_interval_seconds=4,
    )
    assert w[Loop.DETERMINISM_REVIEW].workflow_type == "ReviewWorkflow"
    assert w[Loop.DETERMINISM_REVIEW].params is ReviewScanParams
    assert w[Loop.A11Y_REVIEW].workflow_type == "A11yReviewWorkflow"
    assert w[Loop.A11Y_REVIEW].params is A11yReviewScanParams
    assert w[Loop.DOC_REFS].workflow_type == "DocRefsReviewWorkflow"
    assert w[Loop.DOC_REFS].params is DocRefsReviewScanParams
    assert w[Loop.DOC_COHERENCE].workflow_type == "DocCoherenceReviewWorkflow"
    assert w[Loop.DOC_COHERENCE].params is DocCoherenceReviewScanParams


def test_doc_refs_starts_only_when_enabled():
    # Advisory: no start by default, started when its flag is on — the
    # observe-then-act gate, same as the other advisory loops.
    assert doc_refs_review_workflow_id(REPO) not in _by_id(
        _plans(doc_refs=False)
    )
    on = _by_id(_plans(doc_refs=True))
    start = on[doc_refs_review_workflow_id(REPO)]
    assert start.workflow_type == "DocRefsReviewWorkflow"
    assert start.label == "doc-refs review"


def test_doc_coherence_starts_only_when_enabled():
    assert doc_coherence_review_workflow_id(REPO) not in _by_id(
        _plans(doc_coherence=False)
    )
    on = _by_id(_plans(doc_coherence=True))
    start = on[doc_coherence_review_workflow_id(REPO)]
    assert start.workflow_type == "DocCoherenceReviewWorkflow"
    assert start.label == "doc-coherence review"
