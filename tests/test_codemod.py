from __future__ import annotations

import json
from pathlib import Path

from froot.adapters.codemod import (
    apply_export_codemod,
    build_codemod_script,
    parse_codemod_edits,
)
from froot.domain.sandbox import SandboxResult
from tests.support import FakeSandbox, make_dead_export


def test_build_codemod_script_embeds_targets_safely():
    script = build_codemod_script("src/a b.ts", "weird'name")
    # The target is a JSON literal inside the heredoc, so quotes/spaces in the
    # path can't break out of the script.
    assert '{"file": "src/a b.ts", "symbol": "weird\'name"}' in script
    assert "npm install ts-morph" in script
    assert "ts-morph" in script and "getExportedDeclarations" in script


def test_parse_codemod_edits_reads_path_content_map():
    out = json.dumps({"src/x.ts": "new text"})
    assert parse_codemod_edits(out) == {"src/x.ts": "new text"}


def test_parse_codemod_edits_is_defensive():
    assert parse_codemod_edits("") == {}
    assert parse_codemod_edits("not json") == {}
    assert parse_codemod_edits(json.dumps([1, 2])) == {}  # not a dict
    # Non-string entries are dropped, valid ones kept.
    assert parse_codemod_edits(json.dumps({"a.ts": "ok", "b.ts": 9})) == {
        "a.ts": "ok"
    }


async def test_apply_export_codemod_writes_the_edits(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.ts").write_text("export const x = 1\n")
    sandbox = FakeSandbox(
        SandboxResult(
            exit_code=0,
            stdout=json.dumps({"src/util.ts": "const x = 1\n"}),
            stderr="",
        )
    )
    item = make_dead_export(file="src/util.ts", symbol="x")
    applied = await apply_export_codemod(tmp_path, item, sandbox=sandbox)
    assert applied is True
    assert (tmp_path / "src" / "util.ts").read_text() == "const x = 1\n"
    # The codemod ran against the checkout the worker handed it.
    assert sandbox.workdirs == [tmp_path]


async def test_apply_export_codemod_false_on_nonzero_exit(tmp_path: Path):
    sandbox = FakeSandbox(
        SandboxResult(exit_code=1, stdout="", stderr="ts-morph blew up")
    )
    applied = await apply_export_codemod(
        tmp_path, make_dead_export(), sandbox=sandbox
    )
    assert applied is False


async def test_apply_export_codemod_false_on_empty_result(tmp_path: Path):
    # The symbol was already gone (codemod emitted {}): nothing applied, so the
    # caller falls back to the in-worker un-export.
    sandbox = FakeSandbox(SandboxResult(exit_code=0, stdout="{}", stderr=""))
    applied = await apply_export_codemod(
        tmp_path, make_dead_export(), sandbox=sandbox
    )
    assert applied is False


async def test_apply_export_codemod_false_when_sandbox_raises(tmp_path: Path):
    class _BoomSandbox:
        async def run(
            self, workdir: Path, script: str, *, timeout_seconds=None
        ) -> SandboxResult:
            raise RuntimeError("FROOT_E2B_API_KEY is unset")

    applied = await apply_export_codemod(
        tmp_path, make_dead_export(), sandbox=_BoomSandbox()
    )
    assert applied is False
