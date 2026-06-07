# Building froot

Read this before changing anything here. It binds every change to froot's
direction and to the framework it is an instance of.

## Orient first (always)

1. **[`VISION.md`](./VISION.md)** — the north star: froot is a *common chassis
   for many pluggable maintenance loops*, headed toward a *code factory* where
   loops feed each other and (eventually) act as developers. Every change should
   move toward that or stay faithful to it.
2. **[`SPEC.md`](./SPEC.md)** — the present design: the chassis/loop seam, the
   reputation read-model, the staged roadmap.
3. **Many Hands Engineering** —
   `../many-hands-engineering/many-hands-engineering.typ`. froot *is* an instance
   of MHE. **Read the source thoroughly and build an intuitive grasp of it before
   acting on anything MHE-related** — do not pattern-match from fragments or
   secondhand summaries. The nuances that must stay aligned: the loop anatomy
   (signal → action → verification → commit/revert → update, plus its six
   ingredients incl. the authority surface); the staged transition (§3.4); the
   trust economy and its five properties (§3.6–3.7); triangulation — a target
   needs ≥2 independent metrics gaming would harm (§3.8); security as a distinct
   trust dimension (§3.9); deliberate disturbance / the adversarial probe
   (§2.11). When froot and MHE seem to disagree, re-read MHE — froot is wrong
   until proven otherwise.

## Invariants that always hold

- **Spine-heavy, model-thin.** The durable spine does the work; the model makes
  one or two thin, non-load-bearing judgments. A repair loop should add ~no model
  weight. Fabrication loops carry a heavier executor — keep it behind the action
  slot, never in the spine.
- **Derive, never store.** froot keeps no database. Reputation and every signal
  are recomputed from shared truth (GitHub + the run-ledger). This is also *how
  loops feed each other* — a loop's output in the shared substrate is another
  loop's input. Don't add a store.
- **CI is the oracle.** A loop's action is verified by the repo's own CI, not by
  the model's say-so. **A loop earns autonomy only as far as its oracle can be
  trusted** (VISION §"governing principle") — mechanical loops earn fully;
  fabrication loops earn in proportion to oracle strength.
- **The gate governs every loop, uniformly.** Nothing merges without CI + earned,
  per-class, revocable autonomy + the deep review. Adding a loop must not add a
  bypass.
- **Pure core, effect-driven spine.** Domain + policy are pure and total (MyPy
  strict, invalid states unrepresentable); the state machine returns effects as
  data; activities are the only I/O. Keep nondeterminism out of `@workflow.defn`
  bodies — the determinism gates enforce this.
- **The chassis/loop seam (SPEC).** What makes a loop a specialist is only its
  *signal*, its *action* (per-ecosystem command/edit), and its *prompt*.
  Everything else is the chassis. When you add a loop, add a loop — do not fork
  the spine. (The enum → registry refactor in VISION is the path to making this
  literally true.)

## Build discipline

- **Slices, chained.** Small, independently-green commits. Add the *discriminating*
  test that only the new layer could catch — not coverage padding.
- **Full suite green before done.** `make check` (ruff format + lint, mypy,
  pytest) **and** both determinism gates (`scripts/check_determinism.py src` +
  `check_determinism_transitive.py`) pass. Show the evidence.
- **Boot it / lay eyes on it.** For the dashboard, render and screenshot; for a
  loop, give a concrete way to watch its signal flow (a structured log, a
  dashboard panel).
- **Adversarial verification.** Delegate serious checks to independent review;
  don't bias toward the answer you want.

## When adding a loop, answer these (the loop contract)

1. **Signal** — what mechanically detects the decay? (a CLI tool, an AST/regex
   sweep, an advisory feed). Heterogeneous on purpose; never force it behind one
   interface.
2. **Candidate** — the bounded unit of work. (A bump is `package@version`; a
   dead-code item is a finding; future kinds differ — generalize the work item,
   don't shoehorn it into the bump-shaped `Candidate`.)
3. **Action** — mechanical (edit/remove/bump) or agentic (a sandboxed coding
   harness). Per-ecosystem where it must be.
4. **Oracle** — how CI (or an objective measure) confirms the action. This
   decides how far the loop can earn autonomy.
5. **Judgment** — the one thin model call (e.g. "is this changelog clean?", "is
   this safe to remove?"), framed by the loop.

If a change doesn't fit these, it probably belongs in the chassis, not a loop —
or the abstraction needs widening (toward the registry). Prefer widening the seam
over special-casing the spine.
