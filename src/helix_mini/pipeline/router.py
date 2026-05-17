"""Gate decision + sanity routing — pure rules, no LLM."""

from __future__ import annotations

from .state import ForgeState


def gate_decision(
    state: ForgeState,
    gate_name: str,
    ask_fn=None,
) -> str:
    """Decide whether to proceed, revise, or abort at a gate.

    Returns: "proceed", "revise", or "abort".
    """
    autonomy = state.autonomy.get(gate_name, "always_ask")

    # Check for blocking critiques (critiques may be dicts or strings)
    blocking = [
        c for c in state.critiques
        if isinstance(c, dict) and c.get("severity") == "blocking"
    ]
    if blocking:
        if autonomy == "auto":
            return "revise"
        if ask_fn:
            return ask_fn(gate_name, blocking)
        return "revise"

    if autonomy == "auto":
        return "proceed"

    if ask_fn:
        return ask_fn(gate_name, state.critiques)

    return "proceed"


def sanity_route(state: ForgeState) -> str:
    """After validator, decide next step based on sanity check flags.

    Returns: "pass" (continue to critic_results) or "fail" (loop back to builder).
    """
    flags = state.sanity_check_flags or []

    if not flags:
        return "pass"

    hard = [f for f in flags if f.startswith("HARD:")]
    if hard:
        return "fail"

    return "pass"


def make_autonomy(lightspeed: bool) -> dict[str, str]:
    """Build gate autonomy settings."""
    gates = [
        "gate_scope",
        "gate_methods",
        "gate_plan",
        "gate_build",
        "gate_results",
    ]
    mode = "auto" if lightspeed else "always_ask"
    return {g: mode for g in gates}
