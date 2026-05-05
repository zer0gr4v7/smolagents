"""An offline ``Model`` impl so OpenClaw runs in CI/tests without API keys.

The optimizer in ``optimizer.py`` does *all* the actual decision-making on its
own (it's a math object, not an LLM call). The smolagents ``CodeAgent`` layer
exists to give each niche a *narrative* agent that can be inspected, prompted,
and later upgraded to a real LLM via ``OpenClawConfig.model``. This mock model
satisfies the smolagents ``Model`` interface by emitting deterministic,
parseable code blocks that simply hand the work back to the optimizer.

In production you replace this with ``LiteLLMModel`` / ``InferenceClientModel``
/ ``OpenAIModel`` via the YAML config. The downstream agent code is identical.
"""

from __future__ import annotations

from typing import Any

from smolagents.models import ChatMessage, MessageRole, Model
from smolagents.monitoring import TokenUsage


__all__ = ["MockNicheModel"]


_RESPONSE_TEMPLATE = """Thought: I'll let the optimizer pick the next lever; I just record the day.

Code:
```py
final_answer({{"status": "ok", "agent": "{slug}"}})
```<end_code>"""


class MockNicheModel(Model):
    """Deterministic stand-in for a real LLM, scoped to one niche agent."""

    def __init__(self, slug: str = "openclaw"):
        super().__init__(model_id=f"openclaw-mock::{slug}")
        self.slug = slug
        self._calls = 0

    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs,
    ) -> ChatMessage:
        self._calls += 1
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=_RESPONSE_TEMPLATE.format(slug=self.slug),
            token_usage=TokenUsage(input_tokens=0, output_tokens=0),
        )
