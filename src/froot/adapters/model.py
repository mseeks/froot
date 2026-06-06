"""The model behind the changelog judgment.

A local Ollama (Gemma) driven through its OpenAI-compatible ``/v1`` by Pydantic
AI's OpenAI provider, so froot keeps heavy inference off the request-tight
cluster node. The model and endpoint come from
:class:`~froot.config.settings.ModelSettings` (``FROOT_OLLAMA_MODEL`` /
``FROOT_OLLAMA_URL``); tests pass their own ``TestModel`` / ``FunctionModel``
and never touch this.

This module lives outside the pure core and the workflow modules — the model
stack must never be imported into a Temporal workflow sandbox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from froot.config.settings import ModelSettings

if TYPE_CHECKING:
    from pydantic_ai.models import Model


def build_model(
    *, model_name: str | None = None, base_url: str | None = None
) -> Model:
    """Build the configured Ollama/Gemma model.

    Args:
        model_name: Override the model; defaults to
            ``ModelSettings.ollama_model`` (``$FROOT_OLLAMA_MODEL`` or
            ``gemma4:26b``).
        base_url: Override the endpoint; defaults to
            ``ModelSettings.ollama_url`` (``$FROOT_OLLAMA_URL`` or the local
            Ollama ``/v1``).

    Returns:
        A Pydantic AI model ready to pass to an agent.
    """
    settings = ModelSettings()
    # Ollama ignores the key but the OpenAI client requires a non-empty one.
    return OpenAIChatModel(
        model_name or settings.ollama_model,
        provider=OpenAIProvider(
            base_url=base_url or settings.ollama_url, api_key="ollama"
        ),
    )
