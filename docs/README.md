# Reading guides

froot's code-level reading guides are now hosted at
**[static.mseeks.me/froot](https://static.mseeks.me/froot/)** — they used to live
in this folder as committed HTML, but moved out with the rest of the shareable
pages.

**Overviews**

| Guide | What it is |
|---|---|
| [froot, explained](https://static.mseeks.me/froot/froot-explained) | The reviewer's cut of the codebase — architecture, the load-bearing invariants, the loop, the ports seam, the durable spine, and a verdict. Covers the dependency-patch and determinism-reviewer loops; **predates the read-model dashboard** (regenerate when convenient). |
| [froot learns Python](https://static.mseeks.me/froot/uv-ecosystem-explained) | A walkthrough of the change that adds uv (Python) as froot's second package ecosystem. |

**Per-PR guides** (one per merged change, newest first)

| PR | Guide |
|---|---|
| #5 | [Dashboard: cover the determinism reviewer loop](https://static.mseeks.me/read-thru/froot/pr-5-dashboard-determinism) |
| #4 | [Kernel catch-property + the kernel/brain boundary](https://static.mseeks.me/read-thru/froot/pr-4-kernel-catch-tests) |
| #3 | [Determinism reviewer loop — the transitive ring](https://static.mseeks.me/read-thru/froot/pr-3-determinism-reviewer) |
| #2 | [Temporal determinism gate (workflow boundary)](https://static.mseeks.me/read-thru/froot/pr-2-determinism-gate) |

Each page is self-contained (foldable source, inline diagrams, light/dark) and
every claim was fact-checked against the source. They are generated with
[readthrough](https://github.com/mseeks/readthrough) and served from the
[static](https://github.com/mseeks/static) site.
