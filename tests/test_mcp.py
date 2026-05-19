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


def test_hx_start_creates_missing_source_folder(project, tmp_path):
    pytest.importorskip("mcp")
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import runs
    from helix.mcp.server import mcp as server

    fresh = tmp_path / "fresh-src"  # does not exist; no files
    answers = {"name": "demo-proj", "description": "q",
               "mode": "fully autonomous"}

    async def elicit_cb(context, params):
        schema = getattr(params, "requestedSchema", None) or {}
        field = next(iter(schema.get("properties", {})), "")
        return T.ElicitResult(action="accept",
                              content={field: answers.get(field, "x")})

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool("hx_start", {"folder": str(fresh)})
            return "".join(c.text for c in res.content if c.type == "text")

    txt = anyio.run(drive)
    # helped instead of dead-ending: folder created, actionable guidance,
    # and no doomed run was started.
    assert fresh.is_dir()
    assert "no source material yet" in txt
    assert "atlas/inbox" in txt and "No run was started" in txt
    assert runs.get_record(project="demo-proj") is None


def test_gated_tools_fail_fast_without_client_callbacks(project):
    """A client that advertises neither sampling nor elicitation must get an
    actionable error *before* any run is registered — not a raw "Method not
    found" / "Sampling not supported" mid-run. Non-gated tools are
    unaffected."""
    pytest.importorskip("mcp")
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import runs
    from helix.mcp.server import mcp as server

    def _txt(res):
        return "".join(c.text for c in res.content if c.type == "text")

    async def drive():
        # No sampling_callback / elicitation_callback -> client advertises
        # neither capability (the exact transcript failure mode).
        async with conn(server) as client:
            await client.initialize()
            start = await client.call_tool("hx_start", {"folder": str(project)})
            run = await client.call_tool(
                "run_pipeline", {"folder": str(project), "question": "BP?"})
            status = await client.call_tool("atlas_status", {})
            return _txt(start), _txt(run), _txt(status)

    start, run, status = anyio.run(drive)

    for msg in (start, run):
        assert msg.startswith("Error: this MCP client cannot run")
        assert "No run was started" in msg
    # hx_start elicits first (only elicitation pre-flighted); run_pipeline
    # samples immediately (both pre-flighted).
    assert "does not support MCP elicitation." in start
    assert "does not support MCP sampling + elicitation." in run
    # Pre-flight ran before any run was registered.
    assert runs.get_record(project=project.stem) is None
    # Non-gated tools still work — only the callback-needing ones gate.
    assert not status.startswith("Error:") and "Atlas" in status


def test_midrun_sampling_failure_is_resumable_not_a_crash(project):
    """Pre-flight passes (both caps advertised) but the client then refuses
    the sampling callback mid-run ("Method not found", the real transcript
    symptom). It must become a legible, snapshotted, resumable stop — not an
    uncaught exception that crashes the tool and loses the whole run."""
    pytest.importorskip("mcp")
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import runs
    from helix.core.snapshots import list_snapshots
    from helix.mcp.server import mcp as server

    async def sampling_cb(context, params):
        return T.ErrorData(code=T.METHOD_NOT_FOUND, message="Method not found")

    async def elicit_cb(context, params):  # advertises elicitation; unreached
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
            return res.isError, _txt(res), _txt(status)

    is_error, txt, status = anyio.run(drive)

    # Clean tool return (a summary string), not an opaque exception crash.
    assert is_error is False, txt
    assert "error" in txt and "could not reach the model" in txt
    assert "resumable" in txt
    # Recorded as a resumable error: status + the legible note + a snapshot.
    rec = runs.get_record(project=project.name)
    assert rec is not None and rec.status == "error"
    assert rec.last_snapshot and "could not reach the model" in (rec.note or "")
    assert "error" in status
    # The run was snapshotted, not lost — resume_pipeline has a target.
    assert len(list_snapshots(project.name)) >= 1


def test_unusable_sampling_response_is_legible(project):
    """An empty / non-text sampling response must surface as a clear seam
    error, not silently become the string "None" and fail JSON parsing with
    a confusing downstream error."""
    pytest.importorskip("mcp")
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.mcp.server import mcp as server

    async def sampling_cb(context, params):
        return T.CreateMessageResult(
            role="assistant", content=T.TextContent(type="text", text=""),
            model="fake", stopReason="endTurn")

    async def elicit_cb(context, params):
        return T.ElicitResult(action="accept", content={"action": "proceed"})

    async def drive():
        async with conn(server, sampling_callback=sampling_cb,
                        elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool(
                "run_pipeline", {"folder": str(project), "question": "BP?"})
            return res.isError, "".join(
                c.text for c in res.content if c.type == "text")

    is_error, txt = anyio.run(drive)
    assert is_error is False, txt
    assert "error" in txt and "unusable sampling response" in txt


def test_bridge_translates_lost_connection():
    """A broken sync↔async bridge (host task gone / called off the worker
    thread) is a bare RuntimeError; it must read as a resumable lost
    connection, not leak as an opaque crash."""
    from helix.io import ClientUnavailable
    from helix.mcp.client_io import McpClientIO

    async def _coro():
        return 1

    io = McpClientIO(ctx=None)
    # Called from the test's own thread: there is no anyio portal, so
    # anyio.from_thread.run raises RuntimeError — the bridge-broken signal.
    with pytest.raises(ClientUnavailable, match="lost the connection"):
        io._bridge(_coro)


# --- config.use_root: the per-run root seam (mirrors helix.io.use) ----------


def test_use_root_overrides_home_and_resets(tmp_path, monkeypatch):
    """A bound run root wins over HELIX_HOME; empty/None is a no-op (keeps
    the surrounding binding / the HELIX_HOME fallback); exit restores."""
    from helix import config

    home, folder = tmp_path / "server-home", tmp_path / "proj"
    monkeypatch.setenv("HELIX_HOME", str(home))
    assert config.project_root() == home.resolve()

    with config.use_root(folder):
        assert config.project_root() == folder.resolve()
        with config.use_root(""):  # no-op: does not reset the outer binding
            assert config.project_root() == folder.resolve()
    assert config.project_root() == home.resolve()  # token reset restored

    with config.use_root(None):  # no-op at top level: HELIX_HOME fallback
        assert config.project_root() == home.resolve()


def test_run_is_self_rooted_under_folder_not_server_cwd(tmp_path, monkeypatch):
    """The structural fix: a run lands entirely under its source folder even
    when HELIX_HOME (the server's launch root) points somewhere unrelated —
    so a misrooted/stale server can no longer silently write a run into the
    wrong project."""
    pytest.importorskip("mcp")
    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import config, runs
    from helix.core.snapshots import list_snapshots
    from helix.mcp.server import mcp as server

    server_home = tmp_path / "unrelated-server-cwd"
    server_home.mkdir()
    monkeypatch.setenv("HELIX_HOME", str(server_home))  # server rooted here
    proj = tmp_path / "bpalgo"                           # ...run targets here
    proj.mkdir()
    (proj / "paper.md").write_text("rPPG BP source")
    (proj / "helix.toml").write_text(
        '[atlas]\npath = "atlas"\n\n[limits]\ntoken_cap = 0\ncall_cap = 0\n')

    async def sampling_cb(context, params):
        return T.CreateMessageResult(
            role="assistant", content=T.TextContent(type="text", text="{}"),
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
                "run_pipeline",
                {"folder": str(proj), "question": "BP?", "autonomy_until": "END"})
            return res.isError, _txt(res)

    is_error, txt = anyio.run(drive)
    assert is_error is False, txt
    assert "done (stages=6" in txt

    # Everything the run produced is under the *folder*, not the server root.
    assert (proj / ".helix" / "snapshots").is_dir()
    assert (proj / "atlas").is_dir()
    assert not (server_home / ".helix").exists()
    assert not (server_home / "atlas").exists()

    # Read-back is consistent only when resolved at the folder root — proof
    # the data really moved there (and why a per-project server is needed).
    assert runs.get_record(project="bpalgo") is None  # HELIX_HOME=server_home
    with config.use_root(proj):
        rec = runs.get_record(project="bpalgo")
        assert rec is not None and rec.status == "done"
        assert len(list_snapshots("bpalgo")) == 6
