"""Two runners over the same core: the plain ``loop`` (default, no heavy deps)
and ``langgraph_runner`` (the ``helix[sdk]`` extra). Both call
``core.transitions.next_stage`` so they cannot diverge on routing."""
