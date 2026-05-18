"""The ask/Envelope primitive, the session store, and the hx_start intent."""

from __future__ import annotations

import time

import pytest
from click.testing import CliRunner

from helix.cli import cli
from helix.envelope import AnswerError, Envelope, Question, validate_answer
from helix.intents import step
from helix.sessions import SessionStore


# --- envelope -------------------------------------------------------------

def test_envelope_shape():
    e = Envelope(result={"x": 1}, next="hx_run")
    assert e.to_dict() == {"result": {"x": 1}, "ask": None,
                           "next": "hx_run", "warn": None}


def test_validate_answer_per_type():
    assert validate_answer(Question("k", "", "string",
                                    constraints={"pattern": r"[a-z-]+"}), "ok-name") == "ok-name"
    with pytest.raises(AnswerError):
        validate_answer(Question("k", "", "string",
                                 constraints={"pattern": r"[a-z-]+"}), "Bad Name")
    with pytest.raises(AnswerError):
        validate_answer(Question("k", "", "int", constraints={"min": 1, "max": 3}), 9)
    opts = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]
    assert validate_answer(Question("k", "", "choice", options=opts), "a") == "a"
    with pytest.raises(AnswerError):
        validate_answer(Question("k", "", "choice", options=opts), "z")
    assert validate_answer(Question("k", "", "multi", options=opts), ["a", "b"]) == ["a", "b"]
    assert validate_answer(Question("k", "", "confirm"), "yes") is True
    assert validate_answer(Question("k", "", "confirm"), "n") is False


# --- sessions -------------------------------------------------------------

def test_session_store_ttl():
    st = SessionStore(ttl=1)
    s = st.open("hx_start")
    assert st.get(s.id) is not None
    st._data[s.id].ts = time.time() - 10  # age it past the TTL
    assert st.get(s.id) is None  # evicted on access


# --- hx_start state machine ----------------------------------------------

def _drive(answers_seq):
    """Run hx_start, answering with each dict in order. Return final Envelope."""
    env = step("hx_start")
    for ans in answers_seq:
        assert env.ask is not None
        env = step("hx_start", session=env.ask.session, answers=ans)
    return env


def test_hx_start_auto_to_asks_stage_and_resolves():
    env = step("hx_start")
    assert env.ask.questions[0].key == "project_name"
    env = step("hx_start", session=env.ask.session, answers={"project_name": "smartphone-bp"})
    assert env.ask.questions[0].key == "description"
    env = step("hx_start", session=env.ask.session, answers={"description": "rPPG BP"})
    assert env.ask.questions[0].key == "control"
    env = step("hx_start", session=env.ask.session, answers={"control": "auto_to"})
    assert env.ask.questions[0].key == "stage"   # conditional slot appeared
    env = step("hx_start", session=env.ask.session, answers={"stage": "builder"})
    assert env.ask.questions[0].key == "start" and env.ask.questions[0].type == "confirm"
    env = step("hx_start", session=env.ask.session, answers={"start": False})
    assert env.result["autonomy_until"] == "builder"
    assert env.result["start"] is False and env.next is None and env.warn


def test_hx_start_step_and_auto_modes():
    env = _drive([{"project_name": "p1"}, {"description": "d"},
                  {"control": "step"}, {"start": True}])
    assert env.result["autonomy_until"] == "" and env.result["start"] is True
    assert env.next == "pipeline_status"

    env = _drive([{"project_name": "p2"}, {"description": "d"},
                  {"control": "auto"}, {"start": False}])
    assert env.result["autonomy_until"] == "END"


def test_hx_start_rejects_bad_name_and_reasks():
    env = step("hx_start")
    env = step("hx_start", session=env.ask.session, answers={"project_name": "Bad Name"})
    assert env.ask.questions[0].key == "project_name"   # not accepted
    assert env.warn and env.warn.startswith("project_name:")


# --- CLI renderer (same engine, terminal skin) ----------------------------

def test_cli_start_prepares_without_running(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    # arg seeds project_name; then description, control=1 (step), confirm n.
    r = CliRunner().invoke(cli, ["start", "smartphone-bp"],
                           input="rPPG BP estimation\n1\nn\n")
    assert r.exit_code == 0, r.output
    assert "Prepared 'smartphone-bp'" in r.output
    assert "helix run ." in r.output
    assert (tmp_path / "smartphone-bp" / "question.md").exists()
