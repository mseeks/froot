from __future__ import annotations

from froot.policy.environment import (
    env_from_labels,
    env_label,
    environment_slug,
)


def test_environment_slug_is_a_legible_model_slug():
    assert environment_slug("gemma4:26b") == "gemma4-26b"
    assert environment_slug("gemma4:e4b") == "gemma4-e4b"
    assert environment_slug("  Qwen3.5:0.8B  ") == "qwen3-5-0-8b"


def test_environment_slug_never_empty():
    assert environment_slug("") == "unknown"
    assert environment_slug("@@@") == "unknown"


def test_env_label_round_trips_through_labels():
    label = env_label("gemma4:26b")
    assert label == "froot-env:gemma4-26b"
    assert env_from_labels({"froot", "dependency-patch", label}) == "gemma4-26b"


def test_env_from_labels_is_none_when_unstamped():
    # A PR with no froot-env: label was opened under a prior environment.
    assert env_from_labels({"froot", "dependency-patch"}) is None
    assert env_from_labels(set()) is None


def test_a_model_swap_changes_the_label():
    # The whole point: different models yield different stamps, so trust earned
    # under one does not match the other (§3.7 conditional).
    assert env_label("gemma4:e4b") != env_label("gemma4:26b")
