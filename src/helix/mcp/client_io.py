"""``McpClientIO`` — the standardized seam, backed by a live MCP session.

Elicitation only. Helix has no server-side model: the client agent is the
intelligence, driving the pipeline through the hx_step / hx_submit tool
loop. The one remaining server→client callback is *elicitation* (gates,
confirmations). ``elicit`` is synchronous (the pipeline core is a plain loop
in a worker thread); it hops to the server's event loop via
``anyio.from_thread.run`` — the single sync↔async bridge.

SDK-contact is confined to this file (+ ``server.py``). ``helix.io`` emits
spec-shaped flat JSON-schema dicts; we pass them straight to the raw
``elicit_form`` (which, unlike FastMCP's model wrapper, accepts enum/choice
schemas), so there is no dict↔model translation anywhere.

Every way the seam can fail — the client refusing the callback ("Method
not found" / "not supported"), the connection dropping, the sync↔async
bridge breaking — is funnelled into the one typed
:class:`~helix.io.ClientUnavailable`, so a mid-run MCP failure becomes a
legible, snapshotted, resumable stop instead of a raw protocol error that
crashes the run.
"""

from __future__ import annotations

import anyio

from ..io import ClientIO, ClientUnavailable, ElicitRequest, ElicitResult


class McpClientIO(ClientIO):
    def __init__(self, ctx):
        # ctx: a FastMCP Context for the in-flight tool call.
        self._ctx = ctx

    # --- async half: runs on the MCP event loop ---------------------------

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
                "Helix could not ask you to confirm: the MCP client refused "
                f"the elicitation callback ({e}). The client driving the "
                "helix MCP server must support MCP elicitation — run Helix "
                "from an interactive client (e.g. Claude Code), not a stale "
                "or standalone server process. The run stopped at its last "
                "snapshot and is resumable once the client is fixed."
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

    def elicit(self, req: ElicitRequest) -> ElicitResult:
        return self._bridge(self._elicit, req)
