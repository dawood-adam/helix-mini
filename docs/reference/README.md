# API Reference

Reference documentation for all public modules, classes, and functions in helix-mini.

## Modules

| Module | Description |
|--------|-------------|
| [app](app.md) | `HelixMini` facade class — main programmatic entry point |
| [atlas](atlas.md) | Persistent markdown wiki — `Atlas`, `Page`, `PageWrite`, `ingest_folder` |
| [config](config.md) | Model selection, provider registry, OAuth/subscription auth, settings — `ModelConfig`, `PROVIDERS`, `claude_subprocess_env` |
| [pipeline](pipeline.md) | Forge pipeline — `ForgeState`, `Agents`, runner, router, decisions, snapshots |
| [sandbox](sandbox.md) | LLM output validation — path, title, content, batch sanitization |
| [llm](llm.md) | LLM call wrapper / single chokepoint — `call_llm`, `call_llm_json`, `LLMResponse` |
| [llm_cli](llm_cli.md) | CLI-backed LLM engine — `CLIEngine`, `call_cli_llm`, `cli/claude` |
| [agent_sdk](agent_sdk.md) | Claude Agent SDK driver — helix tools as in-process MCP |
| [docker](docker.md) | Docker sandbox execution — `run_sandboxed` |
| [cli](cli.md) | CLI commands — `run`, `agent`, `setup`, `init`, `status`, `log`, `atlas search` |
