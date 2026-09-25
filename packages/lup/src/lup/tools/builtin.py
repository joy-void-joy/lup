"""Which of its runtime's built-in tools a session is given.

Three presets every runtime answers, and in each adapter an explicit list of
that runtime's own tool names — a Literal, so a misspelt tool is a type error
where it is written and a validation error where it is read, rather than a
grant the runtime quietly never makes.

``"web"`` is the default for a session opened in process: it fetches and
searches, and reads, writes and runs nothing on the machine it runs on until
something grants that explicitly. ``"stock"`` is everything the runtime ships,
the coding agent a terminal launch starts. ``"none"`` leaves the session only
the servers it declares.
"""

from typing import Literal

type BuiltinPreset = Literal["stock", "web", "none"]
"""A runtime's built-in tools by preset: all of them, the web alone, or none."""
