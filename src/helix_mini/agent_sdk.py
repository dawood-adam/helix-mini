"""Drive helix-mini through a Claude agent built on the Claude Agent SDK.

helix-mini operations are exposed as in-process SDK MCP tools so a Claude
agent can search the Atlas, inspect status/decision logs, and (gated) launch
pipeline runs. The pure ``*_text`` helpers carry no SDK dependency; only the
agent plumbing imports ``claude-agent-sdk`` lazily, so it stays optional.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from . import __version__
from .atlas import Atlas
from .config import HELIX_HOME

log = logging.getLogger(__name__)

# The single costly / state-mutating tool. Read tools are auto-approved via
# `allowed_tools`; this one falls through to the `can_use_tool` gate.
RUN_TOOL = "run_pipeline"
_READ_TOOLS = ("atlas_search", "atlas_status", "decision_log")

# Exact tool names the gate recognizes. Anything else is denied (fail-closed):
# the SDK exposes powerful built-ins (Bash/Write/Edit/...) and `allowed_tools`
# only pre-approves — unlisted tools reach `can_use_tool`, so a prompt-injected
# agent must not be able to slip an arbitrary tool past this gate.
_READ_TOOL_NAMES = frozenset(_READ_TOOLS) | {f"mcp__helix__{t}" for t in _READ_TOOLS}
_RUN_TOOL_NAMES = frozenset({RUN_TOOL, f"mcp__helix__{RUN_TOOL}"})

# Defense-in-depth: the agent only needs the helix MCP tools, so hard-block
# the SDK's built-in tools at the options level too — even if the callback is
# bypassed, these can never execute.
_DISALLOWED_TOOLS = (
    "Bash", "BashOutput", "KillShell", "Write", "Edit", "NotebookEdit",
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "Task",
)

SYSTEM_PROMPT = (
    "You operate the helix-mini research system. You have tools to search the "
    "persistent Atlas wiki, report Atlas status, read a project's decision log, "
    "and run the multi-stage research pipeline on a folder of sources.\n\n"
    "Guidance:\n"
    "- Prefer the read tools (atlas_search, atlas_status, decision_log) to "
    "answer questions about existing knowledge.\n"
    "- run_pipeline is expensive, slow, and writes to the Atlas wiki. Only call "
    "it when the user explicitly asks to run/analyze a folder, and confirm the "
    "folder path first. It is human-gated and may be denied.\n"
    "- Cite Atlas page paths when you use their content."
)


def _atlas_root(home: Path | None) -> Path:
    return (home or HELIX_HOME) / "atlas"


def atlas_search_text(query: str, home: Path | None = None) -> str:
    """Search the Atlas wiki; return matching pages as readable text."""
    root = _atlas_root(home)
    if not root.exists():
        return "No Atlas found yet — run the pipeline on a folder first."
    pages = Atlas(root).read(query)
    if not pages:
        return f"No Atlas results for: {query}"
    parts = []
    for p in pages:
        body = p.content[:1500] + ("\n..." if len(p.content) > 1500 else "")
        parts.append(f"## {p.title} ({p.path})\n{body}")
    return "\n\n".join(parts)


def atlas_status_text(home: Path | None = None) -> str:
    """Atlas page count and known projects."""
    root = _atlas_root(home)
    if not root.exists():
        return "No Atlas found yet — run the pipeline on a folder first."
    index = Atlas(root).read_all_summaries()
    pages = sum(1 for line in index.splitlines() if line.startswith("- ["))
    projects_dir = root / "projects"
    projects = (
        sorted(d.name for d in projects_dir.iterdir() if d.is_dir())
        if projects_dir.exists()
        else []
    )
    return (
        f"Atlas: {root}\nPages: {pages}\n"
        f"Projects: {', '.join(projects) if projects else '(none)'}"
    )


def decision_log_text(project: str, home: Path | None = None) -> str:
    """Rendered decision log for a project."""
    from .pipeline.decisions import render_decisions_md

    path = _atlas_root(home) / "projects" / project / ".decisions.json"
    if not path.exists():
        return f"No decision log found for project: {project}"
    return render_decisions_md(path)


def run_pipeline_text(
    folder: str,
    question: str = "",
    lightspeed: bool = True,
    home: Path | None = None,
) -> str:
    """Run the full pipeline on a folder. Heavy: spawns the LLM pipeline."""
    fp = Path(folder).expanduser()
    if not fp.is_dir():
        return f"Error: folder not found or not a directory: {folder}"

    from .app import HelixMini
    from .config import ModelConfig

    # Fall back to cli/claude so an agent-launched run needs no provider key.
    model_config = ModelConfig.default(lightspeed=lightspeed) or ModelConfig.cli(
        "claude"
    )

    app = HelixMini(home=home) if home else HelixMini()
    results = app.run(
        [fp.resolve()],
        lightspeed=lightspeed,
        research_question=question,
        model_config=model_config,
    )
    lines = []
    for r in results:
        status = "error" if r.error else "done"
        lines.append(
            f"{r.project_name}: {status} "
            f"(stages={len(r.completed_stages)}, cost=${r.cost_so_far:.4f})"
        )
        if r.error:
            lines.append(f"  error: {r.error}")
    return "\n".join(lines)


def run_permission_decision(
    tool_name: str,
    *,
    interactive: bool,
    approver=None,
) -> tuple[bool, str]:
    """Fail-closed gate for agent tool calls.

    Only the helix read tools are auto-approved. ``run_pipeline`` requires
    explicit approval (expensive, writes to the Atlas). **Every other tool —
    including the SDK's built-in Bash/Write/Edit — is denied**, so a
    prompt-injected agent cannot reach arbitrary tools even if it slips past
    ``allowed_tools``/``disallowed_tools``.
    """
    if tool_name in _READ_TOOL_NAMES:
        return True, ""
    if tool_name not in _RUN_TOOL_NAMES:
        return False, f"Tool '{tool_name}' is not permitted by the helix agent."
    if approver is not None:
        if approver():
            return True, ""
        return False, "User declined the pipeline run."
    if not interactive:
        return (
            False,
            "Pipeline runs require interactive confirmation; "
            "denied (non-interactive session).",
        )
    return False, "No approver configured for the pipeline run."


def claude_code_auth() -> tuple[dict[str, str], list[str]]:
    """Resolve subscription-vs-API auth for the Agent SDK subprocess.

    If a Claude Code OAuth token (``claude setup-token``) is set, the agent
    should run on the user's subscription rate limits. Returns
    ``(env_to_pass, env_keys_to_drop)``: the token is passed through to the
    subprocess and ANTHROPIC_API_KEY is dropped so a stray API key can't
    silently switch the session to pay-per-token billing. No token → no-op.
    """
    from .config import CLAUDE_CODE_OAUTH_ENV, claude_code_oauth_token

    token = claude_code_oauth_token()
    if token is None:
        return {}, []
    return {CLAUDE_CODE_OAUTH_ENV: token}, ["ANTHROPIC_API_KEY"]


def _require_sdk():
    """Import claude-agent-sdk lazily with an actionable error if absent."""
    try:
        import claude_agent_sdk as sdk
    except ImportError as e:
        raise RuntimeError(
            "The Claude Agent SDK is not installed. Install it with:\n"
            "  pip install 'helix-mini[agent]'\n"
            "(or: pip install claude-agent-sdk)"
        ) from e
    return sdk


def build_helix_server(home: Path | None = None):
    """Build the in-process SDK MCP server exposing helix-mini's tools."""
    sdk = _require_sdk()

    @sdk.tool(
        "atlas_search",
        "Search the persistent Atlas research wiki for pages matching a query.",
        {"query": str},
    )
    async def _atlas_search(args):
        return {"content": [{"type": "text", "text": atlas_search_text(args["query"], home)}]}

    @sdk.tool(
        "atlas_status",
        "Show Atlas wiki status: page count and known project names.",
        {},
    )
    async def _atlas_status(args):
        return {"content": [{"type": "text", "text": atlas_status_text(home)}]}

    @sdk.tool(
        "decision_log",
        "Show the decision log (stage-by-stage rationale) for a project name.",
        {"project": str},
    )
    async def _decision_log(args):
        return {
            "content": [
                {"type": "text", "text": decision_log_text(args["project"], home)}
            ]
        }

    @sdk.tool(
        "run_pipeline",
        "Run the full multi-stage research pipeline on a local folder of "
        "source files. Expensive, slow, and writes to the Atlas wiki — only "
        "use when explicitly asked; the run is human-gated.",
        {"folder": str, "question": str, "lightspeed": bool},
    )
    async def _run_pipeline(args):
        import anyio

        text = await anyio.to_thread.run_sync(
            run_pipeline_text,
            args["folder"],
            args.get("question", ""),
            args.get("lightspeed", True),
            home,
        )
        return {"content": [{"type": "text", "text": text}]}

    return sdk.create_sdk_mcp_server(
        name="helix",
        version=__version__,
        tools=[_atlas_search, _atlas_status, _decision_log, _run_pipeline],
    )


def _confirm_run(tool_input: dict) -> bool:
    """Blocking terminal confirmation for a pipeline run."""
    folder = tool_input.get("folder", "?")
    sys.stderr.write(
        f"\n[helix] The agent wants to RUN the pipeline on: {folder}\n"
        f"        This is expensive and writes to the Atlas wiki.\n"
        f"        Approve? [y/N] "
    )
    sys.stderr.flush()
    try:
        return input().strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _render(message, sdk) -> None:
    """Print agent output to the user."""
    if isinstance(message, sdk.AssistantMessage):
        for block in message.content:
            if isinstance(block, sdk.TextBlock):
                click.echo(block.text)
            elif isinstance(block, sdk.ToolUseBlock):
                click.echo(f"  [tool] {block.name} {block.input}", err=True)
    elif isinstance(message, sdk.ResultMessage):
        cost = message.total_cost_usd
        if cost is not None:
            click.echo(
                f"\n[helix] done — {message.num_turns} turn(s), ${cost:.4f}",
                err=True,
            )


async def _run_turn(client, sdk, prompt: str) -> None:
    await client.query(prompt)
    async for message in client.receive_response():
        _render(message, sdk)


async def _run_agent_async(prompt: str | None, home: Path | None, max_turns: int) -> None:
    sdk = _require_sdk()
    server = build_helix_server(home)

    # SDK subprocess inherits os.environ: drop the API key here and forward the
    # token via options.env so subscription auth wins (see claude_code_auth).
    sdk_env, drop_keys = claude_code_auth()
    for _k in drop_keys:
        os.environ.pop(_k, None)

    async def can_use_tool(tool_name, tool_input, context):
        import anyio

        allowed, reason = await anyio.to_thread.run_sync(
            lambda: run_permission_decision(
                tool_name,
                interactive=sys.stdin.isatty(),
                approver=(lambda: _confirm_run(tool_input))
                if sys.stdin.isatty()
                else None,
            )
        )
        if allowed:
            return sdk.PermissionResultAllow()
        return sdk.PermissionResultDeny(message=reason)

    options = sdk.ClaudeAgentOptions(
        mcp_servers={"helix": server},
        # Auto-approve read-only tools; run_pipeline is intentionally absent so
        # it falls through to can_use_tool (which gates it and fail-closes
        # every other tool). disallowed_tools hard-blocks the built-ins too.
        allowed_tools=[f"mcp__helix__{t}" for t in _READ_TOOLS],
        disallowed_tools=list(_DISALLOWED_TOOLS),
        can_use_tool=can_use_tool,
        system_prompt=SYSTEM_PROMPT,
        max_turns=max_turns,
        permission_mode="default",
        env=sdk_env,
    )

    async with sdk.ClaudeSDKClient(options=options) as client:
        if prompt:
            await _run_turn(client, sdk, prompt)
            return
        click.echo("helix-mini agent — ask about the Atlas, or request a run. "
                   "Empty line or Ctrl-D to exit.", err=True)
        while True:
            try:
                user = input("\nyou> ").strip()
            except EOFError:
                break
            if not user or user.lower() in ("exit", "quit"):
                break
            await _run_turn(client, sdk, user)


def run_agent(prompt: str | None = None, home: Path | None = None, max_turns: int = 30) -> None:
    """Sync entry point: drive helix-mini via a Claude agent.

    Raises RuntimeError (with an install hint) if the Agent SDK is missing.
    """
    _require_sdk()  # fail fast with a clear message before the event loop
    import anyio

    anyio.run(_run_agent_async, prompt, home, max_turns)
