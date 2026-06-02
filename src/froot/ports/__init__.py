"""Ports: the typed seam between froot and the impure world.

The workflow spine depends only on these Protocols, never on a concrete client,
so the pure decision flow can be exercised with fakes and the real npm / git /
GitHub / model integrations stay swappable. Adapters in
:mod:`froot.adapters` implement them.
"""
