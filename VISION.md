# froot — the north star

froot is a **common chassis for many pluggable maintenance loops, pointed at any
repo.** The end state is a **code factory**: loops that inspect, repair, and
eventually *fabricate* code — feeding each other through shared truth, each
earning the right to act as far as its work can be objectively verified.

This file is the direction. [`SPEC.md`](./SPEC.md) is the present design; this is
where it is headed. It is grounded throughout in **Many Hands Engineering**
(`../many-hands-engineering/many-hands-engineering.typ`) — read the source before
building, and don't pattern-match from fragments.

## The thesis

A loop is a *control loop* in the control-theory sense: observe a signal, act to
close the gap, verify, repeat to convergence. A repo has an implicit **desired
state** — dependencies current, no dead code, no determinism hazards, no security
debt, … — and froot continuously reconciles the actual repo toward it.

The bet: **at sufficient loop density, code health stops being a property of the
contributors and becomes a property of the substrate.** You stop *doing*
maintenance and start *running* it. Humans (and AI) do net-new; froot holds the
line. The "emergent development" is what's left over when nobody is spending
cycles fighting rot — and the sharper end state is *loops feeding each other and
loops acting as developers*: a small code factory that runs the line itself.

This is also the timely bet: when humans + AI write code 10× faster, *writing* is
no longer scarce — *keeping it healthy* is. froot is the homeostasis layer for
the age of AI-generated code.

## The factory, made literal

An assembly line has **stations** (each does one bounded thing), a **conveyor**
(work flows between them), **QC** (every part inspected before it ships), a
**foreman** (schedules the line, clears jams), and a **plant manager** (the human
— sets *what* gets built, not *how*). Map it:

- **Stations = loops.** Pluggable, single-purpose.
- **Conveyor = the shared truth** (GitHub + the run-ledger). A loop's output *is*
  another loop's input — see "loops feed each other" below.
- **QC = CI + the gate.** Every part, every station, the same inspection.
- **Foreman = Core** (the Temporal spine: schedule, scan/dispatch, reconcile).
- **Plant manager = the steward** (policy + the allowlist).

froot today is a **repair line** (bump, patch, remove). "Loops as developers"
means adding **fabrication stations** (write new code) to that line. The chassis
is the factory floor *plus the safety systems that let you bolt on any station
without rewiring the plant.*

## What the chassis must own (so loops stay thin and pluggable)

1. **The loop contract.** A loop is `(signal, candidate, action, oracle,
   judgment)`. Core schedules / verifies / gates; the loop only fills those
   slots. The unlock is **an open registry, not a closed enum** — add a loop
   without touching the spine. (Today `Loop` is an enum the spine branches on;
   turning it into a registry is the architectural step that makes froot "a
   chassis you plug loops into.")
2. **A pluggable executor for the action.** Mechanical (run a command, edit a
   manifest, delete a symbol) *or* agentic (an LLM coding harness in a sandbox).
   Same contract, two executor kinds — this is how the spine stays
   *spine-heavy, model-thin* for repair loops while still hosting model-heavy
   fabrication loops.
3. **Sandboxing / blast-radius.** A dependency bump is safe in-process; a
   fabrication loop writing arbitrary code needs an isolated worktree, a tool
   allowlist, resource caps. Isolation scales with how dangerous the station is —
   this is where per-loop worker images eventually earn their keep.
   - **The first sandbox is e2b — external Firecracker microVMs.** The worker
     never installs or runs a repo's toolchain (the invariant); but some signals
     need it — e.g. Python dead-code (`deptry`) must run where the deps are
     installed. froot tars the *existing* checkout into an e2b microVM (so the
     GitHub token never enters it), runs `uv sync` + `deptry` there, and reads
     back the JSON. The microVM has egress to the package registries but no path
     back into the cluster. *Shipped — the uv dead-code arm runs this on every
     `@uv` repo each tick; with no `FROOT_E2B_API_KEY` it degrades to no-op.*
   - **The sandbox now hosts an *action*, not just a signal.** The dead-export
     codemod is the first: deleting a truly-dead exported symbol (vs. just
     un-exporting it) needs an AST, which the Python worker can't run — so a
     Node + `ts-morph` codemod runs in the same e2b sandbox, mutates the
     checkout, and returns the edits as a `{path: content}` map on stdout; the
     worker applies them and pushes, CI the oracle. *Shipped — this is the
     reusable `run-in-sandbox → apply-edits` seam the agentic fabrication harness
     later rides (it swaps the deterministic codemod for the LLM harness behind
     the same seam); with no `FROOT_E2B_API_KEY` it falls back to the in-worker
     regex un-export.*
   - **e2b sidesteps the in-cluster microVM problem by being off-cluster.** DOKS
     gives no guaranteed `/dev/kvm`, so *in-cluster* Kata/Firecracker degrade to
     software emulation and gVisor would be the only viable in-cluster strong
     isolation. e2b runs the Firecracker VMs on its own infrastructure, so that
     constraint never binds. An earlier plan used the target's own CI
     (`workflow_dispatch`) as the sandbox; e2b won because it isolates the
     *signal* without coupling froot to each repo's CI wiring — and the *action*
     (remove + relock) stays lockfile-only on the worker, with CI still the
     oracle for the resulting PR.
   - **Agentic executors stay replay-safe via the durable-execution pattern.**
     When a loop's action becomes an LLM coding harness, wrap it so its
     model/tool calls are *recorded Temporal activities* (Pydantic AI's
     `TemporalAgent` does exactly this) — the workflow stays deterministic
     regardless of what the sandbox does. The determinism bar is
     bounded/idempotent (pin base-image-by-digest, pin tool versions, key off
     the lockfile hash), not bit-for-bit.
4. **The universal gate.** Nothing merges without CI **and** earned, per-class,
   revocable autonomy. The gate is the one safety system that makes *any* station
   safe to add and run unattended.

## Loops feed each other through shared truth

froot **derives, never stores.** A loop's output — a merged PR, a recorded
outcome, a label — lives in GitHub + the run-ledger, which is exactly what other
loops read as *their* signal. dead-code removes an export → the dependency is now
unused → dependency-patch's signal fires next tick. **The repo state is the bus.**
No bespoke message queue; composition falls out of the shared substrate. (This is
SPEC Stage 4, "Coordinate," made real.)

Designed-for, not hoped-for: a loop's output being another loop's input is the
mechanism of the compounding — so it is worth treating a loop's signal as
something other loops legitimately produce.

## The governing principle: a loop earns autonomy only as far as its oracle is trusted

A **mechanical** loop (bump, remove) has a near-perfect oracle: CI either still
passes or it does not. It can earn full autonomy. A **fabrication** loop's output
("implement this") passes CI and can still be wrong, ugly, or subtly off — green
CI ≠ good code, and an LLM grading LLM-written code is a far weaker oracle than CI
catching a broken build.

So: **autonomy is granted in proportion to how objectively a loop's work can be
verified.** This single rule orders the whole build:

- **test-backfill** — oracle: coverage rose *and* the new tests pass *and* they
  actually assert. Clean-ish → a strong first fabrication loop.
- **flaky-test fixer** — oracle: the measured flake rate drops (the run-ledger
  already sees it). Clean → excellent, bounded, measurable.
- **TODO-resolver** — oracle murky → stays propose-only longer.
- **feature-implement** — no objective oracle → stays human-gated, perhaps
  forever. That is fine; not every station runs lights-out.

The factory runs lights-out exactly where the oracle is trustworthy, and stays
supervised everywhere else — and the gate already encodes that distinction per
class.

## Hard problems (named, not hand-waved)

1. **The oracle problem** for fabrication loops — CI is necessary, not
   sufficient. The deep-review leg helps; it is not a build oracle. This is the
   ceiling on lights-out fabrication.
2. **Cross-loop oscillation** — control loops ring without damping; loop A's fix
   re-triggers loop B which re-triggers A. Needs convergence discipline:
   idempotency (have it, via deterministic ids), "don't act on your own output,"
   cycle detection, and a global tick/PR budget so a cascade can't flood a repo.
3. **Trust at scale** — autonomy is per-`(repo, loop)`, and most classes have
   tiny volume → never enough evidence → the factory stalls back into
   "human reviews everything." "Many many loops" needs trust to *generalize*: a
   loop-*type* prior (dead-code earned on four repos → a new repo starts with a
   head-start, not from zero) or shared fleet evidence. The long tail decides
   whether more loops is liberating or just a bigger review queue.

## The build arc

1. **Mechanical repair loops** — dependency-patch ✓, security-patch ✓, and
   **dead-code** (unused dependencies, whole unused files, and unused exports):
   npm via `knip` ✓ — static analysis, no install, so it fits the clone-only
   worker, and the file/export arms are froot's first edits to *source* (a file
   deleted, an `export` stripped in place). The uv arm (`deptry`, deps only) ✓ —
   it runs `uv sync` + `deptry` in an external e2b microVM (the deps must be
   installed), the sandbox above. A safe-to-remove judge vetoes *at the signal*
   (a tool used without an import, a framework entry loaded by convention, never
   becomes a PR), and CI stays the oracle.
2. **The enum → loop-registry refactor** — the moment froot stops being "a few
   loops" and becomes "the chassis you plug loops into."
3. **Fabrication loops** — ordered by oracle strength (test-backfill, flaky-fix
   first), behind the same gate.

> One sentence for the box: **froot is the factory floor — a durable chassis
> where pluggable loops inspect, repair, and (eventually) fabricate code, each
> earning the right to act as far as its work can be objectively verified.**
