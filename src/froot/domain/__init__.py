"""The pure domain core: frozen, strongly-typed, no I/O, no framework.

Every type here is immutable (a new state is a new value) and closed (unknown
fields are rejected). Invariants live in the types and their validators, so the
illegal states the loop must never reach — a "patch bump" that changes the
minor version, a transaction in two lifecycle states at once — cannot be
constructed. This is the substrate the rest of froot builds on.
"""
