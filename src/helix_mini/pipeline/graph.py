"""LangGraph pipeline definition."""

from __future__ import annotations

import logging
from pathlib import Path

from langgraph.graph import END, StateGraph

from .agents import Agents
from .decisions import append_decision, save_decisions_md
from .router import gate_decision, sanity_route
from .snapshots import mint_snapshot
from .state import GraphState, to_state

log = logging.getLogger(__name__)


class CostCapExceeded(Exception):
    """Raised when cumulative LLM cost exceeds the configured cap."""


def _check_cost_cap(state):
    """Raise if cost cap is exceeded."""
    if state.cost_so_far >= state.cost_cap:
        raise CostCapExceeded(
            f"Cost cap reached: ${state.cost_so_far:.4f} >= ${state.cost_cap:.4f}"
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
        _check_cost_cap(s)
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
        _check_cost_cap(s)
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
        _check_cost_cap(s)
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
        _check_cost_cap(s)
        _progress("builder", s.project_name, s.cost_so_far)
        result = agents.builder(s)

        append_decision(
            _decisions_path(home, s.project_name),
            "builder",
            f"Produced {len(result.get('code_artifacts', []))} artifacts",
            "Built code and ran experiments",
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
        _check_cost_cap(s)
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
            "cost_so_far": s.cost_so_far + result.get("cost", 0),
            "current_stage": "gate_results",
            "completed_stages": s.completed_stages + ["critic_results"],
        }

    def gate_results_node(state: GraphState) -> GraphState:
        s = to_state(state)
        decision = gate_decision(s, "gate_results", ask_fn)
        append_decision(
            _decisions_path(home, s.project_name), "gate_results", decision,
            "Final gate — shipping or iterating",
        )
        save_decisions_md(
            _project_dir(home, s.project_name),
            _decisions_path(home, s.project_name),
        )
        return {"next_action": decision, "current_stage": "done"}

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
    graph.add_edge("gate_results", END)

    return graph
