"""Telemetry: what a run records about itself for later analysis.

A markdown trace beside its machine-readable sidecar, console rendering, and
per-tool metrics with a file-backed flush for subprocess tools.

`trace` accumulates the markdown session trace and its machine-readable
event sidecar; `display` renders content blocks to the console with
color-coded tool pairing; `blocks` holds the block-extraction and
truncation helpers the two share. `metrics` tracks per-tool call counts and
timings, with a file-backed flush for subprocess tools.
"""
