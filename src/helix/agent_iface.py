"""Drive helix via a Claude agent (Claude Agent SDK).

Read tools auto-approve; ``run_pipeline``/``resume_pipeline``/
``snapshot_revert`` are state-mutating and human-gated. The gate is
fail-closed: any other tool — including the SDK's Bash/Write/Edit — is denied
*and* hard-blocked, so a prompt-injected agent cannot escape (Risk J). The
pure ``*_text`` helpers carry no SDK dependency.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from . import __version__, config
from .core.atlas import Atlas

log = logging.getLogger(__name__)

_READ_TOOLS = (
    "atlas_search", "atlas_status", "decision_log",
    "snapshot_list", "snapshot_show", "snapshot_diff", "snapshot_timeline",
)
_GATED_TOOLS = ("run_pipeline", "resume_pipeline", "snapshot_revert")
_READ_NAMES = frozenset(_READ_TOOLS) | {f"mcp__helix__{t}" for t in _READ_TOOLS}
_GATED_NAMES = frozenset(_GATED_TOOLS) | {f"mcp__helix__{t}" for t in _GATED_TOOLS}
_DISALLOWED_TOOLS = (
    "Bash", "BashOutput", "KillShell", "Write", "Edit", "NotebookEdit",
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "Task",
)

SYSTEM_PROMPT = (
    "You operate the helix research pipeline end to end. Read tools "
    "(atlas_search/atlas_status/decision_log, snapshot_list/show/diff/"
    "timeline) are free. run_pipeline/resume_pipeline/snapshot_revert are "
    "expensive, write to the project, and human-gated — only call them when "
    "explicitly asked, and confirm the target first. Cite Atlas paths and "
    "snapshot ids you use."
)


def atlas_search_text(query: str) -> str:
    root = config.atlas_path()
    if not root.exists():
        return "No Atlas yet — run the pipeline on a folder first."
    pages = Atlas(root).read(query)
    if not pages:
        return f"No Atlas results for: {query}"
    return "\n\n".join(
        f"## {p.title} ({p.path})\n{p.content[:1500]}"
        + ("\n..." if len(p.content) > 1500 else "")
        for p in pages
    )


def atlas_status_text() -> str:
    root = config.atlas_path()
    if not root.exists():
        return "No Atlas yet — run the pipeline first."
    pages = sum(
        1 for ln in Atlas(root).read_all_summaries().splitlines()
        if ln.startswith("- [")
    )
    pdir = root / "projects"
    projects = sorted(d.name for d in pdir.iterdir() if d.is_dir()) if pdir.exists() else []
    return f"Atlas: {root}\nPages: {pages}\nProjects: {', '.join(projects) or '(none)'}"


def decision_log_text(project: str) -> str:
    from .core.decisions import render_decisions_md

    p = config.atlas_path() / "projects" / project / ".decisions.json"
    return render_decisions_md(p) if p.exists() else f"No decision log for: {project}"


def snapshot_list_text(project: str) -> str:
    from .core.snapshots import list_snapshots

    snaps = list_snapshots(project)
    if not snaps:
        return f"No snapshots for '{project}'."
    return "\n".join(
        f"snap-{m['id']} {m.get('branch','main')} {m.get('stage','')} "
        f"parent={m.get('parent') or '-'}"
        for m in snaps
    )


def snapshot_show_text(project: str, snap_id: str) -> str:
    from .core.snapshots import load_snapshot, snapshot_summary

    snap = load_snapshot(project, snap_id)
    if not snap:
        return f"No snap-{snap_id} for '{project}'."
    return "\n".join(f"{k}={v}" for k, v in snapshot_summary(snap).items())


def snapshot_diff_text(project: str, a: str, b: str) -> str:
    from .core.snapshots import diff_snapshots, load_snapshot

    sa, sb = load_snapshot(project, a), load_snapshot(project, b)
    if not sa or not sb:
        return f"Need both snap-{a} and snap-{b} for '{project}'."
    ch = diff_snapshots(sa, sb)
    if not ch:
        return f"snap-{a} -> snap-{b}: no tracked differences"
    return f"snap-{a} -> snap-{b}:\n" + "\n".join(
        f"  {k}: {o!r} -> {n!r}" for k, (o, n) in ch.items()
    )


def snapshot_timeline_text(project: str) -> str:
    from .core.snapshots import snapshot_gitgraph

    return snapshot_gitgraph(project)


def run_pipeline_text(folder: str, question: str = "", autonomy_until: str = "END") -> str:
    fp = Path(folder).expanduser()
    if not fp.is_dir():
        return f"Error: not a directory: {folder}"
    from . import app
    from .config import ModelConfig

    mc = ModelConfig.default() or ModelConfig.cli("claude")
    r = app.run(fp.resolve(), model_config=mc, autonomy_until=autonomy_until,
                research_question=question, interactive=False)
    return (f"{r.project_name}: {'error' if r.error else 'done'} "
            f"(stages={len(r.completed_stages)}, cost=${r.cost_so_far:.4f})"
            + (f"\n  error: {r.error}" if r.error else ""))


def resume_pipeline_text(
    project: str, snapshot: str, at: str = "", branch: str = "main"
) -> str:
    from . import app
    from .config import ModelConfig

    mc = ModelConfig.default() or ModelConfig.cli("claude")
    try:
        r = app.resume(project, snapshot, model_config=mc, start_at=at or None,
                        branch=branch, autonomy_until="END", interactive=False)
    except ValueError as e:
        return f"Error: {e}"
    return (f"resumed '{project}' from snap-{snapshot}: "
            f"{'error' if r.error else 'done'} "
            f"(stages={len(r.completed_stages)}, cost=${r.cost_so_far:.4f})")


def snapshot_revert_text(project: str, snapshot: str) -> str:
    from .core.snapshots import restore_artifacts

    dest = config.atlas_path() / "projects" / project / "artifacts"
    written = restore_artifacts(project, snapshot, dest)
    return f"Restored {len(written)} file(s) from snap-{snapshot} of '{project}'."


def run_permission_decision(tool_name: str, *, interactive: bool, approver=None):
    """Fail-closed: read tools auto-approve, gated tools need confirmation,
    everything else is denied."""
    if tool_name in _READ_NAMES:
        return True, ""
    if tool_name not in _GATED_NAMES:
        return False, f"Tool '{tool_name}' is not permitted by the helix agent."
    if approver is not None:
        return (True, "") if approver() else (False, "User declined.")
    if not interactive:
        return False, "Gated tool denied (non-interactive session)."
    return False, "No approver configured."


def claude_code_auth():
    token = config.claude_code_oauth_token()
    if token is None:
        return {}, []
    return {config.CLAUDE_CODE_OAUTH_ENV: token}, ["ANTHROPIC_API_KEY"]


def _require_sdk():
    try:
        import claude_agent_sdk as sdk
    except ImportError as e:
        raise RuntimeError(
            "The Claude Agent SDK is not installed: pip install 'helix[agent]'"
        ) from e
    return sdk


def build_helix_server():
    sdk = _require_sdk()

    def _txt(s):
        return {"content": [{"type": "text", "text": s}]}

    @sdk.tool("atlas_search", "Search the Atlas wiki.", {"query": str})
    async def _as(a):
        return _txt(atlas_search_text(a["query"]))

    @sdk.tool("atlas_status", "Atlas page count + projects.", {})
    async def _ast(a):
        return _txt(atlas_status_text())

    @sdk.tool("decision_log", "Decision log for a project.", {"project": str})
    async def _dl(a):
        return _txt(decision_log_text(a["project"]))

    @sdk.tool("snapshot_list", "List a project's snapshots.", {"project": str})
    async def _sl(a):
        return _txt(snapshot_list_text(a["project"]))

    @sdk.tool("snapshot_show", "Show a snapshot.", {"project": str, "snap_id": str})
    async def _ss(a):
        return _txt(snapshot_show_text(a["project"], str(a["snap_id"])))

    @sdk.tool("snapshot_diff", "Diff two snapshots.",
              {"project": str, "a": str, "b": str})
    async def _sd(a):
        return _txt(snapshot_diff_text(a["project"], str(a["a"]), str(a["b"])))

    @sdk.tool("snapshot_timeline", "Mermaid gitGraph of history.", {"project": str})
    async def _st(a):
        return _txt(snapshot_timeline_text(a["project"]))

    @sdk.tool("run_pipeline", "Run the full pipeline on a folder (gated).",
              {"folder": str, "question": str, "autonomy_until": str})
    async def _rp(a):
        import anyio

        return _txt(await anyio.to_thread.run_sync(
            run_pipeline_text, a["folder"], a.get("question", ""),
            a.get("autonomy_until", "END")))

    @sdk.tool("resume_pipeline", "Resume from a snapshot (gated).",
              {"project": str, "snapshot": str, "at": str, "branch": str})
    async def _rsp(a):
        import anyio

        return _txt(await anyio.to_thread.run_sync(
            resume_pipeline_text, a["project"], str(a["snapshot"]),
            a.get("at", ""), a.get("branch", "main")))

    @sdk.tool("snapshot_revert", "Restore a snapshot's artifacts (gated).",
              {"project": str, "snapshot": str})
    async def _sr(a):
        return _txt(snapshot_revert_text(a["project"], str(a["snapshot"])))

    return sdk.create_sdk_mcp_server(
        name="helix", version=__version__,
        tools=[_as, _ast, _dl, _sl, _ss, _sd, _st, _rp, _rsp, _sr],
    )


def _confirm(tool_input: dict) -> bool:
    sys.stderr.write(
        f"\n[helix] agent wants a gated action: {tool_input}\n"
        f"        Expensive / writes to the project. Approve? [y/N] "
    )
    sys.stderr.flush()
    try:
        return input().strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _render(message, sdk) -> None:
    if isinstance(message, sdk.AssistantMessage):
        for b in message.content:
            if isinstance(b, sdk.TextBlock):
                click.echo(b.text)
            elif isinstance(b, sdk.ToolUseBlock):
                click.echo(f"  [tool] {b.name} {b.input}", err=True)
    elif isinstance(message, sdk.ResultMessage):
        if message.total_cost_usd is not None:
            click.echo(f"\n[helix] done — {message.num_turns} turn(s), "
                       f"${message.total_cost_usd:.4f}", err=True)


async def _run_async(prompt, max_turns) -> None:
    sdk = _require_sdk()
    server = build_helix_server()
    sdk_env, drop = claude_code_auth()
    for k in drop:
        os.environ.pop(k, None)

    async def can_use_tool(tool_name, tool_input, ctx):
        import anyio

        allowed, reason = await anyio.to_thread.run_sync(
            lambda: run_permission_decision(
                tool_name, interactive=sys.stdin.isatty(),
                approver=(lambda: _confirm(tool_input)) if sys.stdin.isatty() else None,
            )
        )
        return sdk.PermissionResultAllow() if allowed else sdk.PermissionResultDeny(
            message=reason)

    options = sdk.ClaudeAgentOptions(
        mcp_servers={"helix": server},
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
            await client.query(prompt)
            async for m in client.receive_response():
                _render(m, sdk)
            return
        click.echo("helix agent — ask about the Atlas/snapshots or request a "
                   "run. Empty line to exit.", err=True)
        while True:
            try:
                u = input("\nyou> ").strip()
            except EOFError:
                break
            if not u or u.lower() in ("exit", "quit"):
                break
            await client.query(u)
            async for m in client.receive_response():
                _render(m, sdk)


def run_agent_session(prompt: str | None = None, max_turns: int = 30) -> None:
    _require_sdk()
    import anyio

    anyio.run(_run_async, prompt, max_turns)
