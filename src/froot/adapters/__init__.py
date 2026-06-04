"""Adapters: the concrete impure shell implementing the ports.

Each module backs one :mod:`froot.ports` Protocol with a real integration —
``npm`` (subprocess) and ``uv`` (subprocess + the PyPI registry) for the two
package managers, GitHub + git (httpx + subprocess), the changelog source
(HTTP), and the model judge (Pydantic AI);
:func:`froot.adapters.registry.package_manager_for` picks the package manager
for a target's ecosystem. The pure cores of each — parsing ``npm``/``uv``
output, mapping GitHub checks to a :class:`~froot.domain.ci.CIStatus`, mapping a
model assessment to a verdict — are module-level functions so they are
unit-tested without touching the network. These modules are imported lazily
*inside activity bodies*, never at a workflow module's top level, so the model
and HTTP stacks stay out of the Temporal workflow sandbox.
"""
