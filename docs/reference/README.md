# API Reference

Reference documentation for all public modules, classes, and functions in helix-mini.

## Modules

| Module | Description |
|--------|-------------|
| [app](app.md) | `HelixMini` facade class — main programmatic entry point |
| [atlas](atlas.md) | Persistent markdown wiki — `Atlas`, `Page`, `PageWrite`, `ingest_folder` |
| [config](config.md) | Model selection, provider registry, settings — `ModelConfig`, `PROVIDERS` |
| [pipeline](pipeline.md) | Forge pipeline — `ForgeState`, `Agents`, runner, router, decisions, snapshots |
| [sandbox](sandbox.md) | LLM output validation — path, title, content, batch sanitization |
| [llm](llm.md) | LLM call wrapper — `call_llm`, `call_llm_json`, `LLMResponse` |
| [docker](docker.md) | Docker sandbox execution — `run_sandboxed` |
| [cli](cli.md) | CLI commands — `run`, `setup`, `init`, `status`, `log`, `atlas search` |
