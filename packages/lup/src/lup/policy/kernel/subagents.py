"""A subagent reports only after the background work it started has stopped.

A subagent that arms a watch or backgrounds a command and then reports leaves
the task running: the runtime keeps it, and each line it emits resumes the
finished subagent, which reports again, until somebody ends the task by id.
The runtime's own note on such a subagent reads "stopped with background work
of its own still running. It may resume on its own when that work completes
or reports."

Two moments, one judgement. As a subagent starts, it is told that what it
arms is its own to stop. As it is about to report, the runtime hands the hook
every background task of the session and the subagent's own transcript; the
tasks the subagent started are the ones whose start its transcript records,
and while any of them is still listed the report is refused once, with a
reason naming each task and the call that ends it. Once, because the runtime
flags a stop that already follows a refusal, and a second refusal would hold
a subagent that cannot comply forever, when the runtime's own notification
already tells the parent it stopped with work running.

The main agent is deliberately not gated. Its stop fires with background
subagents listed as running, and that wait is the point: the events it is
waiting for are what wake it.

What a runtime spells — the payload's keys, the transcript's shape, the names
of the tools that arm and end a task, the output envelopes — is its host
half's; this module holds the part every runtime answers identically.
"""

from typing import Literal, TypedDict

type TaskKind = Literal["shell", "subagent"]
"""The runtime's own partition of what it keeps running: a shell task, which a
watch and a backgrounded command both are, or a subagent."""


class BackgroundTask(TypedDict, total=False):
    """One background task of the session, as the host half decodes it.

    ``id`` is what the ending call takes. ``command`` is what a shell task
    runs; ``description`` and ``agent_type`` are what a subagent task was
    started with. Each is how the task is matched back to the call that
    started it, because the list carries nothing else that says whose it is.
    """

    id: str
    kind: TaskKind
    command: str
    description: str
    agent_type: str


class Child(TypedDict):
    """What a subagent task was started with, as both the call and the list spell it."""

    description: str
    agent_type: str


class Armed(TypedDict):
    """What a subagent started in the background, as its transcript records it.

    Shell tasks by the command they were given, subagents by what they were
    started with — the same keys the task list carries.
    """

    commands: list[str]
    children: list[Child]


def leftovers(
    own_id: str, tasks: list[BackgroundTask], armed: Armed
) -> list[BackgroundTask]:
    """The listed tasks this subagent started, every one still running.

    The list is the whole session's, with nothing marking whose each is, so a
    task is the subagent's when the subagent's own transcript armed it. The
    subagent's own entry is in the same list, and is nobody's to stop.
    """

    def owned(task: BackgroundTask) -> bool:
        match task.get("kind"):
            case "shell":
                return task.get("command", "") in armed["commands"]
            case "subagent":
                started = Child(
                    description=task.get("description", ""),
                    agent_type=task.get("agent_type", ""),
                )
                return started in armed["children"]
        return False

    return [task for task in tasks if task.get("id", "") != own_id and owned(task)]


def refusal(tasks: list[BackgroundTask], ending_call: str) -> str:
    """Why the report is refused: each task by id, and the call that ends it."""
    named = ", ".join(
        f"{task.get('id', '')} ({task.get('kind', '')}:"
        f" {task.get('command') or task.get('description') or ''})"
        for task in tasks
    )
    return (
        f"Background work you started is still running: {named}. Stop each"
        f" with {ending_call}, then finish. A task left running resumes you"
        " after you have reported."
    )


def notice(watch_call: str, ending_call: str) -> str:
    """What a subagent is told as it starts: what it arms is its own to stop."""
    return (
        f"Background work you start — a {watch_call}, a command run in the"
        " background, a subagent — is yours to stop with"
        f" {ending_call} before you report. A task left running resumes you"
        " after you have finished, and your report is refused once while any"
        " of it runs."
    )
