"""Tool-name vocabulary: the neutral names and per-engine builtin tables.

``names`` holds the framework's lingua-franca constants; each engine
module declares its own builtin table on top of them — the set of tools
its backend exposes natively is a property of that backend, not of any
domain. A table names what builtin activity surfaces as in lup traffic;
whether the set is restrictable is the separate ``tools`` intent knob,
judged by each client translation. These modules hold only string tables
and import no SDK.
"""
