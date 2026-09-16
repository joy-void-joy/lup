# lup: ignore[constant-declaration]
# The file names below are a handshake across three processes: the generator
# writes them, the guard execs one by the other, and the shipped reader
# answers to both. A caller free to spell them differently is a caller free
# to ship a guard that reaches nothing.
"""What a plugin ships so the roster reaches a session at each prompt.

A session has no reason to ask who else is here at the moment a prompt
arrives, which is the moment it most needs to know. Both runtimes fire an
event when a prompt is submitted and read context back from it, so both
plugins carry the same two artifacts: a shell guard that exits without
starting an interpreter where this repository has no roster at all, and the
fold from :mod:`lup.coordination.changes`, shipped verbatim beside it, which
says what changed since this session's last prompt and nothing else.

Rendered once here rather than once per adapter, because what the adapters
own is two words — the event's name and the variable their plugin root is
exported as — and everything else would be the same file twice. Each adapter
passes those two words and registers the entry under its own event.

Every name the guard needs is interpolated from the definition that owns it:
a store directory renamed in one place moves the guard with it, instead of
leaving a script that reads a path nobody writes.
"""

from importlib import resources
from pathlib import Path

from lup.coordination.identity import MEMBER_ENV
from lup.coordination.roster import ROSTER_FILE
from lup.coordination.store import COORDINATION_DIR, STORE_DIR
from lup.formats.banner import (
    REGENERATE_COMMAND,
    VERBATIM_COPY,
    GeneratedBanner,
)
from lup.harness.models import Artifact, HookSet
from lup.types import JsonObject
from pydantic import BaseModel

RUNTIME_MODULE = "coordination_changes.py"
GUARD_SCRIPT = "coordination_changes.sh"
RUNTIME_ORIGIN = "lup.coordination.changes"
RUNTIME_SOURCE = "changes.py"
"""The two files a plugin carries for the roster at prompt time, and the fold's home.

Beside the delivery pair rather than inside it, because they answer at
different moments: delivery runs before every tool call and this runs once
per prompt, and a guard that had to tell the two apart would be paying for
the distinction on every call.
"""

DEPARTURE_MODULE = "coordination_departure.py"
DEPARTURE_SCRIPT = "coordination_departure.sh"
DEPARTURE_ORIGIN = "lup.coordination.departure"
DEPARTURE_SOURCE = "departure.py"
"""The two files a plugin carries for the roster as a session ends, and the writer's home.

The same guard shape under the runtime's ending event, handing over to the
one writer the plugin ships: the record that finishes this session's row,
which nothing else writes on a clean exit.
"""


def runtime_source(module: str) -> str:
    """A shipped runtime, read from the module that owns it rather than restated here."""
    return resources.files("lup.coordination").joinpath(module).read_text("utf-8")


def guard_body(event: str, runtime_module: str) -> str:
    """A roster-existence check that answers "nobody coordinates here" without Python.

    The store's roster file is the whole test: a repository whose sessions
    have never joined has no file, and a session there is told nothing rather
    than told the roster is empty — which would cost a line on every prompt
    of every project that never coordinates.

    Every failure exits zero. A prompt is not something a broken roster may
    stop, and neither is an exit, so a guard that cannot tell must let it
    through: the cost of being wrong that way is one prompt without the
    roster or one departure unwritten, and the cost of the other way is a
    session that cannot be prompted or cannot end.

    The member's launcher-proven id is handed over as an argument even where
    it is blank, so the reader can fall back to the id the runtime itself
    hands the hook; the environment variable's name stays the identity
    module's and the event's name stays the adapter's.
    """
    return f"""#!/bin/sh
command -v python3 >/dev/null 2>&1 || exit 0
shared=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
case "$shared" in
    /*) ;;
    *) shared="$PWD/$shared" ;;
esac
root="$shared/{STORE_DIR}/{COORDINATION_DIR}"
[ -f "$root/{ROSTER_FILE}" ] || exit 0
exec python3 "${{0%/*}}/../runtime/{runtime_module}" "$root" "${MEMBER_ENV}" "{event}"
"""


def guard_command(plugin_root_env: str, guard_script: str) -> str:
    """The hooks entry, which never refuses however badly it goes.

    No `|| exit 2` beside it, unlike the policy guard's: a fold that fails is
    a session that was not told who arrived, and turning that into a refused
    prompt would make an unreadable roster stop the work it was trying to
    inform.
    """
    return f'sh "${plugin_root_env}/hooks/scripts/{guard_script}" || exit 0'


def hook_entry(plugin_root_env: str, guard_script: str) -> JsonObject:
    """The one command hook a runtime registers under one of its events.

    A short timeout, because the fold is three small files and a prompt is
    waiting on it: a store that takes longer than this to read is one the
    session is better off without for this prompt. An ending runs under a
    budget of its own that the same figure raises to fit.
    """
    return {
        "type": "command",
        "command": guard_command(plugin_root_env, guard_script),
        "timeout": 10,
    }


class PromptHook(BaseModel, frozen=True):
    """What one plugin registers and carries for the roster at prompt time.

    Empty on both counts where the project declared no roster: a hook that
    fired for a population nobody declared would read an absent store on
    every prompt to say nothing, and a plugin would carry two files for it.
    """

    registered: JsonObject
    artifacts: list[Artifact]


def prompt_hook(
    plugin_root: Path, plugin_root_env: str, source: HookSet, event: str
) -> PromptHook:
    """The hooks entry under *event* and the files behind it, where a roster is declared.

    The declaration is the hook set's own ``peer_policy``: a project whose
    sessions find each other on a roster is one whose sessions are told when
    it moves, and one that declined the roster is told nothing here either.
    """
    if source.peer_policy is None:
        return PromptHook(registered={}, artifacts=[])
    return PromptHook(
        registered={event: [{"hooks": [hook_entry(plugin_root_env, GUARD_SCRIPT)]}]},
        artifacts=roster_artifacts(
            plugin_root,
            source.id,
            event,
            guard_script=GUARD_SCRIPT,
            runtime_module=RUNTIME_MODULE,
            source_file=RUNTIME_SOURCE,
            origin=RUNTIME_ORIGIN,
        ),
    )


def departure_hook(
    plugin_root: Path, plugin_root_env: str, source: HookSet, event: str
) -> PromptHook:
    """The hooks entry under the runtime's ending event, and the files behind it.

    Declared by the same ``peer_policy`` as the prompt-time hook: a session
    on a roster is one whose row has to end when it does, and a project that
    declined the roster has no row to end.
    """
    if source.peer_policy is None:
        return PromptHook(registered={}, artifacts=[])
    return PromptHook(
        registered={
            event: [{"hooks": [hook_entry(plugin_root_env, DEPARTURE_SCRIPT)]}]
        },
        artifacts=roster_artifacts(
            plugin_root,
            source.id,
            event,
            guard_script=DEPARTURE_SCRIPT,
            runtime_module=DEPARTURE_MODULE,
            source_file=DEPARTURE_SOURCE,
            origin=DEPARTURE_ORIGIN,
        ),
    )


def roster_artifacts(
    plugin_root: Path,
    semantic_id: str,
    event: str,
    guard_script: str,
    runtime_module: str,
    source_file: str,
    origin: str,
) -> list[Artifact]:
    """A guard and the runtime it hands over to, as one plugin carries them."""
    return [
        Artifact.generated(
            path=plugin_root / "hooks" / "scripts" / guard_script,
            body=guard_body(event, runtime_module),
            semantic_id=semantic_id,
            banner=GeneratedBanner(source=__name__, command=REGENERATE_COMMAND),
            executable=True,
        ),
        Artifact(
            path=plugin_root / "hooks" / "runtime" / runtime_module,
            content=runtime_source(source_file),
            semantic_id=semantic_id,
            banner=VERBATIM_COPY.compiled_from(origin),
        ),
    ]
