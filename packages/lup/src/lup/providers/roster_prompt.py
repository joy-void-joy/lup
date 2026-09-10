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
"""The two files a plugin carries for the roster at prompt time, and the fold's home.

Beside the delivery pair rather than inside it, because they answer at
different moments: delivery runs before every tool call and this runs once
per prompt, and a guard that had to tell the two apart would be paying for
the distinction on every call.
"""


def changes_runtime_source() -> str:
    """The fold, read from the module that owns it rather than restated here."""
    return resources.files("lup.coordination").joinpath("changes.py").read_text("utf-8")


def guard_body(event: str) -> str:
    """A roster-existence check that answers "nobody coordinates here" without Python.

    The store's roster file is the whole test: a repository whose sessions
    have never joined has no file, and a session there is told nothing rather
    than told the roster is empty — which would cost a line on every prompt
    of every project that never coordinates.

    Every failure exits zero. A prompt is not something a broken roster may
    stop, so a guard that cannot tell must let it through: the cost of being
    wrong that way is one prompt without the roster, and the cost of the
    other way is a session that cannot be prompted.

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
exec python3 "${{0%/*}}/../runtime/{RUNTIME_MODULE}" "$root" "${MEMBER_ENV}" "{event}"
"""


def prompt_command(plugin_root_env: str) -> str:
    """The hooks entry, which never refuses however badly it goes.

    No `|| exit 2` beside it, unlike the policy guard's: a fold that fails is
    a session that was not told who arrived, and turning that into a refused
    prompt would make an unreadable roster stop the work it was trying to
    inform.
    """
    return f'sh "${plugin_root_env}/hooks/scripts/{GUARD_SCRIPT}" || exit 0'


def prompt_entry(plugin_root_env: str) -> JsonObject:
    """The one command hook a runtime registers under its prompt event.

    A short timeout, because the fold is three small files and a prompt is
    waiting on it: a store that takes longer than this to read is one the
    session is better off without for this prompt.
    """
    return {
        "type": "command",
        "command": prompt_command(plugin_root_env),
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
        registered={event: [{"hooks": [prompt_entry(plugin_root_env)]}]},
        artifacts=prompt_artifacts(plugin_root, source.id, event),
    )


def prompt_artifacts(plugin_root: Path, semantic_id: str, event: str) -> list[Artifact]:
    """The guard and the fold, as one plugin carries them."""
    return [
        Artifact.generated(
            path=plugin_root / "hooks" / "scripts" / GUARD_SCRIPT,
            body=guard_body(event),
            semantic_id=semantic_id,
            banner=GeneratedBanner(source=__name__, command=REGENERATE_COMMAND),
            executable=True,
        ),
        Artifact(
            path=plugin_root / "hooks" / "runtime" / RUNTIME_MODULE,
            content=changes_runtime_source(),
            semantic_id=semantic_id,
            banner=VERBATIM_COPY.compiled_from(RUNTIME_ORIGIN),
        ),
    ]
