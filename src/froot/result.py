"""A minimal ``Result`` type for the parsing boundary.

Domain value objects validate on construction — Pydantic raises on illegal
input, which is the right move when a caller hands us data that *should* already
be valid. But at the *boundary*, where untrusted external text (``npm`` output,
GitHub JSON) becomes domain values, an expected parse failure is not
exceptional. There the pure parsers return a ``Result`` and the caller
pattern-matches on :class:`Ok` / :class:`Err`, so the type system forces both
arms to be handled rather than letting an exception escape unannounced.

This is the one place froot leans on functional error handling; the rest of the
domain expresses its invariants through types and validators.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final


@final
@dataclass(frozen=True, slots=True)
class Ok[T]:
    """A successful result carrying a value."""

    value: T


@final
@dataclass(frozen=True, slots=True)
class Err[E]:
    """A failed result carrying an error."""

    error: E


# A computation that either succeeds with a ``T`` or fails with an ``E``.
# Callers pattern-match (``match r: case Ok(v): ... case Err(e): ...``); mypy
# proves both arms are handled.
type Result[T, E] = Ok[T] | Err[E]


def unwrap[T, E](result: Result[T, E]) -> T:
    """Return the value of an :class:`Ok`, or raise if it is an :class:`Err`.

    For call sites where an :class:`Err` is genuinely a programming error
    (tests, already-validated inputs), not an expected outcome.

    Args:
        result: The result to unwrap.

    Returns:
        The contained value.

    Raises:
        ValueError: if ``result`` is an :class:`Err`.
    """
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise ValueError(f"unwrap on Err: {error!r}")
