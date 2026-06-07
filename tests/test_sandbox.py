from __future__ import annotations

import tarfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import froot.config.settings as settings_mod
from froot.adapters.e2b_sandbox import E2bSandbox, workdir_tar
from froot.domain.sandbox import SandboxResult


def test_sandbox_result_ok():
    assert SandboxResult(exit_code=0, stdout="", stderr="").ok
    assert not SandboxResult(exit_code=1, stdout="", stderr="").ok


def _tar_names(blob: bytes) -> set[str]:
    with tarfile.open(fileobj=BytesIO(blob)) as tar:
        return {m.name.lstrip("./") for m in tar.getmembers() if m.isfile()}


def test_workdir_tar_includes_source_and_manifests(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n")
    names = _tar_names(workdir_tar(tmp_path))
    assert "pyproject.toml" in names
    assert "uv.lock" in names
    assert "src/app.py" in names


def test_workdir_tar_excludes_vcs_and_install_trees(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "left-pad.js").write_text("//")
    names = _tar_names(workdir_tar(tmp_path))
    assert names == {"pyproject.toml"}  # .git/.venv/node_modules all dropped


class _FakeCommands:
    def __init__(self) -> None:
        self.runs: list[tuple[str, str | None]] = []

    async def run(self, cmd, cwd=None, timeout=None):
        self.runs.append((cmd, cwd))
        return SimpleNamespace(exit_code=0, stdout="DEPTRY-JSON", stderr="log")


class _FakeFiles:
    def __init__(self) -> None:
        self.writes: list[str] = []

    async def write(self, path, data):
        self.writes.append(path)


class _FakeSandbox:
    def __init__(self) -> None:
        self.commands = _FakeCommands()
        self.files = _FakeFiles()
        self.killed = False

    async def kill(self) -> None:
        self.killed = True


async def test_e2b_sandbox_uploads_runs_in_workdir_and_kills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # The adapter uploads the checkout, runs the script with the upload as cwd,
    # maps the result, and always tears the sandbox down.
    import e2b

    fake = _FakeSandbox()

    async def fake_create(**kwargs):
        return fake

    monkeypatch.setattr(e2b.AsyncSandbox, "create", fake_create)
    monkeypatch.setenv("FROOT_E2B_API_KEY", "test-key")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    result = await E2bSandbox().run(tmp_path, "deptry .", timeout_seconds=120)

    assert result == SandboxResult(
        exit_code=0, stdout="DEPTRY-JSON", stderr="log"
    )
    assert fake.files.writes == ["/tmp/work.tar"]  # checkout uploaded
    assert (
        "deptry .",
        "/tmp/froot-work",
    ) in fake.commands.runs  # ran in the upload dir
    assert fake.killed  # torn down


async def test_e2b_sandbox_raises_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # No API key -> a clear error, not an opaque SDK failure.
    class _NoKey:
        api_key = None
        template = ""
        timeout_seconds = 600

    monkeypatch.setattr(settings_mod, "E2bSettings", _NoKey)
    with pytest.raises(RuntimeError, match="not configured"):
        await E2bSandbox().run(tmp_path, "echo hi")
