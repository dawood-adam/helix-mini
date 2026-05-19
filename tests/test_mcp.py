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
    gate_asker,
)
from helix.llm import call_llm_json


class _IO:
    """Scripted ClientIO: a queue of elicit results (the only callback —
    Helix is agent-driven, there is no sampling)."""

    def __init__(self, answers=None):
        self._answers = list(answers or [])

    def elicit(self, req):
        return self._answers.pop(0)


# --- agent-driven drive helper (the model is the test, via the tool loop) --

_AGENT_ANSWERS = {
    "scout": {
        "source_summaries": [{"file": "paper.md", "summary": "cfd"}],
        "approaches": [
            {"id": "approach-1", "title": "A1", "description": "d",
             "feasibility": "high"},
            {"id": "approach-2", "title": "A2", "description": "d",
             "feasibility": "low"}],
        "atlas_writes": [{"path": "sources/paper.md", "title": "Paper",
                          "content": "c", "summary": "s"}]},
    "critic_methods": {
        "critiques": [{"approach_id": "approach-1", "strengths": "x",
                       "weaknesses": "y", "severity": "info",
                       "recommendation": "go"}],
        "recommended_id": "approach-1", "atlas_writes": []},
    "planner": {
        "plan": {"title": "Plan", "objective": "o",
                 "steps": [{"step": 1, "action": "a", "expected_output": "e"}],
                 "success_criteria": ["c"],
                 "validation_bands": {"acc": {"min": 0.0, "max": 1.0}}},
        "atlas_writes": [{"path": "projects/src-papers/plan.md",
                          "title": "Plan", "content": "c", "summary": "s"}]},
    "builder": {
        "artifacts": [{"name": "src/sim.py", "type": "code",
                       "content": "print('ok')\n", "description": "sim"}],
        "results": [{"metric": "acc", "value": 0.9, "notes": "ok"}],
        "atlas_writes": []},
    "critic_results": {
        "assessment": "good", "strengths": ["s"], "weaknesses": [],
        "recommendations": ["r"], "verdict": "ship",
        "atlas_writes": [{"path": "projects/src-papers/overview.md",
                          "title": "O", "content": "c", "summary": "s"}]},
}


def _drive_steps(folder, *, max_steps=20):
    """Drive a fresh run agent-driven with NO sampling: hx_step, then loop
    hx_submit feeding _AGENT_ANSWERS, gates auto-accepted via elicitation.
    Returns (final_text, seen_stages)."""
    import json
    import re

    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.mcp.server import mcp as server

    async def elicit_cb(context, params):
        return T.ElicitResult(action="accept", content={"action": "proceed"})

    def _txt(res):
        return "".join(c.text for c in res.content if c.type == "text")

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            out = _txt(await client.call_tool("hx_step", {"folder": folder}))
            seen: list[str] = []
            while out.startswith("NEEDS MODEL") and len(seen) < max_steps:
                stage = re.search(r"stage '([^']+)'", out).group(1)
                token = re.search(r"pending_token='([^']+)'", out).group(1)
                seen.append(stage)
                out = _txt(await client.call_tool("hx_submit", {
                    "folder": folder, "stage": stage,
                    "result_json": json.dumps(_AGENT_ANSWERS[stage]),
                    "pending_token": token}))
            return out, seen

    return anyio.run(drive)


# --- schema builders --------------------------------------------------------


def test_builders_emit_flat_compliant_schemas():
    c = ask_choice("pick", ["a", "b"], "c").schema
    assert c["type"] == "object" and c["required"] == ["c"]
    assert c["properties"]["c"]["enum"] == ["a", "b"]
    assert ask_confirm("ok?").schema["properties"]["proceed"]["type"] == "boolean"
    m = ask_multi("many", ["x", "y"]).schema["properties"]["choices"]
    assert m["type"] == "array" and m["items"]["enum"] == ["x", "y"]
    assert ask_text("t", pattern="[a-z]+").schema["properties"]["value"]["pattern"] == "[a-z]+"


# --- the model seam: no responder bound -> clear, agent-directed error -----


def test_call_llm_json_without_responder_raises():
    with pytest.raises(RuntimeError, match="agent-driven|hx_step"):
        call_llm_json(model="x", system="s", user="u")


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


def _wizard_drive(project, elicit_cb):
    """hx_start with elicitation only (no sampling — Helix is agent-driven).
    Returns (isError, text)."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.mcp.server import mcp as server

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool("hx_start", {"folder": str(project)})
            return res.isError, "".join(
                c.text for c in res.content if c.type == "text")

    return anyio.run(drive)


def test_hx_start_wizard_initializes_and_returns_first_step(project):
    """The wizard elicits name/description/mode, then hands off to the
    agent-driven loop: it returns the FIRST stage's prompt (no autonomous
    server run, no sampling)."""
    pytest.importorskip("mcp")
    import mcp.types as T

    answers = {"name": "demo-proj", "description": "BP via rPPG",
               "mode": "fully autonomous"}

    async def elicit_cb(context, params):
        schema = getattr(params, "requestedSchema", None) or {}
        field = next(iter(schema.get("properties", {})), "")
        return T.ElicitResult(action="accept",
                              content={field: answers.get(field, "x")})

    is_error, txt = _wizard_drive(project, elicit_cb)
    assert is_error is False, txt
    assert txt.startswith("Started 'demo-proj'")
    assert "NEEDS MODEL" in txt and "stage 'scout'" in txt

    from helix import runs
    assert runs.get_record(project="demo-proj").status == "running"
    assert runs.get_pending("demo-proj")["stage"] == "scout"


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


def test_gated_tools_fail_fast_without_elicitation(project):
    """A client with no elicitation callback must get an actionable error
    *before* any run is registered — not a raw "Method not found" at the
    first gate. Non-gated tools are unaffected."""
    pytest.importorskip("mcp")
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import runs
    from helix.mcp.server import mcp as server

    def _txt(res):
        return "".join(c.text for c in res.content if c.type == "text")

    async def drive():
        # No elicitation_callback -> client doesn't advertise it.
        async with conn(server) as client:
            await client.initialize()
            step = await client.call_tool("hx_step", {"folder": str(project)})
            run = await client.call_tool(
                "run_pipeline", {"folder": str(project), "question": "BP?"})
            status = await client.call_tool("atlas_status", {})
            return _txt(step), _txt(run), _txt(status)

    step, run, status = anyio.run(drive)

    for msg in (step, run):
        assert msg.startswith("Error: this MCP client cannot run")
        assert "does not support MCP elicitation." in msg
        assert "No run was started" in msg
    # Pre-flight ran before any run was registered.
    assert runs.get_record(project=project.stem) is None
    # Non-gated tools still work — only the elicitation-needing ones gate.
    assert not status.startswith("Error:") and "Atlas" in status


def test_midrun_elicitation_refusal_is_resumable_not_a_crash(project):
    """The client serviced hx_step/hx_submit, but then refuses the GATE
    elicitation mid-run ("Method not found"). It must become a legible,
    snapshotted, resumable stop — not an uncaught crash that loses the run.
    The completed stage's snapshot already exists, so it is resumable."""
    pytest.importorskip("mcp")
    import json
    import re

    import anyio
    import mcp.types as T
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix import runs
    from helix.core.snapshots import list_snapshots
    from helix.mcp.server import mcp as server

    async def elicit_cb(context, params):  # gate refused
        return T.ErrorData(code=T.METHOD_NOT_FOUND, message="Method not found")

    def _txt(res):
        return "".join(c.text for c in res.content if c.type == "text")

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            step = _txt(await client.call_tool("hx_step", {"folder": str(project)}))
            stage = re.search(r"stage '([^']+)'", step).group(1)
            token = re.search(r"pending_token='([^']+)'", step).group(1)
            sub = _txt(await client.call_tool("hx_submit", {
                "folder": str(project), "stage": stage,
                "result_json": json.dumps(_AGENT_ANSWERS[stage]),
                "pending_token": token}))
            status = _txt(await client.call_tool(
                "hx_run_status", {"project": project.name}))
            return stage, sub, status

    stage, sub, status = anyio.run(drive)
    assert stage == "scout"
    # The scout step rendered fine; the gate after it could not be answered.
    assert "could not ask you to confirm" in sub and "resumable" in sub
    name = project.stem
    rec = runs.get_record(project=name)
    assert rec is not None and rec.status == "error"
    assert "could not ask you to confirm" in (rec.note or "")
    assert "error" in status
    # scout was snapshotted before the gate — the run is not lost.
    assert len(list_snapshots(name)) >= 2  # init + scout


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
    from helix import config, runs
    from helix.core.snapshots import list_snapshots

    server_home = tmp_path / "unrelated-server-cwd"
    server_home.mkdir()
    monkeypatch.setenv("HELIX_HOME", str(server_home))  # server rooted here
    proj = tmp_path / "bpalgo"                           # ...run targets here
    proj.mkdir()
    (proj / "paper.md").write_text("rPPG BP source")
    (proj / "helix.toml").write_text(
        '[atlas]\npath = "atlas"\n\n[limits]\ntoken_cap = 0\ncall_cap = 0\n')

    final, seen = _drive_steps(str(proj))
    assert "done (stages=6" in final, final

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
        assert len(list_snapshots("bpalgo")) == 7  # init + 6 stages


def test_pipeline_runs_agent_driven_without_sampling(project):
    """The whole pipeline runs through hx_step/hx_submit with NO sampling
    callback — Claude Code's exact constraint. The test plays the agent,
    feeding each stage's JSON. Proves suspend→submit→snapshot→next over the
    real core, gates via elicitation, the deterministic validator handled
    in-loop, ending in a normal done summary."""
    pytest.importorskip("mcp")
    from helix import runs
    from helix.core.snapshots import list_snapshots

    final, seen = _drive_steps(str(project))
    assert "done (stages=6" in final, final
    # Five LLM stages round-tripped; deterministic validator ran in-loop.
    assert seen == ["scout", "critic_methods", "planner", "builder",
                    "critic_results"]
    name = project.stem
    assert len(list_snapshots(name)) == 7  # init "start" + 6 stage snapshots
    rec = runs.get_record(project=name)
    assert rec is not None and rec.status == "done"
    assert runs.get_pending(name) is None  # consumed
    assert (project / "atlas" / "projects" / name / "overview.md").is_file()
