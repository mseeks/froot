"""The dead-export codemod — froot's first *action* run in the sandbox.

The dead-code loop's un-export is a one-line regex edit the worker does in
process (see :func:`froot.policy.dead_source.unexport_line`). That is the safe
minimum; the fuller action is to *delete* a truly-dead symbol, which needs an
AST, not a regex — multi-line declarations, proper cleanup. froot's worker is
Python and cannot run a TypeScript AST, so the codemod runs where the deptry
signal already runs: an e2b sandbox (Node + ``ts-morph``).

This is the first time the :class:`~froot.ports.protocols.Sandbox` hosts an
*action* rather than a *signal* — it mutates the checkout and returns the edits,
where ``deptry`` only read it. The sandbox tears down on teardown and only
*stdout* returns, so the codemod emits the changed files as a JSON map of
``{path: content}``; the worker applies it to its checkout, with CI the oracle.
It degrades like the deptry arm: with no ``FROOT_E2B_API_KEY`` (or any error) it
returns ``False`` and the caller falls back to the in-worker un-export.

The codemod is conservative: for the flagged export it deletes the whole
declaration only when nothing else in the file references the symbol; if the
symbol is still used in its own file it just strips the ``export`` (knip already
guarantees no *other* module imports it). The pure pieces (the script builder,
the output parser) are fixture-tested; the Node codemod itself is validated by
running it directly, the same posture as ``deptry`` (untested in CI, integration
truth lives in the tool).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from temporalio import activity

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.dead_source import DeadExport
    from froot.ports.protocols import Sandbox

# The ts-morph codemod, validated against fixtures. Reads ``targets.json``
# ({file, symbol}) and the checkout root from argv; deletes the unused export's
# declaration if the file references it nowhere, else un-exports it; emits the
# changed file as ``{relpath: new_text}`` (empty ``{}`` if the symbol is gone).
_CODEMOD_JS = r"""const { Project, Node } = require("ts-morph");
const fs = require("fs");
const path = require("path");

const base = process.argv[2];
const { file, symbol } = JSON.parse(fs.readFileSync("targets.json", "utf8"));
const abs = path.join(base, file);

const project = new Project({ skipAddingFilesFromTsConfig: true });
const sf = project.addSourceFileAtPath(abs);

const decls = sf.getExportedDeclarations().get(symbol);
if (!decls || decls.length === 0) {
  process.stdout.write("{}");
  process.exit(0);
}
const decl = decls[0];

const nameNode =
  typeof decl.getNameNode === "function" ? decl.getNameNode() : null;
let inFileRefs = 0;
if (nameNode && typeof nameNode.findReferencesAsNodes === "function") {
  for (const ref of nameNode.findReferencesAsNodes()) {
    if (ref.getSourceFile() === sf && ref !== nameNode) inFileRefs++;
  }
}

function exportableOf(d) {
  return Node.isVariableDeclaration(d) ? d.getVariableStatement() : d;
}
if (inFileRefs === 0) {
  if (Node.isVariableDeclaration(decl)) {
    const stmt = decl.getVariableStatement();
    if (stmt && stmt.getDeclarations().length === 1) stmt.remove();
    else decl.remove();
  } else decl.remove();
} else {
  const ex = exportableOf(decl);
  if (ex && typeof ex.setIsExported === "function") ex.setIsExported(false);
}
const out = {}; out[file] = sf.getFullText();
process.stdout.write(JSON.stringify(out));
"""

# The sandbox script: capture the checkout (the script's initial cwd, where the
# tar was extracted), install ts-morph off-checkout, write the codemod + the
# targets, run it. All install noise goes to stderr so stdout is only the JSON
# the worker parses (the same discipline as the deptry script).
_SCRIPT = (
    "set -e\n"
    'WORK="$(pwd)"\n'
    "mkdir -p /tmp/cm && cd /tmp/cm\n"
    "cat > targets.json <<'TARGETS'\n"
    "__TARGETS_JSON__\n"
    "TARGETS\n"
    "cat > codemod.js <<'CODEMOD'\n" + _CODEMOD_JS + "CODEMOD\n"
    "npm init -y >/dev/null 2>&1\n"
    "npm install ts-morph@24 >&2\n"
    'node codemod.js "$WORK"\n'
)


def build_codemod_script(file: str, symbol: str) -> str:
    """The sandbox script that un-exports/deletes ``symbol`` in ``file``.

    ``file``/``symbol`` are embedded as JSON inside a literal heredoc, so a path
    with shell metacharacters can never break out of the script.
    """
    targets = json.dumps({"file": file, "symbol": symbol})
    return _SCRIPT.replace("__TARGETS_JSON__", targets)


def parse_codemod_edits(stdout: str) -> dict[str, str]:
    """Parse the codemod's ``{relpath: new_content}`` JSON (defensive).

    Empty or unparseable output, or a non-string entry, yields ``{}`` — the
    caller reads that as "the codemod did nothing" and falls back.
    """
    try:
        data = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        path: content
        for path, content in data.items()
        if isinstance(path, str) and isinstance(content, str)
    }


def _default_sandbox() -> Sandbox:
    """Build the production sandbox backend (e2b), imported lazily."""
    from froot.adapters.e2b_sandbox import E2bSandbox

    return E2bSandbox()


async def apply_export_codemod(
    workspace: Path, item: DeadExport, sandbox: Sandbox | None = None
) -> bool:
    """Run the codemod in the sandbox and apply its edits to ``workspace``.

    Returns ``True`` iff the sandbox ran cleanly and produced at least one file
    edit (the deletion or un-export landed). Returns ``False`` when the sandbox
    is unconfigured (no ``FROOT_E2B_API_KEY``), errors, exits non-zero, or finds
    nothing — the caller falls back to the in-worker un-export, so a missing
    sandbox never blocks the loop.
    """
    sandbox = sandbox or _default_sandbox()
    script = build_codemod_script(item.file, item.symbol)
    try:
        result = await sandbox.run(workspace, script)
    except Exception as exc:
        activity.logger.warning(
            "export codemod sandbox unavailable for %s; falling back: %r",
            item.symbol,
            exc,
        )
        return False
    if result.exit_code != 0:
        activity.logger.warning(
            "export codemod failed for %s (exit %d); falling back: %s",
            item.symbol,
            result.exit_code,
            result.stderr[-200:],
        )
        return False
    edits = parse_codemod_edits(result.stdout)
    for rel, content in edits.items():
        (workspace / rel).write_text(content)
    return bool(edits)
