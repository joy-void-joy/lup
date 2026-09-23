# lup: ignore[constant-declaration]
# The file names below are a handshake across three processes: the generator
# writes them, the guard runs one by the other, and the host half reads its
# settings under its own name. A caller free to spell them differently is a
# caller free to ship a guard that reaches nothing.
"""What a plugin ships so a session is named for its work at its first prompt.

Three things travel, registered only where the hook set declares both a
roster and the naming: the guard every prompt-time fold of the roster is
started by, which exits without an interpreter where the repository's store
holds nothing; the runtime's host half, shipped verbatim, which imports
:mod:`lup.coordination.bare.naming` from the package already beside it; and
the declaration compiled into that runtime's words, under the host half's
name beside the hooks manifest — where
:func:`lup.coordination.bare.naming.compiled_for` looks, and outside the
runtime directory a policy evaluator's snapshot admits only source into.

Rendered once here rather than once per adapter, because what the adapters
own is the event's name, the variable their plugin root is exported as, the
host half, the words their CLI takes for the declared tier and effort, and
whether the prompt waits on the ask — and everything else would be the same
files twice.
"""

import json
from collections.abc import Callable, Mapping
from math import ceil
from pathlib import Path

from lup.coordination.bare.naming import Naming
from lup.formats.banner import (
    COMMENT_FREE,
    REGENERATE_COMMAND,
    VERBATIM_COPY,
    GeneratedBanner,
)
from lup.harness.models import Artifact, HookSet, SessionNaming
from lup.providers.roster_prompt import PromptHook, guard_body, guard_command
from lup.types import JsonObject, ModelTier, SessionEffort

GUARD_SCRIPT = "session_naming.sh"
RUNTIME_ENTRY = "session_naming.py"
"""What the plugin carries: the guard, and the host half the guard runs."""


def compiled(declared: SessionNaming, model: str, effort: str) -> Naming:
    """The declaration in one runtime's words, as its host half reads it."""
    return Naming(
        model=model,
        effort=effort,
        instruction=declared.instruction,
        attempts=declared.attempts,
        deadline_seconds=declared.deadline_seconds,
        longest=declared.longest,
    )


def naming_hook(
    plugin_root: Path,
    plugin_root_env: str,
    source: HookSet,
    event: str,
    host: str,
    host_origin: str,
    model_of: Callable[[ModelTier], str | None],
    efforts: Mapping[SessionEffort, str],
    waits: bool,
) -> PromptHook:
    """The entry under *event* and the files behind it, where naming is declared.

    *waits* is whether the runtime holds the prompt for the hook's answer. One
    that takes a name only from that answer waits on the ask, and its entry's
    timeout leaves the declared deadline room to run out first, so an ask that
    overruns is abandoned by the host half rather than killed by the runtime
    halfway through settling a name. One that names the session elsewhere
    returns at once, and keeps the short budget every prompt-time fold has.

    A tier the runtime cannot spell registers nothing, rather than an ask that
    could only fail.
    """
    declared = source.session_naming
    model = model_of(declared.tier) if declared is not None else None
    if declared is None or source.peer_policy is None or model is None:
        return PromptHook(registered={}, artifacts=[])
    entry: JsonObject = {
        "type": "command",
        "command": guard_command(plugin_root_env, GUARD_SCRIPT),
        "timeout": ceil(declared.deadline_seconds) + 10 if waits else 10,
    }
    hooks = plugin_root / "hooks"
    return PromptHook(
        registered={event: [{"hooks": [entry]}]},
        artifacts=[
            Artifact.generated(
                path=hooks / "scripts" / GUARD_SCRIPT,
                body=guard_body(event, RUNTIME_ENTRY),
                semantic_id=source.id,
                banner=GeneratedBanner(source=__name__, command=REGENERATE_COMMAND),
                executable=True,
            ),
            Artifact(
                path=hooks / "runtime" / RUNTIME_ENTRY,
                content=host,
                semantic_id=source.id,
                banner=VERBATIM_COPY.compiled_from(host_origin),
            ),
            Artifact(
                path=hooks / Path(RUNTIME_ENTRY).with_suffix(".json"),
                content=json.dumps(
                    compiled(declared, model, efforts[declared.effort]),
                    indent=2,
                    sort_keys=True,
                ),
                semantic_id=source.id,
                banner=COMMENT_FREE.compiled_from(source.id),
            ),
        ],
    )
