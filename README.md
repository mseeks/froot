# froot

*Durable maintenance loops, pointed at any repo.*

> ⚠️ **Experimental, WIP, and written agentically.** froot is an early
> work-in-progress, built largely by AI agents, and currently tailored to the
> author's own projects and infrastructure (its assumptions, conventions, and
> deployment target are all mine). It is **not** general-purpose or
> production-ready for others yet. Generalizing it for other repos — and
> possibly a hosted offering — is future work, not a promise.

froot runs autonomous code-maintenance loops on Temporal. A loop watches a repo for one class
of decay, proposes a bounded fix as a pull request, lets the repo's **own CI** verify it, and
leaves the outcome behind as a signal. A human approves every merge until a class *earns* the
gate — then froot auto-merges its clean, green bumps on an opted-in repo (off by default). The
first loop keeps dependencies patched; froot is the chassis an army of such loops grows on.

See **[SPEC.md](./SPEC.md)** for the what and the why.

Part of an exploration of
[Many Hands Engineering](https://github.com/mseeks/many-hands-engineering) in practice.
