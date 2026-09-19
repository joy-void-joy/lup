"""Claude Code's half of the subagent cleanup fold, run as a bare script.

Shipped verbatim into the plugin's ``hooks/runtime/`` beside the kernel it
imports, and registered under ``SubagentStart`` and ``SubagentStop``. It holds
only what Claude Code spells for itself: the payload's keys, the transcript's
shape, the names of the tools that arm and end background work, and the two
output envelopes. The judgement — which listed tasks the stopping subagent
started, and what it is told — is :mod:`kernel.subagents`'s.

Measured on 2.1.278 rather than read from the docs, with the recordings kept
as fixtures under ``tests/unit/fixtures/subagent_cleanup/``. At
``SubagentStop`` the payload carries ``agent_id``, ``agent_transcript_path``,
``stop_hook_active`` and ``background_tasks``, the last being the whole
session's: each entry is typed ``shell`` — a Monitor and a backgrounded
command alike — or ``subagent``, and the subagent's own entry is among them.
A transcript line of type ``assistant`` carries the tool calls under
``message.content`` as blocks of type ``tool_use``. A block on the first pass
made the subagent stop its task within seconds and pass on the second, which
the runtime flags with ``stop_hook_active``.

Every failure is silence. A fold that cannot read is a report let through,
which costs one leaked task, the same as having no fold — the opposite of a
permission hook, whose failure must refuse.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

# The hook is launched as a bare script, promised no cwd, PYTHONPATH, or
# interpreter environment, and this file sits in the `runtime/` directory
# that holds the kernel package and the coordination store's reader. Naming
# it as a search path is what lets the imports below resolve.
sys.path.insert(0, str(Path(__file__).parent))
from coordination.store import loaded
from kernel.subagents import (
    Armed,
    BackgroundTask,
    Child,
    Leftover,
    leftovers,
    notice,
    refusal,
)


class ListedTask(TypedDict, total=False):
    """One entry of ``background_tasks`` as Claude Code spells it."""

    id: str
    type: str
    status: str
    description: str
    command: str
    agent_type: str


class ToolInput(TypedDict, total=False):
    """The arguments of the three calls that start background work."""

    command: str
    run_in_background: bool
    description: str
    subagent_type: str


class ToolUse(TypedDict, total=False):
    """One block of an assistant message, as far as a tool call is concerned."""

    type: str
    name: str
    input: ToolInput


class Message(TypedDict, total=False):
    content: list[ToolUse] | str


class Entry(TypedDict, total=False):
    """One line of a subagent's transcript, as far as its tool calls need."""

    type: str
    message: Message


class Payload(TypedDict, total=False):
    """What the two events hand the hook, as far as it reads."""

    hook_event_name: str
    agent_id: str
    agent_transcript_path: str
    stop_hook_active: bool
    background_tasks: list[ListedTask]


class Pushed(TypedDict):
    hookEventName: str
    additionalContext: str


class Context(TypedDict):
    """The start-time answer: context the subagent reads, refusing nothing."""

    hookSpecificOutput: Pushed


class Refusal(TypedDict):
    """The stop-time answer: the subagent continues with the reason as its next instruction."""

    decision: str
    reason: str


def armed(transcript: Path) -> Armed:
    """Every background start the subagent's transcript records.

    A `Monitor` and a `Bash` call run in the background both become shell
    tasks, keyed by command; an `Agent` call becomes a subagent task, keyed by
    what it was started with.
    """

    def calls() -> Iterator[ToolUse]:
        for entry in loaded(transcript, Entry):
            message = entry.get("message", Message())
            content = message.get("content", [])
            if entry.get("type") == "assistant" and not isinstance(content, str):
                yield from (
                    block for block in content if block.get("type") == "tool_use"
                )

    def backgrounded(block: ToolUse) -> bool:
        arguments = block.get("input", ToolInput())
        match block.get("name"):
            case "Monitor":
                return True
            case "Bash":
                return arguments.get("run_in_background", False)
        return False

    started = list(calls())
    return Armed(
        commands=[
            block.get("input", ToolInput()).get("command", "")
            for block in started
            if backgrounded(block)
        ],
        children=[
            Child(
                description=block.get("input", ToolInput()).get("description", ""),
                agent_type=block.get("input", ToolInput()).get("subagent_type", ""),
            )
            for block in started
            if block.get("name") == "Agent"
        ],
    )


def decoded(listed: ListedTask) -> BackgroundTask | None:
    """One listed task as the kernel reads it, or nothing for a kind it does not judge."""
    match listed.get("type"):
        case "shell":
            return BackgroundTask(
                id=listed.get("id", ""),
                kind="shell",
                command=listed.get("command", ""),
            )
        case "subagent":
            return BackgroundTask(
                id=listed.get("id", ""),
                kind="subagent",
                description=listed.get("description", ""),
                agent_type=listed.get("agent_type", ""),
            )
    return None


def decided(payload: Payload) -> Context | Refusal | None:
    """The answer to one event, or nothing where the report goes through."""
    match payload.get("hook_event_name"):
        case "SubagentStart":
            return Context(
                hookSpecificOutput=Pushed(
                    hookEventName="SubagentStart",
                    additionalContext=notice(
                        "a Monitor",
                        "TaskStop",
                        # Both measured on 2.1.278 and kept as fixtures: the
                        # monitor survives the report, and each line it emits
                        # resumes the subagent that reported.
                        Leftover(resumes=True, refused=True),
                    ),
                )
            )
        case "SubagentStop" if not payload.get("stop_hook_active", False):
            tasks = [
                task
                for listed in payload.get("background_tasks", [])
                if (task := decoded(listed)) is not None
            ]
            left = leftovers(
                payload.get("agent_id", ""),
                tasks,
                armed(Path(payload.get("agent_transcript_path", ""))),
            )
            if left:
                return Refusal(decision="block", reason=refusal(left, "TaskStop"))
    return None


def main() -> None:
    """Answer the event on stdin, or say nothing and let the subagent through."""
    try:
        payload: Payload = json.load(sys.stdin)
        answer = decided(payload)
    except Exception:
        return
    if answer is not None:
        print(json.dumps(answer))


if __name__ == "__main__":
    main()
