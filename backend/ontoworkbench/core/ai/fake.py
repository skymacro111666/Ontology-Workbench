"""In-process scripted provider: the only LLM CI ever sees."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.ai.types import (
    Done,
    ModelRequest,
    ModelResponse,
    StreamEvent,
    TextDelta,
    UsageEvent,
)

_CHUNK = 20


class FakeProvider(ModelProvider):
    """Pops scripted responses in order; stream() re-chunks the same data."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        """Store the scripted response list."""
        self._responses = list(responses)

    def _pop(self) -> ModelResponse:
        """Consume the next scripted response or fail the test loudly."""
        if not self._responses:
            raise RuntimeError("FakeProvider exhausted: add more scripted responses")
        return self._responses.pop(0)

    async def complete(self, req: ModelRequest) -> ModelResponse:
        """Return the next scripted response."""
        await asyncio.sleep(0)
        return self._pop()

    async def stream(self, req: ModelRequest) -> AsyncIterator[StreamEvent]:
        """Chunk the next scripted response into the neutral event order."""
        resp = self._pop()
        for i in range(0, len(resp.text), _CHUNK):
            yield TextDelta(resp.text[i : i + _CHUNK])
        for call in resp.tool_calls:
            yield call
        if resp.in_tokens or resp.out_tokens:
            yield UsageEvent(resp.in_tokens, resp.out_tokens)
        yield Done()
