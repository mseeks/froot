from __future__ import annotations

import pytest

from froot.result import Err, Ok, unwrap


def test_unwrap_ok_returns_value():
    assert unwrap(Ok(42)) == 42


def test_unwrap_err_raises():
    with pytest.raises(ValueError):
        unwrap(Err("boom"))
