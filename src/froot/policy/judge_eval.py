"""The judge eval — a golden set that keeps the one model judgment honest.

froot is spine-heavy and model-thin, but the single model call it makes — "is
this changelog clean, or does it hide a behavioral change behind a patch?" — is
load-bearing at the gate: a *risky* changelog wrongly read as *clean* is the one
judgment error that could wave an unsafe bump through. That judge runs on a
local model a steward can swap, and a model can drift; neither drift shows up
in CI, where the judge has no fixed inputs. This is the adversarial probe for
the judgment bearing (MHE §2.11): a fixed battery of changelogs whose right
reading we already know, re-graded against the *live* model on a schedule,
alarming the moment the judge stops agreeing with the golden answers.

This module is the pure half — the fixtures, the grade, the reduction, and the
alert decision — so every part is tested without a model. The live run and the
schedule are the impure wiring (:mod:`froot.judge_eval`, a k8s CronJob).

The grade is deliberately asymmetric. A *clean* fixture must read as ``clean``
exactly; a *risky* fixture must read as anything but ``clean`` (``risky`` or
``unknown`` both pass). That mirrors the gate's burden — the unsafe drift is a
risky changelog read as clean, so that is the direction pinned hard — and the
two halves triangulate: a degenerate judge that always says ``clean`` fails
every risky case, and one that always says ``unknown`` fails every clean case.
Only a judge that actually discriminates passes both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.base import Frozen
from froot.domain.changelog import Changelog
from froot.domain.loop import Loop
from froot.domain.version import Version

if TYPE_CHECKING:
    from froot.domain.changelog import ChangelogVerdict


class EvalCase(Frozen):
    """One golden fixture: a changelog whose right reading we already know.

    Attributes:
        name: A short, stable identifier for the case (used in logs/alerts).
        changelog: The changelog fed to the live judge, with the package and
            target version that frame it.
        loop: Which loop's framing to judge under — the prompt differs for a
            routine patch vs. a security upgrade.
        expect_clean: The known-right reading. ``True`` means the judge should
            return ``clean``; ``False`` means anything but ``clean`` (the
            changelog describes a real behavioral change).
    """

    name: str
    changelog: Changelog
    expect_clean: bool
    loop: Loop = Loop.DEPENDENCY_PATCH


class CaseOutcome(Frozen):
    """How the live judge read one fixture, and whether it was right.

    Attributes:
        name: The fixture's identifier, carried through for logs and the alert.
        expect_clean: The fixture's known-right reading (see :class:`EvalCase`).
        got: The live verdict's discriminator (``clean`` / ``risky`` /
            ``unknown``).
        rationale: The model's one-line reason, surfaced in the alert so a
            human sees *why* the judge disagreed.
        passed: Whether ``got`` matched the fixture under the asymmetric grade.
    """

    name: str
    expect_clean: bool
    got: str
    rationale: str
    passed: bool


class EvalSummary(Frozen):
    """The whole run reduced to a pass count and the mismatches to alarm on."""

    total: int
    passed: int
    failures: tuple[CaseOutcome, ...] = ()


def grade(case: EvalCase, verdict: ChangelogVerdict) -> bool:
    """Whether the live verdict matches the fixture's known-right reading.

    Asymmetric on purpose (see the module docstring): a clean case must read as
    ``clean``; a risky case must read as anything but ``clean``.
    """
    if case.expect_clean:
        return verdict.kind == "clean"
    return verdict.kind != "clean"


def outcome(case: EvalCase, verdict: ChangelogVerdict) -> CaseOutcome:
    """Build the graded outcome for one case from its live verdict (pure)."""
    return CaseOutcome(
        name=case.name,
        expect_clean=case.expect_clean,
        got=verdict.kind,
        rationale=verdict.rationale,
        passed=grade(case, verdict),
    )


def summarize(outcomes: tuple[CaseOutcome, ...]) -> EvalSummary:
    """Reduce per-case outcomes to a pass count and the failures (pure)."""
    failures = tuple(o for o in outcomes if not o.passed)
    return EvalSummary(
        total=len(outcomes),
        passed=len(outcomes) - len(failures),
        failures=failures,
    )


def eval_alert(summary: EvalSummary) -> tuple[str, str] | None:
    """The ``(title, message)`` to alarm on, or ``None`` when the judge agreed.

    Pure, mirroring the watchdog's ``revival_alert``: the one decision that
    matters — alert iff the live judge disagreed with a golden answer — is
    testable without a model or a notifier.
    """
    if not summary.failures:
        return None
    n = len(summary.failures)
    title = (
        f"froot judge eval: {n} mismatch{'es' if n != 1 else ''} "
        f"of {summary.total}"
    )
    lines = [
        f"{o.name}: expected {'clean' if o.expect_clean else 'not-clean'}, "
        f"got {o.got} — {o.rationale}"
        for o in summary.failures
    ]
    return title, "\n".join(lines)


# The golden set: realistic changelogs whose right reading is unambiguous,
# *calibrated against the live judge* — a fixture the healthy judge already
# disagrees with would cry wolf daily, defeating the whole drift alarm. Three
# clean and three risky, balanced so the two halves triangulate (module
# docstring). Grow it by running a candidate against the live judge and keeping
# only what the healthy judge classifies as intended (a new loop's framing, a
# boundary worth pinning).
#
# Calibration note: this model (Gemma 4 12B) reads *any* functional change as
# risky — even a bugfix whose notes say "no behavioral change", since a fix is a
# behavior change. That conservatism is safe at the gate (it holds more for a
# human to review), so a *clean* fixture must carry strictly NO code change:
# docs, CI, packaging metadata, dev-dependency bumps, a message-string typo.
# Don't pin the over-cautious direction (a code change the judge could
# reasonably flag) as a clean expectation; the risky half carries the load.
GOLDEN: tuple[EvalCase, ...] = (
    EvalCase(
        name="packaging-metadata-only",
        changelog=Changelog(
            package="ms",
            version=Version(major=2, minor=1, patch=4),
            text=(
                "Corrected the repository URL and added `funding` and "
                "`keywords` fields to package.json. No source or runtime "
                "changes."
            ),
        ),
        expect_clean=True,
    ),
    EvalCase(
        name="docs-and-ci-only",
        changelog=Changelog(
            package="tiny-invariant",
            version=Version(major=1, minor=3, patch=1),
            text=(
                "Docs: fix three broken README links. Internal: move CI from "
                "Travis to GitHub Actions. No runtime changes."
            ),
        ),
        expect_clean=True,
    ),
    EvalCase(
        name="typo-and-dev-deps",
        changelog=Changelog(
            package="lodash.merge",
            version=Version(major=4, minor=6, patch=3),
            text=(
                "Patch release: bump development dependencies and fix a typo "
                "in an internal error message string."
            ),
        ),
        expect_clean=True,
    ),
    EvalCase(
        name="behavior-hidden-in-patch",
        changelog=Changelog(
            package="marked",
            version=Version(major=4, minor=3, patch=1),
            text=(
                "Patch release. Note: `headerIds` now defaults to false to "
                "avoid duplicate ids; output for documents that relied on the "
                "auto-generated header ids will change."
            ),
        ),
        expect_clean=False,
    ),
    EvalCase(
        name="new-throw-in-patch",
        changelog=Changelog(
            package="date-fns",
            version=Version(major=2, minor=29, patch=4),
            text=(
                "`parseISO` now throws a RangeError on invalid input instead "
                "of returning an Invalid Date. Callers that checked for an "
                "Invalid Date result must now catch the error."
            ),
        ),
        expect_clean=False,
    ),
    EvalCase(
        name="security-bump-with-breaking-default",
        changelog=Changelog(
            package="redis",
            version=Version(major=4, minor=6, patch=0),
            text=(
                "Security: fixes a denial-of-service parsing flaw "
                "(CVE-2023-28858). Behavior change: the default "
                "`socket_timeout` is now 5 seconds instead of unset, so a "
                "long-running blocking command may now raise TimeoutError."
            ),
        ),
        loop=Loop.SECURITY_PATCH,
        expect_clean=False,
    ),
)
