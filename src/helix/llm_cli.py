"""CLI-backed LLM engine — pilot the pipeline through an LLM's own CLI.

``cli/<engine>[:<model>]`` models route here instead of litellm. Engines are
declarative so adding one is a ``[cli.<name>]`` block in ``helix.toml``, not a
code change. Claude Code is the built-in reference engine and needs no API key.
"""

from __future__ import annotations

import functools
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field

from .config import CALL_CAP_DEFAULT

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # CLIs cold-start and stream; far slower than an API call


class CLIEngineError(RuntimeError):
    """Raised when a CLI engine is misconfigured or its invocation fails."""


@dataclass
class CLIEngine:
    """Declarative description of how to drive one LLM CLI headless."""

    name: str
    bin: str
    prompt_via: str = "arg"  # "stdin" | "arg"
    base_args: list[str] = field(default_factory=list)
    model_flag: str | None = None
    system_flag: str | None = None
    output_format: str = "text"  # "json" | "text"
    json_content_path: str = "result"
    json_cost_path: str | None = None
    json_usage_path: str | None = None
    json_error_path: str | None = None
    reports_cost: bool = False
    strip_env: list[str] = field(default_factory=list)
    uses_claude_code_auth: bool = False
    timeout: int = DEFAULT_TIMEOUT

    def available(self) -> bool:
        return bool(self.bin) and shutil.which(self.bin) is not None


CLAUDE = CLIEngine(
    name="claude",
    bin="claude",
    prompt_via="stdin",
    base_args=["-p", "--output-format", "json", "--max-turns", "1"],
    model_flag="--model",
    system_flag="--append-system-prompt",
    output_format="json",
    json_content_path="result",
    json_cost_path="total_cost_usd",
    json_usage_path="usage",
    json_error_path="is_error",
    reports_cost=True,
    uses_claude_code_auth=True,
)
GENERIC = CLIEngine(name="generic", bin="")
_BUILTIN: dict[str, CLIEngine] = {"claude": CLAUDE}


def parse_cli_model(model: str) -> tuple[str, str | None]:
    rest = model.split("/", 1)[1] if "/" in model else model
    if ":" in rest:
        engine, native = rest.split(":", 1)
        return engine, (native or None)
    return rest, None


@functools.lru_cache(maxsize=1)
def _load_config_engines() -> dict[str, CLIEngine]:
    from .config import load_helix_toml

    out: dict[str, CLIEngine] = {}
    for name, spec in (load_helix_toml().get("cli") or {}).items():
        if not isinstance(spec, dict):
            continue
        out[name] = CLIEngine(
            name=name,
            bin=spec.get("bin", name),
            prompt_via=spec.get("prompt_via", GENERIC.prompt_via),
            base_args=list(spec.get("base_args", [])),
            model_flag=spec.get("model_flag", GENERIC.model_flag),
            system_flag=spec.get("system_flag", GENERIC.system_flag),
            output_format=spec.get("output_format", GENERIC.output_format),
            json_content_path=spec.get("json_content_path", GENERIC.json_content_path),
            json_cost_path=spec.get("json_cost_path", GENERIC.json_cost_path),
            json_usage_path=spec.get("json_usage_path", GENERIC.json_usage_path),
            json_error_path=spec.get("json_error_path", GENERIC.json_error_path),
            reports_cost=bool(spec.get("reports_cost", GENERIC.reports_cost)),
            strip_env=list(spec.get("strip_env", [])),
            uses_claude_code_auth=bool(
                spec.get("uses_claude_code_auth", GENERIC.uses_claude_code_auth)
            ),
            timeout=int(spec.get("timeout", GENERIC.timeout)),
        )
    return out


def get_engine(name: str) -> CLIEngine:
    engines = {**_load_config_engines(), **_BUILTIN}
    if name not in engines:
        raise CLIEngineError(
            f"Unknown CLI engine '{name}'. Built-in: {sorted(_BUILTIN)}. "
            f"Add a [cli.{name}] block to helix.toml to define it."
        )
    return engines[name]


def engine_reports_cost(model: str) -> bool:
    try:
        return get_engine(parse_cli_model(model)[0]).reports_cost
    except CLIEngineError:
        return False


def _dig(obj: object, path: str) -> object:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def call_cli_llm(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: int | None = None,
):
    """Run an LLM CLI as the inference backend. Returns an ``LLMResponse``."""
    from .llm import LLMResponse

    engine_name, native_model = parse_cli_model(model)
    eng = get_engine(engine_name)
    if not eng.available():
        raise CLIEngineError(
            f"CLI engine '{eng.name}' is not on PATH (looked for '{eng.bin}')."
        )

    args = [eng.bin, *eng.base_args]
    if native_model and eng.model_flag:
        args += [eng.model_flag, native_model]
    prompt = user
    if eng.system_flag and system:
        args += [eng.system_flag, system]
    elif system:
        prompt = f"{system}\n\n---\n\n{user}"
    stdin_data = prompt if eng.prompt_via == "stdin" else None
    if eng.prompt_via != "stdin":
        args.append(prompt)

    from .config import claude_subprocess_env

    env = claude_subprocess_env(
        tuple(eng.strip_env), prefer_oauth=eng.uses_claude_code_auth
    )
    log.info("CLI engine '%s' (model=%s)", eng.name, native_model or "default")
    try:
        proc = subprocess.run(
            args, input=stdin_data, capture_output=True, text=True,
            timeout=timeout or eng.timeout, env=env,
        )
    except FileNotFoundError as e:
        raise CLIEngineError(f"Failed to launch '{eng.bin}': {e}") from e
    except subprocess.TimeoutExpired as e:
        raise CLIEngineError(
            f"CLI engine '{eng.name}' timed out after {timeout or eng.timeout}s"
        ) from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        raise CLIEngineError(f"CLI engine '{eng.name}' exited {proc.returncode}: {detail}")

    out = proc.stdout or ""
    cost = 0.0
    usage: dict[str, int] = {}
    if eng.output_format == "json":
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise CLIEngineError(
                f"CLI engine '{eng.name}' did not return valid JSON: {out[:300]}"
            ) from e
        if eng.json_error_path and _dig(data, eng.json_error_path):
            msg = _dig(data, eng.json_content_path) or out[:300]
            raise CLIEngineError(f"CLI engine '{eng.name}' reported an error: {msg}")
        content = _dig(data, eng.json_content_path) or ""
        if eng.json_cost_path:
            c = _dig(data, eng.json_cost_path)
            cost = float(c) if isinstance(c, (int, float)) else 0.0
        if eng.json_usage_path:
            u = _dig(data, eng.json_usage_path)
            if isinstance(u, dict):
                usage = {
                    "prompt_tokens": int(
                        u.get("input_tokens", u.get("prompt_tokens", 0)) or 0
                    ),
                    "completion_tokens": int(
                        u.get("output_tokens", u.get("completion_tokens", 0)) or 0
                    ),
                }
    else:
        content = out.strip()
    if not isinstance(content, str):
        content = str(content)
    return LLMResponse(content=content, usage=usage, cost=cost)


def call_cap_for(
    model: str,
    stage_models: list[str] | None = None,
    default: int | None = None,
) -> int:
    """Call-count cap for a run, or 0 if every model reliably reports cost."""
    cap = CALL_CAP_DEFAULT if default is None else default
    for m in [model, *(stage_models or [])]:
        if m.startswith("cli/") and not engine_reports_cost(m):
            return cap
    return 0
