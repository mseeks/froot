"""froot's open loop registry — the catalog the spine consumes.

The durable chassis is loop-agnostic; a :class:`~froot.loops.registry.LoopSpec`
is the small, declarative entry that makes a loop a specialist. Each loop module
in this package self-registers at import; the spine reads the registry rather
than branching on the :class:`~froot.domain.loop.Loop` enum. See VISION — an
open loop registry the spine consumes, rather than an enum it branches on.
"""
