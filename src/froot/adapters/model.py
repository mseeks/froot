"""The model behind the changelog judgment.

A local Ollama (Gemma) driven through its OpenAI-compatible ``/v1`` by Pydantic
AI's OpenAI provider, so froot keeps heavy inference off the request-tight
cluster node. The model and endpoint come from
:class:`~froot.config.settings.ModelSettings` (``FROOT_OLLAMA_MODEL`` /
``FROOT_OLLAMA_URL``); tests pass their own ``TestModel`` / ``FunctionModel``
and never touch this.

Every request carries an ``X-Model-Client`` header naming the caller
(``froot/<activity>`` when built inside an activity, else ``froot``) so the
cluster's model proxy can attribute traffic per loop. One process-wide httpx
client is shared (no per-call connection-pool leak); an async event hook stamps
the header from a :class:`~contextvars.ContextVar` set in :func:`build_model`,
which keeps it correct when activities run concurrently.

This module lives outside the pure core and the workflow modules — the model
stack must never be imported into a Temporal workflow sandbox.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

import httpx
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from temporalio import activity

from froot.config.settings import ModelSettings

if TYPE_CHECKING:
    from pydantic_ai.models import Model

_caller: contextvars.ContextVar[str] = contextvars.ContextVar(
    "model_caller", default="froot"
)
_clients: dict[str, httpx.AsyncClient] = {}


async def _stamp_caller(request: httpx.Request) -> None:
    """Tag each outbound model request with the current caller."""
    request.headers["X-Model-Client"] = _caller.get()


def _http_client() -> httpx.AsyncClient:
    """The one process-wide client; the event hook tags each request."""
    client = _clients.get("default")
    if client is None:
        client = httpx.AsyncClient(event_hooks={"request": [_stamp_caller]})
        _clients["default"] = client
    return client


def _caller_tag() -> str:
    """``froot/<activity>`` inside an activity, else ``froot``."""
    try:
        return f"froot/{activity.info().activity_type}"
    except RuntimeError:
        return "froot"


def build_model(
    *, model_name: str | None = None, base_url: str | None = None
) -> Model:
    """Build the configured Ollama/Gemma model.

    Args:
        model_name: Override the model; defaults to
            ``ModelSettings.ollama_model`` (``$FROOT_OLLAMA_MODEL`` or
            ``gemma4:12b``).
        base_url: Override the endpoint; defaults to
            ``ModelSettings.ollama_url`` (``$FROOT_OLLAMA_URL`` or the local
            Ollama ``/v1``).

    Returns:
        A Pydantic AI model ready to pass to an agent. Requests carry an
        ``X-Model-Client`` header naming the caller for proxy-side attribution.
    """
    settings = ModelSettings()
    _caller.set(_caller_tag())
    # Ollama ignores the key but the OpenAI client requires a non-empty one.
    return OpenAIChatModel(
        model_name or settings.ollama_model,
        provider=OpenAIProvider(
            base_url=base_url or settings.ollama_url,
            api_key="ollama",
            http_client=_http_client(),
        ),
    )
