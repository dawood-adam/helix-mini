"""Workstream C — interactive agents via ``hx_ask``.

Covers: ``hx_ask`` accepts a free-text question or a flat JSON schema;
the answer is appended to the active project's pending step's
``clarifications`` list; the next stage prompt surfaces recent
clarifications inline; declined elicits surface a legible message.
"""

from __future__ import annotations

import json

import pytest


pytest.importorskip("mcp")


def _drive_call(tool_name: str, args: dict, elicit_cb):
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    from helix.mcp.server import mcp as server

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool(tool_name, args)
            txt = "".join(c.text for c in res.content if c.type == "text")
            return res.isError, txt

    return anyio.run(drive)


def test_hx_ask_records_answer_to_pending(project):
    """An accepted elicitation appends the Q&A to runs.pending."""
    import mcp.types as T
    from helix import runs

    # Seed a pending step (the project must have one for hx_ask to log
    # against it; matches the agent-driven flow's reality).
    runs.set_pending("src-papers", {
        "run_id": "run_test", "stage": "scout",
        "resume_from": "1", "branch": "main",
        "system": "S", "user": "U", "token": "tok", "autonomy": "",
    })

    async def cb(context, params):
        return T.ElicitResult(action="accept",
                              content={"answer": "adults 18–65"})

    is_error, txt = _drive_call("hx_ask", {
        "prompt": "What population?", "project": "src-papers",
    }, cb)
    assert is_error is False, txt
    assert "answered" in txt and "adults" in txt
    pend = runs.get_pending("src-papers")
    assert len(pend["clarifications"]) == 1
    qa = pend["clarifications"][0]
    assert qa["q"] == "What population?" and "adults" in qa["a"]
    assert qa["at"]  # timestamped


def test_hx_ask_declined_returns_clear_message(project):
    import mcp.types as T

    async def cb(context, params):
        return T.ElicitResult(action="decline")

    is_error, txt = _drive_call("hx_ask", {
        "prompt": "What outcome?", "project": "src-papers",
    }, cb)
    assert is_error is False, txt
    assert "decline" in txt and "no answer recorded" in txt


def test_hx_ask_accepts_custom_schema(project):
    """A caller-supplied flat schema (e.g. multi-choice) round-trips."""
    import mcp.types as T

    async def cb(context, params):
        return T.ElicitResult(action="accept", content={"choice": "yes"})

    schema = {
        "type": "object",
        "properties": {"choice": {"type": "string", "enum": ["yes", "no"]}},
        "required": ["choice"],
    }
    is_error, txt = _drive_call("hx_ask", {
        "prompt": "Are we go?", "schema_json": json.dumps(schema),
        "project": "src-papers", "field_name": "choice",
    }, cb)
    assert is_error is False
    assert "yes" in txt


def test_hx_ask_rejects_bad_schema(project):
    import mcp.types as T

    async def cb(context, params):
        return T.ElicitResult(action="accept", content={})

    is_error, txt = _drive_call("hx_ask", {
        "prompt": "x", "schema_json": "{not json",
        "project": "src-papers",
    }, cb)
    # We surface it as a normal tool result, not a tool error, so the agent
    # can recover cleanly.
    assert is_error is False
    assert "Bad schema_json" in txt


def test_clarifications_appear_in_next_step_payload(project):
    """After hx_ask, the next stage's NEEDS MODEL prompt includes the
    Q&A so the agent has the context inline."""
    from helix.mcp.server import _step_payload

    from helix import runs

    runs.set_pending("src-papers", {
        "run_id": "r1", "stage": "scout", "resume_from": "1",
        "branch": "main", "system": "S", "user": "U",
        "token": "tok", "autonomy": "",
        "clarifications": [
            {"q": "population?", "a": "adults", "at": "now"},
            {"q": "outcome?", "a": "accuracy", "at": "now"},
        ],
    })

    # _step_payload takes an "outcome-like" object — a small stand-in suffices.
    class O:
        stage = "scout"
        system = "S"
        user = "U"

    out = _step_payload(str(project), "src-papers", O(), "tok")
    assert "RECENT CLARIFICATIONS" in out
    assert "population?" in out and "adults" in out
    assert "outcome?" in out and "accuracy" in out
