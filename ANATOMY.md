# Anatomy — froot as one living map

> A spec for an interactive **anatomy diagram** of froot: the whole system as a
> single graph, walked statically from the code (every workflow, activity,
> child-workflow, and external system as a node; every call as an edge), then
> overlaid with **live traffic from traces** so you can see structure *and* flow
> at once. The static skeleton is exact and complete; the trace heat shows what
> actually runs and how hard.
>
> Read [`SPEC.md`](./SPEC.md) and [`VISION.md`](./VISION.md) first — this view is
> meant to *render* the chassis/loop seam they describe, not redefine it.

## 1. Why this exists

froot is a chassis with a growing set of loops, and the loops increasingly feed
each other through shared truth (VISION, "the factory made literal"). That power
comes at a cost: the call graph lives in your head. New loops, the per-PR vs root
split, the dispatch indirection, the shared acting spine — it's a lot to hold.

This is the cure: one picture you can re-find every time. The goals, in order:

1. **Where does it live in the tree?** Trace any activity back to the workflow
   and loop that drive it.
2. **What's wired to what?** See the real edges — including the indirect ones
   (a workflow that dispatches a child *through* an activity).
3. **What's hot?** Overlay call counts and latency so the busy paths and the cold
   corners are obvious at a glance.

It is **not** a per-trace debugger (HyperDX already does waterfalls), and it does
not replace the read-model dashboard (`dashboard/`) — that stays the source for
reputation and the gate. This is the *map*, not the speedometer.

## 2. The model: two layers fused

### 2.1 Node kinds

| Kind | What it is | How it's found (static) | froot examples |
|---|---|---|---|
| **workflow** | a `@workflow.defn` class | decorator scan | `ScanWorkflow`, `BumpWorkflow`, `PrDocRefsReviewWorkflow` |
| **activity** | an `@activity.defn` function | decorator scan | `scan_candidates`, `judge_changelog`, `merge_pull_request` |
| **external** | a system froot talks to | adapter import/symbol used inside an activity | GitHub, Ollama/Gemma, ClickHouse, npm, uv, knip, deptry, OSV, e2b, ntfy |
| **entrypoint** | what kicks workflows off | `starter.py` / `trigger.py` `start_workflow` calls | the loop starter, the watchdog |

### 2.2 Edge kinds

The edges are where froot's real shape lives — note that several are **indirect**
(froot starts child workflows from inside activities, not from workflow bodies).

| Edge | Meaning | Code pattern matched |
|---|---|---|
| **executes** | workflow runs an activity | `workflow.execute_activity(activities.<fn>, …)` |
| **dispatches** | an activity starts a (child) workflow | `temporal.start_workflow(<Wf>.run, …)` inside an `@activity.defn` |
| **continues** | a durable loop reschedules itself | `workflow.continue_as_new(…)` (self-edge) |
| **reads/writes** | an activity touches an external system | adapter call inside an activity (forge → GitHub, `build_model` → Ollama, etc.) |
| **starts** | the entrypoint launches a root workflow | `start_workflow` in `starter.py` |

So the canonical froot flow is a three-hop chain the diagram must render
faithfully:

```
ScanWorkflow ──executes──▶ dispatch_bump ──dispatches──▶ BumpWorkflow
ReviewWorkflow ─executes─▶ dispatch_pr_review ─dispatches─▶ PrReviewWorkflow
```

### 2.3 Clusters — by loop

froot's natural grouping is the loop (SPEC, "chassis vs loop"). Seven clusters,
plus a cross-cutting spine. **One asymmetry to render honestly:**

- **Acting loops share the spine.** `dependency-patch`, `security-patch`, and
  `dead-code` all run the *same* `ScanWorkflow` + `BumpWorkflow`, parameterized
  by the `Loop` enum. Statically there is **one** Scan/Bump node pair, used by
  three loops. The per-loop split is only visible at runtime — via the
  `froot.scan_loop` span attribute (see §4). So those nodes belong to three
  clusters at once; draw them once, in a shared "acting spine" lane, and let the
  heat overlay split their traffic by loop.
- **Advisory loops each have their own workflow classes.** `determinism-review`,
  `a11y-review`, `doc-refs`, `doc-coherence` each get a distinct
  `*ReviewWorkflow` + `Pr*ReviewWorkflow` pair, so they're naturally separate
  clusters.

| Cluster | Disposition | Root WF | Per-item WF | Signature activities |
|---|---|---|---|---|
| dependency-patch | acting | ScanWorkflow* | BumpWorkflow* | scan_candidates, dispatch_bump, judge_changelog, open_pull_request, check_ci, gate_review, merge/close_pull_request, record_outcome |
| security-patch | acting | ScanWorkflow* | BumpWorkflow* | (shared spine, OSV-derived signal) |
| dead-code | acting | ScanWorkflow* | BumpWorkflow* | (shared spine, knip/deptry signal) |
| determinism-review | advisory | ReviewWorkflow | PrReviewWorkflow | list_review_prs, dispatch_pr_review, analyze_pr, adjudicate_frontier, post_review |
| a11y-review | advisory | A11yReviewWorkflow | PrA11yReviewWorkflow | scan_pr_a11y, adjudicate_a11y, post_a11y_review |
| doc-refs | advisory | DocRefsReviewWorkflow | PrDocRefsReviewWorkflow | scan_pr_doc_refs, adjudicate_doc_refs, post_doc_refs_review |
| doc-coherence | advisory | DocCoherenceReviewWorkflow | PrDocCoherenceReviewWorkflow | run_doc_coherence_agent, post_doc_coherence_review |

`*` = shared, parameterized by loop. Cross-cutting spine (its own lane):
`starter`, `watchdog`, `worker`, `dashboard`, plus the gate activities
(`auto_merge_eligible`, `gate_selftest`, `gate_review`) and `reconcile_open_prs`.

## 3. Static layer — the skeleton (AST walk)

The skeleton is pure static analysis: exact, complete, deterministic, and free of
runtime noise. froot already AST-walks its own `@workflow.defn` code in
[`scripts/check_determinism.py`](./scripts/check_determinism.py) — the extractor
**reuses that approach** (`ast.parse` → walk `ClassDef`/`FunctionDef` with the
relevant decorator → inspect `Call` nodes). It lives in `froot/anatomy.py` (a normal module, also
runnable as a CLI) and — crucially — **the dashboard runs it at load time against
froot's own installed source**, so the map is always the code that's actually
deployed (see §7). No generation step, no committed artifact, no drift.

What it does, per module under `src/froot/`:

1. **Find nodes.** Collect every `@workflow.defn` class and every `@activity.defn`
   function (name, file, line, docstring-summary).
2. **Find edges inside workflow bodies.** Within each workflow's `run`/signal/
   query methods, match `workflow.execute_activity(<ref>, …)` → resolve `<ref>`
   to an activity node → **executes** edge. Match `workflow.continue_as_new(…)`
   → **continues** self-edge. Match any direct `execute_child_workflow` /
   `start_child_workflow` (froot uses none today, but handle it).
3. **Find edges inside activity bodies.** Within each `@activity.defn`, match
   `temporal.start_workflow(<Wf>.run, …)` → resolve `<Wf>` → **dispatches** edge
   (activity → workflow). This is how froot's root loops reach their children;
   the walker must follow it.
4. **Find external edges.** Within each activity, detect use of the known I/O
   adapters by imported symbol — the forge (`GitHubForge` → GitHub),
   `build_model` (→ Ollama), the ClickHouse reader, npm/uv/knip/deptry/OSV
   helpers, e2b, ntfy — and emit **reads/writes** edges to external nodes. This
   is a heuristic keyed on the `adapters/`/`ports/` surface; it will miss a
   novel adapter until taught, which is acceptable and easy to extend.
5. **Attribute clusters via the registry.** Read the loop registry
   (`loops/registry.py`, `LoopSpec`/`CommitTail`/`AdvisoryTail` and the per-loop
   `loops/<name>.py` modules) to map each workflow/activity to its loop cluster.
   For the shared acting spine, tag the Scan/Bump nodes with *all* acting loops
   and mark them `shared: true`.
6. **Return the graph** — an in-memory object. The JSON below is its serialized
   shape (the API response), *not* a file checked into the repo.

```jsonc
{
  "generatedFrom": "<git sha>",
  "nodes": [
    { "id": "wf:ScanWorkflow", "kind": "workflow", "label": "ScanWorkflow",
      "file": "src/froot/workflow/scan_workflow.py", "line": 40,
      "clusters": ["dependency-patch","security-patch","dead-code"],
      "shared": true, "summary": "durable per-repo scan loop" },
    { "id": "act:judge_changelog", "kind": "activity", … },
    { "id": "ext:ollama", "kind": "external", "label": "Ollama / Gemma" }
  ],
  "edges": [
    { "from": "wf:ScanWorkflow", "to": "act:dispatch_bump", "kind": "executes" },
    { "from": "act:dispatch_bump", "to": "wf:BumpWorkflow", "kind": "dispatches" },
    { "from": "act:judge_changelog", "to": "ext:ollama", "kind": "reads" },
    { "from": "wf:ScanWorkflow", "to": "wf:ScanWorkflow", "kind": "continues" }
  ]
}
```

Node IDs are stable (`<kind>:<symbol>`) so the trace layer can join to them.

**Built from source, every load — never regenerated.** The walker finds froot's
package via its import path and parses the `.py` files on disk: the same source
the running image was built from. The result is cached in-process and invalidated
by file mtime, so:

- in the **deployed image** (immutable source) it parses **once** per process, and
  every load after is instant and exactly the deployed code;
- in **local dev** (dashboard run against the working tree) editing a workflow and
  reloading re-walks and shows the change — no restart, no regen step.

That's the whole point of doing it this way: the map *can't* go stale, because
there's nothing to keep in sync — it **is** the source. (A `python -m froot.anatomy
--json` dump exists only as an escape hatch for hosting the view somewhere without
the source on disk; it is a fallback, not the path.)

## 4. Dynamic layer — the heat (traces)

The heat comes from the OTel traces froot already emits.

- **Source:** the trace store (ClickStack's `otel_traces` table in this
  deployment; any OTLP-backed store works), filtered to
  `ServiceName = 'froot-worker'`. The exact endpoint is deployment config
  (env-driven), kept out of this repo.
- **Span names (Temporal's OTel interceptor convention):**
  `RunWorkflow:<Class>` and `RunActivity:<fn>` — confirmed by the dashboard's
  [`clickhouse_source.py`](./src/froot/dashboard/clickhouse_source.py), which
  already aggregates `SpanName LIKE 'RunActivity:%'`. Child-dispatch shows up as
  `StartWorkflow:<Class>` / a fresh `RunWorkflow:<Class>` trace. **Verify the
  exact prefixes against the live store before wiring.**
- **Per-node metrics**, over a selectable window: call count, p50/p95/max
  duration, error rate (`StatusCode='Error'`), last-seen. Map
  `RunActivity:judge_changelog` → `act:judge_changelog`,
  `RunWorkflow:ScanWorkflow` → `wf:ScanWorkflow`.
- **Per-edge metrics:** caller→callee frequency, via a self-join of `otel_traces`
  on `SpanId = ParentSpanId` — the parent span's name is the caller, the child's
  is the callee. This reconstructs *which workflow ran which activity, how often*.
- **Split the shared spine per loop.** Because `ScanWorkflow`/`BumpWorkflow` are
  shared, use the `froot.scan_loop` span attribute (set in `scan_candidates`) to
  attribute their traffic to `dependency-patch` vs `security-patch` vs
  `dead-code`. This is what lets the diagram color the shared node by loop.
- **Output:** `anatomy.weights.json`, keyed by the same node/edge IDs.

**Temporal trace caveats** (the real tax — document the handling):

- **continue-as-new** starts a fresh trace per tick, so the perpetual root loops
  fragment into many short traces. Aggregate across them; don't expect one giant
  tree.
- **Replay** can re-emit workflow spans; dedup on `(TraceId, SpanId)`.
- **Activity vs workflow spans** are linked through context propagation, not
  always strict parent/child nesting — rely on `ParentSpanId` but be ready to
  fall back to span links for the dispatch hop.
- **Sampling/retention:** the store holds a rolling window (3 days here), so the
  heat is "recent," not all-time — label it as such.

## 5. Fusion + the diff (where the insight is)

The static graph is the **source of truth for topology**; the trace weights only
*annotate* it. That asymmetry produces two free insights:

- **Cold nodes** — defined in code, no traffic in the window → drawn dim. (A loop
  that's enabled but idle, or dead code.)
- **Surprise edges** — present in traces but absent from the static graph → drawn
  in alarm color. Either the walker missed an edge (teach it) or something is
  calling something it shouldn't (a real finding).

For froot specifically, the fused view should make the chassis legible: the three
acting loops collapsing onto one shared spine, the four advisory loops fanning out
as parallel root→per-PR pairs, and every loop's activities terminating at the same
few externals (GitHub, Ollama). That convergence *is* "derive, never store" drawn
as a picture.

## 6. Visualization

**Not Mermaid, not a force-directed hairball.** At ~30–50 nodes with clusters and
cross-links, Mermaid's auto-layout tangles and it can't carry interactivity or the
heat overlay; a physics layout drifts and re-tangles every load, which defeats
"re-find it every time." An anatomy diagram needs a **stable, hierarchical, layered
layout** you can build a memory of.

**Recommended stack:**

- **Layout: [ELK](https://github.com/kieler/elkjs) (`elkjs`)** — its layered
  (Sugiyama) algorithm is the best fit for a directed, clustered DAG; it supports
  compound nodes (the loop clusters as bounding boxes) and gives deterministic,
  legible top-to-bottom flow.
- **Render + interaction: [Cytoscape.js](https://js.cytoscape.org/)** with the ELK
  layout extension. It's mature, loads from a single script tag (no bundler — fits
  froot's "one self-contained page" delivery, like the dashboard), has compound
  nodes for clusters, and rich events/styling/pan-zoom out of the box.
- **Alternative** for a richer custom-node UI (node "cards" showing live stats):
  **React Flow (`@xyflow/react`) + elkjs** — nicer components, at the cost of a
  Vite/React build step. Pick this only if the card UI earns the toolchain.
- **Ruled out:** Mermaid (static, poor layout at scale, no heat/interaction);
  raw `d3-force` (hairball, unstable). D3 is still handy for color scales and the
  legend, just not for the graph layout.

**Layout shape:** entrypoints at the top → root workflows → activities → externals
at the bottom/periphery; each loop a labeled lane/box; the shared acting spine in
its own lane that three loop-lanes point into.

**Encoding:**

| Channel | Encodes |
|---|---|
| node shape | kind (workflow = rounded rect, activity = pill, external = cylinder, entrypoint = chip) |
| node size | call count (trace) |
| node color | error rate (or latency heat); cold = dim |
| edge thickness | call frequency (trace) |
| edge style | kind (executes = solid, dispatches = solid+arrowhead, continues = looped dashed, reads/writes = dotted to external) |
| cluster box | loop (acting lanes warm, advisory lanes cool) |

**Interactions:** hover → tooltip (count, p50/p95, error rate, `file:line`); click
node → focus its neighborhood, dim the rest; filter by loop; time-window selector;
toggle skeleton-only vs heat; search; "show surprises." Always-on **legend** —
an anatomy chart needs its key.

## 7. Pipeline + delivery

The view is served **in-process by the worker**, which is where froot's source
already lives — the read-model dashboard (`dashboard/`) runs in the same process,
so this rides alongside it. Per request (or refresh):

1. **Skeleton:** build the static graph by AST-walking froot's installed source
   (§3) — parsed once per process, mtime-invalidated, so it's always the running
   code with no generation step and nothing to keep in sync.
2. **Heat:** query the trace store for the selected window, build the per-node /
   per-edge weights (§4).
3. **Fuse + serve:** merge by ID and return one self-contained page (the graph +
   the Cytoscape/ELK render). Same shape as the dashboard — a small read-only
   handler, no build toolchain.

Because the skeleton is built from source at load, **nothing needs updating when
the code changes**: redeploy (new image → new source) and the map follows;
locally, just reload. Only the trace overlay depends on the deployment — the
trace-store endpoint, refresh cadence, auth, and hosting are config (env-driven)
and live with the workspace infra, not in this repo.

## 8. Phasing

- **P1 — skeleton.** The in-process AST walk (`froot/anatomy.py`, built from
  source on load) + a layered ELK/Cytoscape render of the static graph, clustered
  by loop, served from the worker. Ship it; eyeball whether the structure reads.
  (This alone answers "where does it live in the tree," and is already
  always-fresh.)
- **P2 — heat.** Add the trace overlay: node/edge weights, the per-loop split of
  the shared spine, hover stats.
- **P3 — polish.** Cold-node dimming, surprise-edge detection, window selector,
  search, focus mode, deployment behind the workspace's auth.

## 9. Risks & open questions

- **Temporal trace shape** (continue-as-new fragmentation, replay, link-vs-nest)
  is the main tax — §4 lists the mitigations; budget time for it in P2.
- **External-edge heuristics** key on the adapter surface; a new adapter is
  invisible until taught. Acceptable; revisit if `adapters/` grows a lot.
- **The shared acting spine** is the one modeling subtlety — get the "one node,
  many loops, split by span attribute" handling right or the acting loops will
  look like they don't exist as distinct things.
- **Build-from-source cost.** The runtime AST walk is sub-second over froot's
  tree and cached per process, so it's negligible — but it does mean the view runs
  where the source is (the worker image), which is why it's served in-process
  rather than as a source-less static site. The `--json` dump is the escape hatch
  if a source-less host is ever needed.
- **Span-name prefixes** must be confirmed against the live store (the dashboard
  confirms `RunActivity:`; confirm the workflow/dispatch prefixes).

## 10. Non-goals

- Not a live per-execution trace viewer (HyperDX covers that).
- Not a replacement for the read-model dashboard or the gate.
- Not cross-service (froot and ynab-agent don't call each other; a future "atlas"
  could place their two maps side by side, but they share no edges).
- Not real-time streaming; a periodic heat refresh is plenty.
