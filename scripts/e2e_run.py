"""Live end-to-end dry run: drive the real froot loop against a real repo.

Starts a local Temporal server, runs the real worker (real activities — real
npm, git, GitHub, Ollama), kicks one scan tick against ``--repo`` (default the
froot-e2e fixture), and waits for the dispatched bump workflow to finish. Reads
the GitHub token from ``.env`` (gitignored). Not part of the package — a dev
harness for validating the loop against live systems.

    uv run python scripts/e2e_run.py [owner/name] [package current target]
"""

from __future__ import annotations

import asyncio
import os
import sys

from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.candidate import PatchCandidate
from froot.domain.repo import RepoRef, TargetRepo
from froot.domain.version import Version
from froot.policy.naming import bump_workflow_id
from froot.result import unwrap
from froot.workflow.bump_workflow import BumpWorkflow
from froot.workflow.runtime import ALL_ACTIVITIES, DATA_CONVERTER, WORKFLOWS
from froot.workflow.scan_workflow import ScanWorkflow
from froot.workflow.types import ScanParams

_SLUG = sys.argv[1] if len(sys.argv) > 1 else "mseeks/froot-e2e"
_PKG = sys.argv[2] if len(sys.argv) > 2 else "is-odd"
_CUR = sys.argv[3] if len(sys.argv) > 3 else "3.0.0"
_TGT = sys.argv[4] if len(sys.argv) > 4 else "3.0.1"

TARGET = TargetRepo(repo=unwrap(RepoRef.parse(_SLUG)))


async def main() -> None:
    async with await WorkflowEnvironment.start_local(port=7233) as env:
        os.environ["TEMPORAL_HOST"] = "127.0.0.1:7233"
        os.environ["TEMPORAL_NAMESPACE"] = "default"
        os.environ["TEMPORAL_TASK_QUEUE"] = "froot"
        config = env.client.config()
        config["data_converter"] = DATA_CONVERTER
        client = Client(**config)
        async with Worker(
            client,
            task_queue="froot",
            workflows=WORKFLOWS,
            activities=ALL_ACTIVITIES,
            max_concurrent_activities=4,
        ):
            print(f">> scan (one-shot) of {_SLUG}", flush=True)
            scan = await client.execute_workflow(
                ScanWorkflow.run,
                ScanParams(target=TARGET, continuous=False),
                id="froot-scan-e2e",
                task_queue="froot",
            )
            print(f">> scan result: found={scan.found} dispatched={scan.dispatched}", flush=True)
            if scan.found == 0:
                print("!! scan found no patch candidates — nothing to wait for")
                return
            candidate = PatchCandidate(
                package=_PKG,
                ecosystem=TARGET.ecosystem,
                current=unwrap(Version.parse(_CUR)),
                target=unwrap(Version.parse(_TGT)),
            )
            bid = bump_workflow_id(TARGET, candidate)
            print(f">> waiting for bump workflow: {bid}", flush=True)
            outcome = await asyncio.wait_for(
                client.get_workflow_handle_for(BumpWorkflow.run, bid).result(),
                timeout=600,
            )
            print(">> OUTCOME ----------------------------------------")
            print(
                f"   bump:    {outcome.candidate.package} "
                f"{outcome.candidate.current} -> {outcome.candidate.target}"
            )
            print(f"   verdict: {outcome.verdict.kind} — {outcome.verdict.rationale[:90]}")
            print(f"   PR:      #{outcome.pr.number}  {outcome.pr.url}")
            print(f"   branch:  {outcome.pr.branch}")
            print(f"   CI:      {outcome.ci.kind}")


if __name__ == "__main__":
    asyncio.run(main())
