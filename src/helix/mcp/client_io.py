"""``McpClientIO`` — the standardized seam, backed by a live MCP session.

``sample`` and ``elicit`` are *synchronous* (the pipeline core that calls
them is a plain loop running in a worker thread). They hop to the server's
event loop via ``anyio.from_thread.run`` — the single sync↔async bridge,
shared by model calls and user prompts alike.

SDK-contact is confined to this file (+ ``server.py``). ``helix.io`` emits
spec-shaped flat JSON-schema dicts; we pass them straight to the raw
``elicit_form`` (which, unlike FastMCP's model wrapper, accepts enum/choice
schemas), so there is no dict↔model translation anywhere.
"""

from __future__ import annotations

import anyio

from ..io import ClientIO, ElicitRequest, ElicitResult
from ..llm import LLMResponse


class McpClientIO(ClientIO):
    def __init__(self, ctx):
        # ctx: a FastMCP Context for the in-flight tool call.
        self._ctx = ctx

    # --- async halves: run on the MCP event loop --------------------------

    async def _sample(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        from mcp.types import SamplingMessage, TextContent

        result = await self._ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=user),
                )
            ],
            system_prompt=system,
            max_tokens=max_tokens,
        )
        content = result.content
        text = content.text if getattr(content, "type", None) == "text" else str(content)
        return LLMResponse(content=text, usage={}, cost=0.0)

    async def _elicit(self, req: ElicitRequest) -> ElicitResult:
        session = self._ctx.request_context.session
        result = await session.elicit_form(
            message=req.message,
            requestedSchema=req.schema,
            related_request_id=self._ctx.request_id,
        )
        if result.action == "accept":
            return ElicitResult(action="accept", data=dict(result.content or {}))
        return ElicitResult(action=result.action, data={})

    # --- sync seam: called from the pipeline worker thread ----------------

    def sample(self, *, system: str, user: str, max_tokens: int) -> LLMResponse:
        return anyio.from_thread.run(self._sample, system, user, max_tokens)

    def elicit(self, req: ElicitRequest) -> ElicitResult:
        return anyio.from_thread.run(self._elicit, req)
