from __future__ import annotations

from froot.dashboard.github_source import (
    _merge_index,
    classify_check_runs,
    parse_from_version,
    parse_title,
    parse_verdict,
)
from froot.dashboard.github_source import _to_pr as to_pr


def _commit(sha: str, message: str) -> dict[str, object]:
    return {"sha": sha, "commit": {"message": message}}


def test_parse_title_extracts_package_and_target():
    assert parse_title("deps: bump vitest to 3.2.6") == ("vitest", "3.2.6")
    assert parse_title("deps: bump @nuxt/test-utils to 3.19.2") == (
        "@nuxt/test-utils",
        "3.19.2",
    )


def test_parse_title_rejects_non_froot_titles():
    assert parse_title("chore: update readme") is None
    assert parse_title("deps: bump vitest") is None
    assert parse_title("") is None


def test_parse_from_version():
    body = "Bumps `nuxt` from 3.21.6 to 3.21.7 (package.json + lockfile)."
    assert parse_from_version(body) == "3.21.6"
    assert parse_from_version(None) is None
    assert parse_from_version("no versions here") is None


def test_parse_verdict_covers_every_template_opener():
    assert parse_verdict("Changelog reads clean. Only a bug fix.") == "clean"
    assert parse_verdict("Review carefully. A deprecation.") == "risky"
    assert parse_verdict("Changelog unavailable. None found.") == "unknown"
    assert parse_verdict("something else") is None
    assert parse_verdict(None) is None


def test_to_pr_marks_merged_when_pull_request_has_merged_at():
    pr = to_pr(
        "acme/widgets",
        {
            "number": 7,
            "title": "deps: bump left-pad to 1.4.3",
            "html_url": "https://github.com/acme/widgets/pull/7",
            "state": "closed",
            "created_at": "2026-06-02T19:45:00Z",
            "body": (
                "Bumps `left-pad` from 1.4.2 to 1.4.3. Changelog reads clean."
            ),
            "pull_request": {"merged_at": "2026-06-02T20:00:00Z"},
        },
    )
    assert pr is not None
    assert pr.state == "merged"
    assert pr.package == "left-pad"
    assert pr.from_version == "1.4.2"
    assert pr.to_version == "1.4.3"
    assert pr.verdict == "clean"
    assert pr.merged_at is not None


def test_to_pr_distinguishes_open_from_closed_unmerged():
    opened = to_pr(
        "acme/widgets",
        {
            "number": 8,
            "title": "deps: bump x to 1.0.1",
            "state": "open",
            "pull_request": {"merged_at": None},
        },
    )
    closed = to_pr(
        "acme/widgets",
        {
            "number": 9,
            "title": "deps: bump x to 1.0.1",
            "state": "closed",
            "pull_request": {"merged_at": None},
        },
    )
    assert opened is not None and opened.state == "open"
    assert closed is not None and closed.state == "closed"


def test_to_pr_skips_plain_issues():
    assert to_pr("acme/widgets", {"number": 1, "title": "a bug"}) is None


# ── Post-merge outcome reader ────────────────────────────────────────────────
def test_classify_check_runs_held_broke_unknown():
    assert classify_check_runs({"check_runs": [{"conclusion": "success"}]}) == (
        "held"
    )
    # any failing conclusion wins over a success
    assert (
        classify_check_runs(
            {
                "check_runs": [
                    {"conclusion": "success"},
                    {"conclusion": "failure"},
                ]
            }
        )
        == "broke"
    )
    # no checks at all is unknown — never conflated with a pass
    assert classify_check_runs({"check_runs": []}) == "unknown"
    assert classify_check_runs({}) == "unknown"
    # an in-flight (null conclusion) run alone is unknown, not held
    assert classify_check_runs({"check_runs": [{"conclusion": None}]}) == (
        "unknown"
    )


def test_classify_check_runs_counts_cancelled_and_timed_out_as_broke():
    for bad in ("cancelled", "timed_out", "action_required"):
        assert (
            classify_check_runs({"check_runs": [{"conclusion": bad}]})
            == "broke"
        )


def test_merge_index_maps_merges_and_marks_reverts():
    # newest-first, like the GitHub commits list
    commits = [
        _commit("rev9", 'Revert "deps: bump p2 to 1.0.1 (#2)" (#9)'),
        _commit("sha1", "deps: bump p1 to 1.0.1 (#1)"),
        _commit("sha2", "deps: bump p2 to 1.0.1 (#2)"),
    ]
    merge_sha, reverted = _merge_index(commits, frozenset({1, 2}))
    assert merge_sha == {1: "sha1", 2: "sha2"}
    assert reverted == {2}


def test_merge_index_ignores_unknown_pr_numbers():
    # a (#N) that isn't one of froot's merged numbers must not be attributed
    commits = [_commit("x", "chore: something (#999)")]
    merge_sha, reverted = _merge_index(commits, frozenset({1}))
    assert merge_sha == {}
    assert reverted == set()


def test_merge_index_first_commit_wins_for_a_number():
    # a later (newer) commit referencing #1 takes precedence over an older one
    commits = [
        _commit("newer", "deps: bump p1 to 1.0.2 (#1)"),
        _commit("older", "deps: bump p1 to 1.0.1 (#1)"),
    ]
    merge_sha, _ = _merge_index(commits, frozenset({1}))
    assert merge_sha == {1: "newer"}


def test_to_pr_pins_offsetless_timestamp_to_utc():
    # A timestamp lacking a Z/offset would parse naive and later blow up the
    # read-model's aware-vs-naive subtraction; the boundary coerces it to UTC.
    pr = to_pr(
        "acme/widgets",
        {
            "number": 11,
            "title": "deps: bump x to 1.0.1",
            "state": "open",
            "created_at": "2026-06-02T19:45:00",  # no 'Z'
            "pull_request": {"merged_at": None},
        },
    )
    assert pr is not None
    assert pr.opened_at is not None
    assert pr.opened_at.tzinfo is not None  # aware, not naive


def _pr_with_labels(labels: list[dict[str, str]] | None):
    return to_pr(
        "acme/widgets",
        {
            "number": 5,
            "title": "deps: bump x to 1.0.1",
            "state": "open",
            "labels": labels,
            "pull_request": {"merged_at": None},
        },
    )


def test_to_pr_reads_security_patch_loop_from_label():
    pr = _pr_with_labels([{"name": "froot"}, {"name": "security-patch"}])
    assert pr is not None
    assert pr.loop == "security-patch"


def test_to_pr_defaults_loop_to_dependency_patch():
    # The froot label alone (the original loop carried no extra label).
    pr = _pr_with_labels([{"name": "froot"}])
    assert pr is not None
    assert pr.loop == "dependency-patch"


def test_to_pr_defaults_loop_when_labels_absent_or_malformed():
    missing = _pr_with_labels(None)
    assert missing is not None
    assert missing.loop == "dependency-patch"
    # A non-dict label entry must not crash the parse.
    pr = _pr_with_labels([{"name": "froot"}, "weird"])  # type: ignore[list-item]
    assert pr is not None
    assert pr.loop == "dependency-patch"
    assert to_pr("acme/widgets", "not a dict") is None
