"""``McpClientIO`` — the standardized seam, backed by a live MCP session.

``sample`` and ``elicit`` are *synchronous* (the pipeline core that calls
them is a plain loop running in a worker thread). They hop to the server's
event loop via ``anyio.from_thread.run`` — the single sync↔async bridge,
shared by model calls and user prompts alike.

SDK-contact is confined to this file (+ ``server.py``). ``helix.io`` emits
spec-shaped flat JSON-schema dicts; we pass them straight to the raw
``elicit_form`` (which, unlike FastMCP's model wrapper, accepts enum/choice
schemas), so there is no dict↔model translation anywhere.

Every way the seam can fail — the client refusing the callback ("Method
not found" / "not supported"), the connection dropping, the sync↔async
bridge breaking, or an unusable response — is funnelled into the one typed
:class:`~helix.io.ClientUnavailable`, so a mid-run MCP failure becomes a
legible, snapshotted, resumable stop instead of a raw protocol error that
crashes the run.
"""

from __future__ import annotations

import anyio

from ..io import ClientIO, ClientUnavailable, ElicitRequest, ElicitResult
from ..llm import LLMResponse

_RUN_FROM = (
    "The client driving the helix MCP server must support MCP {what} — run "
    "Helix from an interactive client (e.g. Claude Code), not a stale or "
    "standalone server process. The run stopped at its last snapshot and is "
    "resumable once the client is fixed."
)


class McpClientIO(ClientIO):
    def __init__(self, ctx):
        # ctx: a FastMCP Context for the in-flight tool call.
        self._ctx = ctx

    # --- async halves: run on the MCP event loop --------------------------

    async def _sample(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        from mcp.shared.exceptions import McpError
        from mcp.types import SamplingMessage, TextContent

        try:
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
        except McpError as e:
            raise ClientUnavailable(
                f"Helix could not reach the model: the MCP client refused "
                f"the sampling callback ({e}). "
                + _RUN_FROM.format(what="sampling")
            ) from e
        content = getattr(result, "content", None)
        text = getattr(content, "text", None) if (
            getattr(content, "type", None) == "text") else None
        if not text or not text.strip():
            raise ClientUnavailable(
                "Helix reached the client but got an unusable sampling "
                "response (empty or non-text content). "
                + _RUN_FROM.format(what="sampling")
            )
        return LLMResponse(content=text, usage={}, cost=0.0)

    async def _elicit(self, req: ElicitRequest) -> ElicitResult:
        from mcp.shared.exceptions import McpError

        session = self._ctx.request_context.session
        try:
            result = await session.elicit_form(
                message=req.message,
                requestedSchema=req.schema,
                related_request_id=self._ctx.request_id,
            )
        except McpError as e:
            raise ClientUnavailable(
                f"Helix could not ask you to confirm: the MCP client refused "
                f"the elicitation callback ({e}). "
                + _RUN_FROM.format(what="elicitation")
            ) from e
        if result.action == "accept":
            return ElicitResult(action="accept", data=dict(result.content or {}))
        return ElicitResult(action=result.action, data={})

    # --- sync seam: called from the pipeline worker thread ----------------

    def _bridge(self, fn, *args):
        """Hop to the MCP event loop. A broken bridge (host task gone,
        runner closed, called off the anyio worker thread) surfaces as a
        bare ``RuntimeError``; translate it so a dropped connection mid-run
        is a legible resumable stop, not an opaque crash. ``ClientUnavailable``
        from the async half passes straight through; cancellation is left
        alone for clean shutdown."""
        try:
            return anyio.from_thread.run(fn, *args)
        except ClientUnavailable:
            raise
        except RuntimeError as e:
            raise ClientUnavailable(
                "Helix lost the connection to the MCP client mid-run "
                f"({e}). The run stopped at its last snapshot and is "
                "resumable once the client is reconnected."
            ) from e

    def sample(self, *, system: str, user: str, max_tokens: int) -> LLMResponse:
        return self._bridge(self._sample, system, user, max_tokens)

    def elicit(self, req: ElicitRequest) -> ElicitResult:
        return self._bridge(self._elicit, req)
