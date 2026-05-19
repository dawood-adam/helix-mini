"""The MCP drive surface: a stdio server (`server.py`) and the client
bridge (`client_io.py`) implementing the standardized `helix.io` seam.

These are the ONLY modules that import the `mcp` SDK. Core / llm / io stay
SDK-free, so the dependency-light invariant holds and the seam is testable
without `mcp` installed."""
