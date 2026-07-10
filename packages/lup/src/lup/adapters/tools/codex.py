"""The Codex runtime's built-in tool vocabulary (SDK-free).

The names Codex-native builtin activity surfaces as in lup traffic. The
thread-item projection (``lup.adapters.clients.codex.messages``) emits
each native builtin as a tool-use block under these names — command
execution and file changes under their native identifiers, web search
under the shared ``WebSearch`` constant per the lingua-franca rule in
:mod:`lup.adapters.tools.names`.
"""

from lup.adapters.tools.names import WEB_SEARCH

COMMAND_EXECUTION = "command_execution"
FILE_CHANGE = "file_change"

CODEX_BUILTIN_TOOLS: frozenset[str] = frozenset(  # lup: ignore[frozenset-shape]
    {
        COMMAND_EXECUTION,
        FILE_CHANGE,
        WEB_SEARCH,
    }
)
"""The tools Codex-native activity surfaces as (shell/file/web).

A name table, not a selector: the Codex runtime's builtins are always
on and not individually restrictable, so the ``tools`` intent knob
stays refused by the codex translation (``build_codex_native`` never
reads it). Consumers key on these names when reading lup traffic —
matching a command-execution block, diffing file changes, or counting
web searches."""
