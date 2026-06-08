"""Worker wiring: the Pydantic data converter + the workflow/activity registry.

The worker (and the workflow tests) build their client with
:data:`DATA_CONVERTER` so domain models serialize through Temporal, and register
:data:`WORKFLOWS` and :data:`ALL_ACTIVITIES`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from temporalio.contrib.pydantic import pydantic_data_converter

from froot.workflow import activities
from froot.workflow.a11y_review_workflow import A11yReviewWorkflow
from froot.workflow.bump_workflow import BumpWorkflow
from froot.workflow.pr_a11y_review_workflow import PrA11yReviewWorkflow
from froot.workflow.pr_review_workflow import PrReviewWorkflow
from froot.workflow.review_workflow import ReviewWorkflow
from froot.workflow.scan_workflow import ScanWorkflow

if TYPE_CHECKING:
    from collections.abc import Callable

DATA_CONVERTER = pydantic_data_converter

WORKFLOWS = [
    ScanWorkflow,
    BumpWorkflow,
    ReviewWorkflow,
    PrReviewWorkflow,
    A11yReviewWorkflow,
    PrA11yReviewWorkflow,
]

ALL_ACTIVITIES: list[Callable[..., object]] = [
    activities.scan_candidates,
    activities.judge_changelog,
    activities.gate_review,
    activities.open_pull_request,
    activities.check_ci,
    activities.record_outcome,
    activities.close_pull_request,
    activities.auto_merge_eligible,
    activities.merge_pull_request,
    activities.reconcile_open_prs,
    activities.gate_selftest,
    activities.dispatch_bump,
    activities.list_review_prs,
    activities.dispatch_pr_review,
    activities.analyze_pr,
    activities.adjudicate_frontier,
    activities.post_review,
    activities.scan_pr_a11y,
    activities.adjudicate_a11y,
    activities.post_a11y_review,
    activities.dispatch_pr_a11y_review,
]
