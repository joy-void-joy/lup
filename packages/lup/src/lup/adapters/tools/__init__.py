"""Per-engine built-in tool-name tables.

The set of tools a backend exposes natively (shell, file, web) is a
property of that backend, not of any domain. ``tool_policy`` consumes an
engine's set as a parameter when it computes the allowlist, so the
generic policy names no backend; each engine module here declares its own
table. These modules hold only string tables and import no SDK.
"""
