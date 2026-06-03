# Reading guides

Self-contained, code-level walkthroughs of froot. Open either file in a browser —
each is fully standalone (no network needed), with folding source, inline
diagrams, a navigable table of contents, and a light/dark toggle.

| File | What it is |
|---|---|
| [`froot-explained.html`](./froot-explained.html) | **The essential reading.** A reviewer's cut: ~12 sections covering the architecture, the load-bearing invariants, the loop logic, the ports seam, the safety-critical adapter code, the durable spine, secret handling, the time-skipping test, the deploy, and a verdict. Key code is shown as snippets; expand any block for surrounding context. |
| [`froot-explained-full.html`](./froot-explained-full.html) | **The full edition.** Every one of froot's source lines, plus the tests, infra, and CI, walked top to bottom across 50 sections with 15 diagrams. |

Each claim in these guides was fact-checked against the source, and the prose was
linted for quality. Start with the essential reading; drop into the full edition
when you want the line-by-line detail.
