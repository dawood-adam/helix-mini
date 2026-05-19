"""The standardized client-IO seam (sampling + elicitation).

These exercise the seam with no `mcp` installed — that the design is
testable SDK-free is the point. Server construction is smoke-tested behind
importorskip.
"""

from __future__ import annotations

import pytest

from helix.core.gates import GateReport
from helix.io import (
    Declined, ElicitResult, ask_choice, ask_confirm, ask_multi, ask_text,
    gate_asker, use,
)
from helix.llm import LLMResponse, call_llm


class _IO:
    """Scripted ClientIO: canned model reply + a queue of elicit results."""

    def __init__(self, answers=None, reply="ok"):
        self._answers = list(answers or [])
        self._reply = reply

    def sample(self, *, system, user, max_tokens):
        return LLMResponse(content=self._reply, usage={}, cost=0.0)

    def elicit(self, req):
        return self._answers.pop(0)


# --- schema builders --------------------------------------------------------


def test_builders_emit_flat_compliant_schemas():
    c = ask_choice("pick", ["a", "b"], "c").schema
    assert c["type"] == "object" and c["required"] == ["c"]
    assert c["properties"]["c"]["enum"] == ["a", "b"]
    assert ask_confirm("ok?").schema["properties"]["proceed"]["type"] == "boolean"
    m = ask_multi("many", ["x", "y"]).schema["properties"]["choices"]
    assert m["type"] == "array" and m["items"]["enum"] == ["x", "y"]
    assert ask_text("t", pattern="[a-z]+").schema["properties"]["value"]["pattern"] == "[a-z]+"


# --- call_llm rides the bound seam -----------------------------------------


def test_call_llm_uses_bound_io():
    with use(_IO(reply="hello")):
        assert call_llm(model="x", system="s", user="u").content == "hello"


def test_call_llm_unbound_raises():
    with pytest.raises(RuntimeError, match="No Helix client IO"):
        call_llm(model="x", system="s", user="u")


# --- gate_asker: standardized elicitation -> core HITL decision ------------


def _report():
    return GateReport("scout", "found 2 approaches", "ingested sources")


def test_gate_asker_proceed_and_stop():
    proceed = gate_asker(_IO([ElicitResult("accept", {"action": "proceed"})]))
    assert proceed(_report()).action == "proceed"
    stop = gate_asker(_IO([ElicitResult("accept", {"action": "stop"})]))
    assert stop(_report()).action == "stop"


def test_gate_asker_send_back_collects_stage_and_note():
    io = _IO([
        ElicitResult("accept", {"action": "send back"}),
        ElicitResult("accept", {"stage": "scout"}),
        ElicitResult("accept", {"note": "widen the search"}),
    ])
    gd = gate_asker(io)(_report())
    assert gd.action == "goto" and gd.target == "scout"
    assert gd.feedback == "widen the search"


def test_gate_asker_decline_raises():
    with pytest.raises(Declined):
        gate_asker(_IO([ElicitResult("decline")]))(_report())


# --- the loop turns a declined gate into a resumable pause -----------------


def test_declined_gate_pauses_resumably(project, fake_llm):
    from helix import app

    r = app.run(project, ask=gate_asker(_IO([ElicitResult("cancel")])),
                interactive=True)
    assert r.error is None
    assert r.next_action == "paused-input"


# --- server smoke (needs the mcp SDK) --------------------------------------


def test_server_constructs():
    pytest.importorskip("mcp")
    from helix.mcp import server

    assert server.mcp is not None
    assert callable(server.main)


def test_end_to_end_in_memory(project):
    """The only regression guard for client_io.py's sync↔async bridge:
    drive run_pipeline through a real in-memory MCP client↔server, with the
    client faking sampling ({}) and auto-proceeding every gate."""
    pytest.importorskip("mcp")
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.core.snapshots import list_snapshots
    from helix.mcp.server import mcp as server

    async def sampling_cb(context, params):
        return T.CreateMessageResult(
            role="assistant",
            content=T.TextContent(type="text", text="{}"),
            model="fake", stopReason="endTurn")

    async def elicit_cb(context, params):
        return T.ElicitResult(action="accept", content={"action": "proceed"})

    def _txt(res):
        return "".join(c.text for c in res.content if c.type == "text")

    async def drive():
        async with conn(server, sampling_callback=sampling_cb,
                        elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool(
                "run_pipeline", {"folder": str(project), "question": "BP?"})
            status = await client.call_tool(
                "hx_run_status", {"project": project.name})
            events = await client.call_tool(
                "hx_run_events", {"project": project.name})
            return (res.isError, _txt(res), _txt(status), _txt(events))

    is_error, txt, status, events = anyio.run(drive)
    assert is_error is False, txt
    assert "done (stages=6" in txt and txt.startswith("[run_")
    # The bounded run registry recorded the run + its transitions.
    assert "done" in status and "run_" in status
    assert "scout" in events and "critic_results" in events
    snaps = list_snapshots(project.name)
    assert len(snaps) == 6
    # Every stage's snapshot carries a Decision Card (here generic, since the
    # fake client returns {}); proves the card flows the real MCP path.
    from helix.core.snapshots import load_snapshot

    first = load_snapshot(project.name, snaps[0]["id"])
    assert first["decision_card"]["summary"] == "scout complete"


def _wizard_drive(project, elicit_cb):
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.mcp.server import mcp as server

    async def sampling_cb(context, params):
        return T.CreateMessageResult(
            role="assistant", content=T.TextContent(type="text", text="{}"),
            model="fake", stopReason="endTurn")

    async def drive():
        async with conn(server, sampling_callback=sampling_cb,
                        elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool("hx_start", {"folder": str(project)})
            return res.isError, "".join(
                c.text for c in res.content if c.type == "text")

    return anyio.run(drive)


def test_hx_start_wizard_happy_path(project):
    pytest.importorskip("mcp")
    import mcp.types as T

    answers = {"name": "demo-proj", "description": "BP via rPPG",
               "mode": "fully autonomous", "stage": "scout", "action": "proceed"}

    async def elicit_cb(context, params):
        schema = getattr(params, "requestedSchema", None) or {}
        field = next(iter(schema.get("properties", {})), "")
        return T.ElicitResult(action="accept",
                              content={field: answers.get(field, "x")})

    is_error, txt = _wizard_drive(project, elicit_cb)
    assert is_error is False, txt
    assert txt.startswith("[run_") and "started 'demo-proj'" in txt
    assert "done (stages=6" in txt

    from helix import runs
    assert runs.get_record(project="demo-proj").status == "done"


def test_hx_start_wizard_cancelled(project):
    pytest.importorskip("mcp")
    import mcp.types as T

    async def elicit_cb(context, params):
        return T.ElicitResult(action="decline")

    is_error, txt = _wizard_drive(project, elicit_cb)
    assert is_error is False
    assert txt == "Setup cancelled."


def test_hx_atlas_ingest_over_mcp(project):
    pytest.importorskip("mcp")
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import config
    from helix.mcp.server import mcp as server

    inbox = config.atlas_path() / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "paper.md").write_text("rPPG source material")

    async def drive():
        async with conn(server) as client:
            await client.initialize()
            a = await client.call_tool("hx_atlas_ingest", {})
            b = await client.call_tool("hx_atlas_ingest", {})  # idempotent
            t = lambda r: "".join(c.text for c in r.content if c.type == "text")
            return t(a), t(b)

    first, second = anyio.run(drive)
    assert "Ingested 1 source(s): paper.md" in first
    assert "nothing new" in second
    assert (config.atlas_path() / "raw" / "paper.md").exists()
    assert (config.atlas_path() / "sources" / "paper.md").exists()


def test_hx_atlas_put_and_promote_over_mcp(project):
    pytest.importorskip("mcp")
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import config
    from helix.core.recall import get
    from helix.mcp.server import mcp as server

    proceed = {"v": True}

    async def elicit_cb(context, params):
        return T.ElicitResult(action="accept", content={"proceed": proceed["v"]})

    def _t(r):
        return "".join(c.text for c in r.content if c.type == "text")

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            put = _t(await client.call_tool("hx_atlas_put", {
                "path": "concepts/widget.md", "title": "Widget",
                "content": "a widget", "summary": "w"}))
            ok = _t(await client.call_tool("hx_atlas_promote", {
                "ids": "concepts/widget.md", "tier": "canonical"}))
            proceed["v"] = False
            no = _t(await client.call_tool("hx_atlas_promote", {
                "ids": "atlas:concepts:widget", "tier": "published"}))
            return put, ok, no

    put, ok, no = anyio.run(drive)
    assert "atlas:concepts:widget" in put
    assert "Promoted 1 → canonical" in ok
    assert "cancelled" in no
    # confirmed promotion stuck; cancelled one did not advance the tier
    assert get(config.atlas_path(), "concepts/widget.md")["tier"] == "canonical"


def test_canonical_prompts_over_mcp():
    pytest.importorskip("mcp")
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.mcp.server import mcp as server

    async def drive():
        async with conn(server) as client:
            await client.initialize()
            names = sorted(p.name for p in (await client.list_prompts()).prompts)
            run = await client.get_prompt("helix_run", {"folder": "./papers"})
            return names, run.messages[0].content.text

    names, run_text = anyio.run(drive)
    assert names == ["helix_freeze", "helix_ingest", "helix_lint",
                     "helix_resume", "helix_run"]
    assert "./papers" in run_text and "hx_start" in run_text  # real workflow
