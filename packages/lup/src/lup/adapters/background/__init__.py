"""Background agents: independent SDK clients running beside a main session.

A background agent runs for the session lifetime with its own SDK
client, tools, and system prompt, communicating through shared mutable
state — observation (summarize as the conversation unfolds), research,
long-running execution; several can coexist in one session.

Contract and scaffolding are separate objects, composed at construction:
``BackgroundDriver`` is the per-engine verb (drive turns against the SDK
from a message stream), ``BackgroundAgent`` the SDK-free wake/debounce
scaffolding that runs a driver over its own stream, and
``BackgroundAgentParams`` the request each engine's ``Engine.background``
builds from — the engine owning the validation and defaults that are
properties of its backend (Codex rejects tools and requires an explicit
model; Claude defaults to an opus-class model and can act through
tools). See ``agent/tools/realtime.py`` in the template for the observer
integration example.
"""
