"""LangGraph pipeline definition."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from langgraph.graph import END, StateGraph

from ..config import LLM_STAGES
from .agents import Agents
from .decisions import append_decision, save_decisions_md
from .router import gate_decision, iterate_decision, sanity_route
from .snapshots import mint_snapshot
from .state import GraphState, to_state

log = logging.getLogger(__name__)


class CostCapExceeded(Exception):
    """Raised when cumulative LLM cost exceeds the configured cap."""


def _check_caps(state):
    """Raise if the cost cap, or the call-count fallback cap, is exceeded."""
    if state.cost_so_far >= state.cost_cap:
        raise CostCapExceeded(
            f"Cost cap reached: ${state.cost_so_far:.4f} >= ${state.cost_cap:.4f}"
        )
    if state.call_cap:
        used = sum(1 for st in state.completed_stages if st in LLM_STAGES)
        if used >= state.call_cap:
            raise CostCapExceeded(
                f"LLM call cap reached: {used} >= {state.call_cap} "
                f"(CLI engine does not report cost — using call-count guardrail)"
            )


def _project_dir(home: Path, project_name: str) -> Path:
    d = home / "atlas" / "projects" / project_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _decisions_path(home: Path, project_name: str) -> Path:
    return _project_dir(home, project_name) / ".decisions.json"


def build_graph(agents: Agents, home: Path, ask_fn=None, progress_fn=None) -> StateGraph:
    """Build the 12-node Forge pipeline as a LangGraph StateGraph."""

    def _progress(stage: str, project: str, cost: float) -> None:
        if progress_fn:
            progress_fn(stage, project, cost)

    def scout_node(state: GraphState) -> GraphState:
        s = to_state(state)
        _check_caps(s)
        _progress("scout", s.project_name, s.cost_so_far)
        result = agents.scout(s)
        if result.get("error"):
            return {"error": result["error"], "current_stage": "error"}

        append_decision(
            _decisions_path(home, s.project_name),
            "scout",
            f"Identified {len(result.get('candidate_approaches', []))} approaches",
            "Ingested sources and analyzed for research directions",
        )
        mint_snapshot(
            to_state({**state, **result}),
            _project_dir(home, s.project_name),
        )
        return {
            "source_content": result["source_content"],
            "candidate_approaches": result["candidate_approaches"],
            "cost_so_far": s.cost_so_far + result.get("cost", 0),
            "current_stage": "gate_scope",
            "completed_stages": s.completed_stages + ["scout"],
        }

    def gate_scope_node(state: GraphState) -> GraphState:
        s = to_state(state)
        decision = gate_decision(s, "gate_scope", ask_fn)
        append_decision(
            _decisions_path(home, s.project_name), "gate_scope", decision,
            f"{len(s.candidate_approaches)} approaches proposed",
        )
        return {"next_action": decision, "current_stage": "critic_methods"}

    def critic_methods_node(state: GraphState) -> GraphState:
        s = to_state(state)
        _check_caps(s)
        _progress("critic-methods", s.project_name, s.cost_so_far)
        result = agents.critic_methods(s)

        append_decision(
            _decisions_path(home, s.project_name),
            "critic_methods",
            f"Recommended approach: {result.get('chosen_approach_id')}",
            f"Evaluated {len(s.candidate_approaches)} candidates",
        )
        mint_snapshot(
            to_state({**state, **result}),
            _project_dir(home, s.project_name),
        )
        return {
            "critiques": result["critiques"],
            "chosen_approach_id": result["chosen_approach_id"],
            "chosen_approach": result["chosen_approach"],
            "cost_so_far": s.cost_so_far + result.get("cost", 0),
            "current_stage": "gate_methods",
            "completed_stages": s.completed_stages + ["critic_methods"],
        }

    def gate_methods_node(state: GraphState) -> GraphState:
        s = to_state(state)
        decision = gate_decision(s, "gate_methods", ask_fn)
        append_decision(
            _decisions_path(home, s.project_name), "gate_methods", decision,
            f"Chose approach: {s.chosen_approach_id}",
        )
        return {"next_action": decision, "current_stage": "planner", "critiques": []}

    def planner_node(state: GraphState) -> GraphState:
        s = to_state(state)
        _check_caps(s)
        _progress("planner", s.project_name, s.cost_so_far)
        result = agents.planner(s)

        append_decision(
            _decisions_path(home, s.project_name),
            "planner",
            f"Plan: {result.get('project_plan', {}).get('title', 'untitled')}",
            "Designed validation plan with success criteria",
        )
        mint_snapshot(
            to_state({**state, **result}),
            _project_dir(home, s.project_name),
        )
        return {
            "project_plan": result["project_plan"],
            "cost_so_far": s.cost_so_far + result.get("cost", 0),
            "current_stage": "gate_plan",
            "completed_stages": s.completed_stages + ["planner"],
        }

    def gate_plan_node(state: GraphState) -> GraphState:
        s = to_state(state)
        decision = gate_decision(s, "gate_plan", ask_fn)
        append_decision(
            _decisions_path(home, s.project_name), "gate_plan", decision,
            f"Plan has {len(s.project_plan.get('steps', []))} steps",
        )
        return {"next_action": decision, "current_stage": "builder"}

    def builder_node(state: GraphState) -> GraphState:
        s = to_state(state)
        _check_caps(s)
        _progress("builder", s.project_name, s.cost_so_far)
        result = agents.builder(s)

        _files = result.get("artifact_files", [])
        append_decision(
            _decisions_path(home, s.project_name),
            "builder",
            f"Produced {len(result.get('code_artifacts', []))} artifacts "
            f"({len(_files)} file(s) written)",
            f"Built code (iteration {s.build_iterations})"
            + (f"; files: {', '.join(_files[:10])}" if _files else ""),
        )
        mint_snapshot(
            to_state({**state, **result}),
            _project_dir(home, s.project_name),
        )
        return {
            "code_artifacts": result["code_artifacts"],
            "experiment_results": result["experiment_results"],
            "cost_so_far": s.cost_so_far + result.get("cost", 0),
            "current_stage": "gate_build",
            "completed_stages": s.completed_stages + ["builder"],
        }

    def gate_build_node(state: GraphState) -> GraphState:
        s = to_state(state)
        decision = gate_decision(s, "gate_build", ask_fn)
        append_decision(
            _decisions_path(home, s.project_name), "gate_build", decision,
            f"{len(s.code_artifacts)} artifacts, {len(s.experiment_results)} results",
        )
        return {"next_action": decision, "current_stage": "validator"}

    def validator_node(state: GraphState) -> GraphState:
        s = to_state(state)
        log.info("[%s] Validator — checking results", s.project_name)
        result = agents.validator(s)

        flags = result.get("sanity_check_flags")
        append_decision(
            _decisions_path(home, s.project_name),
            "validator",
            "pass" if not flags else f"flags: {flags}",
            "Checked results against validation bands",
        )
        mint_snapshot(
            to_state({**state, **result}),
            _project_dir(home, s.project_name),
        )
        return {
            "sanity_check_flags": result["sanity_check_flags"],
            "current_stage": "sanity_route",
            "completed_stages": s.completed_stages + ["validator"],
        }

    def sanity_route_node(state: GraphState) -> GraphState:
        s = to_state(state)
        route = sanity_route(s)
        if route == "fail":
            return {"current_stage": "builder", "next_action": "revise"}
        return {"current_stage": "critic_results"}

    def critic_results_node(state: GraphState) -> GraphState:
        s = to_state(state)
        _check_caps(s)
        _progress("critic-results", s.project_name, s.cost_so_far)
        result = agents.critic_results(s)

        append_decision(
            _decisions_path(home, s.project_name),
            "critic_results",
            f"Verdict: {result.get('verdict', 'unknown')}",
            "Final assessment of results and approach",
        )
        save_decisions_md(
            _project_dir(home, s.project_name),
            _decisions_path(home, s.project_name),
        )
        mint_snapshot(
            to_state({**state, **result}),
            _project_dir(home, s.project_name),
        )
        return {
            "critiques": result.get("critiques", []),
            "verdict": result.get("verdict", "ship"),
            "cost_so_far": s.cost_so_far + result.get("cost", 0),
            "current_stage": "gate_results",
            "completed_stages": s.completed_stages + ["critic_results"],
        }

    def gate_results_node(state: GraphState) -> GraphState:
        s = to_state(state)
        verdict = (s.verdict or "ship").lower()
        decision = iterate_decision(s)  # "iterate" | "stop" (cap-aware)
        capped = s.build_iterations >= s.max_iterations
        autonomy = s.autonomy.get("gate_results", "always_ask")

        # HITL: when this gate isn't auto and we're on a TTY, the human chooses
        # ship/iterate/abandon, overriding the model verdict. Non-interactive
        # (tests, pipes) or --lightspeed (auto) falls back to the pure rule.
        if autonomy != "auto" and sys.stdin.isatty():
            import click

            default = "i" if decision == "iterate" else (
                "a" if verdict == "abandon" else "s")
            note = " (max iterations reached)" if (
                verdict == "iterate" and capped) else ""
            choice = click.prompt(
                f"\n[helix] critic verdict: {verdict}{note}. "
                f"[s]hip / [i]terate / [a]bandon",
                type=click.Choice(["s", "i", "a"]),
                default=default, show_default=True,
            )
            if choice == "i" and not capped:
                decision, verdict = "iterate", "iterate"
            elif choice == "a":
                decision, verdict = "stop", "abandon"
            else:
                decision, verdict = "stop", "ship"

        if decision == "iterate":
            append_decision(
                _decisions_path(home, s.project_name), "gate_results",
                f"iterate ({s.build_iterations + 1}/{s.max_iterations})",
                "Looping back to builder to refine the artifacts",
            )
            save_decisions_md(
                _project_dir(home, s.project_name),
                _decisions_path(home, s.project_name),
            )
            return {
                "next_action": "iterate",
                "build_iterations": s.build_iterations + 1,
                "current_stage": "builder",
            }

        final = "abandon" if verdict == "abandon" else "ship"
        append_decision(
            _decisions_path(home, s.project_name), "gate_results", final,
            "Final gate — pipeline complete"
            + (" (iterations exhausted)" if (verdict == "iterate" and capped)
               else ""),
        )
        save_decisions_md(
            _project_dir(home, s.project_name),
            _decisions_path(home, s.project_name),
        )
        return {"next_action": final, "current_stage": "done"}

    # Build the graph
    graph = StateGraph(GraphState)

    graph.add_node("scout", scout_node)
    graph.add_node("gate_scope", gate_scope_node)
    graph.add_node("critic_methods", critic_methods_node)
    graph.add_node("gate_methods", gate_methods_node)
    graph.add_node("planner", planner_node)
    graph.add_node("gate_plan", gate_plan_node)
    graph.add_node("builder", builder_node)
    graph.add_node("gate_build", gate_build_node)
    graph.add_node("validator", validator_node)
    graph.add_node("sanity_route", sanity_route_node)
    graph.add_node("critic_results", critic_results_node)
    graph.add_node("gate_results", gate_results_node)

    # Edges: linear pipeline with sanity loop
    graph.set_entry_point("scout")
    graph.add_edge("scout", "gate_scope")
    graph.add_edge("gate_scope", "critic_methods")
    graph.add_edge("critic_methods", "gate_methods")
    graph.add_edge("gate_methods", "planner")
    graph.add_edge("planner", "gate_plan")
    graph.add_edge("gate_plan", "builder")
    graph.add_edge("builder", "gate_build")
    graph.add_edge("gate_build", "validator")

    # Sanity route: pass -> critic_results, fail -> builder
    graph.add_conditional_edges(
        "sanity_route",
        lambda s: "builder" if s.get("next_action") == "revise" else "critic_results",
        {"builder": "builder", "critic_results": "critic_results"},
    )
    graph.add_edge("validator", "sanity_route")
    graph.add_edge("critic_results", "gate_results")

    # gate_results: iterate -> back to builder (bounded refine loop), else END
    graph.add_conditional_edges(
        "gate_results",
        lambda st: "builder" if st.get("next_action") == "iterate" else "END",
        {"builder": "builder", "END": END},
    )

    return graph
