"""Helix — a self-auditing research pipeline with a persistent wiki.

The package is split into two layers:

- ``helix.core`` — the dependency-light pipeline (stages, gates, transitions,
  Atlas, snapshots). Imports with neither ``langgraph`` nor ``litellm``.
- ``helix.orchestrator`` — two runners over that core: a plain loop (default,
  CLI mode) and a LangGraph runner (the ``helix[sdk]`` extra).
"""

__version__ = "0.2.0"
