"""Claude Code's hooks: its payloads in, lup's events, its outputs out.

| Claude Code hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `PreToolUse` | `CallStarted`; for `Edit` and `Write`, judged before it lands first |
| `PostToolUse`, `PostToolUseFailure` | `CallFinished` |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |

Claude Code asks the operator in its own prompt: `PreToolUse` answers `allow`, `ask`
or `deny`, and a hook's `ask` prompts in auto mode too. The agent hears a
checkpoint's report as `additionalContext` beside the call's result, and the turn
can't end while a `Stop` hook answers `decision: block`. When judging itself fails
at a turn's end, the turn ends, and the operator is warned once in
`systemMessage`.

What this relies on, from Claude Code's hooks reference
(code.claude.com/docs/en/hooks):
- `tool_use_id` is in both `PreToolUse` and `PostToolUse`, so a call's start and
  finish match; a call that fails fires `PostToolUseFailure` instead, with the same
  id;
- `PreToolUse` "runs before a tool call executes", `PostToolUse` "after a tool call
  succeeds": a call never finishes before it starts, so the calls running stay
  right when calls run in parallel, whose hooks "run in parallel";
- a `command` hook's timeout defaults to 600 seconds, and "a timed-out command
  ... hook doesn't block the tool call", so a judgement must answer within it.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Annotated, Literal, override

from pydantic import Field, TypeAdapter
from pydantic.alias_generators import to_camel

from lup.types import JsonObject, Model, Settings
from lup_dev.policy.before import Decision, Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    Bench,
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
    first_warning,
)
from lup_dev.policy.report import judge_failed
from lup_dev.policy.runtime import Runtime


class Variables(Settings):
    """The variables Claude Code sets in the commands it runs."""

    claude_code_child_session: str | None = None
    """`CLAUDE_CODE_CHILD_SESSION`, `1` in what Claude Code's tools and hooks run.

    Its environment-variable reference: "Set to `1` in subprocesses Claude Code
    spawns via the Bash, PowerShell, and Monitor tools, hook commands, and status
    line commands". Unlike `CLAUDECODE`, IDE extensions don't set it in their
    terminals, where the operator may answer a hold.
    """


class Claude(Runtime):
    """Claude Code, as the judge sees it."""

    @override
    def name(self) -> str:
        return "claude"

    @override
    def asks_before(self) -> bool:
        return True

    @override
    def inside(self) -> bool:
        return bool(Variables().claude_code_child_session)


class Output(Model, alias_generator=to_camel, populate_by_name=True):
    """What a hook prints for Claude Code, its fields in camel case."""


class PreToolUseAnswer(Output):
    """`PreToolUse`'s decision on the call."""

    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: Literal["allow", "ask", "deny"] | None = None
    permission_decision_reason: str | None = None
    additional_context: str | None = None


class PostToolUseAnswer(Output):
    """What `PostToolUse` adds beside the call's result."""

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    additional_context: str


class Specific(Output):
    """An answer in the `hookSpecificOutput` field."""

    hook_specific_output: PreToolUseAnswer | PostToolUseAnswer


class Blocked(Output):
    """`Stop` or `SubagentStop` refusing to let the conversation end, and why."""

    decision: Literal["block"] = "block"
    reason: str


class OperatorWarning(Output):
    """A warning shown to the operator, not the agent, which lets the turn end.

    The hooks reference: `systemMessage` is a "Warning message shown to the user",
    and `Stop`'s own section neither discards nor redirects it. Anything `Stop`
    tells the agent, `reason` or `additionalContext`, keeps the turn going.
    """

    system_message: str


def failure_note(failure: Exception) -> str:
    """Say that judging failed, for the agent to pass on."""
    return f"lup's judge failed, so this wasn't judged: {failure!r}. Tell the operator."


class Payload(Model, ABC):
    """What every Claude Code hook receives on stdin, and how each answers."""

    session_id: str
    cwd: Path
    agent_id: str = ""
    """The subagent the hook fires for; absent for the session's own conversation."""

    @abstractmethod
    def answer(self, bench: Bench) -> Output | None:
        """Act on the hook, and return what to print; none to print nothing."""

    @abstractmethod
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Return what to print when judging itself failed."""


class SessionStart(Payload):
    """`SessionStart`: a session starts, resumes, or is cleared or compacted."""

    hook_event_name: Literal["SessionStart"]

    @override
    def answer(self, bench: Bench) -> Output | None:
        SessionStarted(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd
        ).apply(bench)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        return None


class Edit(Model):
    """The `Edit` tool's input."""

    file_path: Path
    old_string: str
    new_string: str
    replace_all: bool = False


class Write(Model):
    """The `Write` tool's input."""

    file_path: Path
    content: str


class PreToolUse(Payload):
    """`PreToolUse`: a tool call about to run."""

    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: JsonObject
    tool_use_id: str

    def proposal(self) -> Replacement | Overwrite | None:
        """Read a file tool's call as what it proposes to write; none for others."""
        match self.tool_name:
            case "Edit":
                edit = Edit.model_validate(self.tool_input)
                return Replacement(
                    call=self.tool_use_id,
                    tool=self.tool_name,
                    path=self.cwd / edit.file_path,
                    old=edit.old_string,
                    new=edit.new_string,
                    everywhere=edit.replace_all,
                )
            case "Write":
                write = Write.model_validate(self.tool_input)
                return Overwrite(
                    call=self.tool_use_id,
                    tool=self.tool_name,
                    path=self.cwd / write.file_path,
                    text=write.content,
                )
            case _:
                return None

    def started(self) -> CallStarted:
        """Return the event of this call starting.

        A call running a subagent (`Agent`) isn't counted: its own calls are.
        """
        return CallStarted(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            call=self.tool_use_id,
            tool=self.tool_name,
            spawns=self.tool_name in ["Agent", "Task"],
        )

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Judge a file tool's write before it lands, and count the call as running.

        A refused call never runs, so it isn't counted.
        """
        proposed = self.proposal()
        decision = (
            Decision(outcome=None)
            if proposed is None
            else before(bench, proposed, self.session_id, self.cwd)
        )
        match decision.outcome:
            case "refuse":
                answer = PreToolUseAnswer(
                    permission_decision="deny",
                    permission_decision_reason=decision.reason,
                )
                return Specific(hook_specific_output=answer)
            case None:
                self.started().apply(bench)
                return None
            case "allow" | "ask" as outcome:
                self.started().apply(bench)
                answer = PreToolUseAnswer(
                    permission_decision=outcome,
                    permission_decision_reason=decision.reason or None,
                )
                return Specific(hook_specific_output=answer)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Refuse a file tool's write; let other calls go on, told why.

        A crashing hook is a non-blocking error to Claude Code, which would let a
        write meant for review through unseen.
        """
        told = failure_note(failure)
        if self.proposal() is None:
            return Specific(
                hook_specific_output=PreToolUseAnswer(additional_context=told)
            )
        refused = PreToolUseAnswer(
            permission_decision="deny", permission_decision_reason=told
        )
        return Specific(hook_specific_output=refused)


class PostToolUse(Payload):
    """`PostToolUse` or `PostToolUseFailure`: a tool call finished, or failed."""

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    tool_name: str
    tool_use_id: str

    @override
    def answer(self, bench: Bench) -> Output | None:
        finished = CallFinished(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            call=self.tool_use_id,
        )
        reply = finished.apply(bench)
        if not reply.context:
            return None
        said = PostToolUseAnswer(
            hook_event_name=self.hook_event_name, additional_context=reply.context
        )
        return Specific(hook_specific_output=said)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        said = PostToolUseAnswer(
            hook_event_name=self.hook_event_name,
            additional_context=failure_note(failure),
        )
        return Specific(hook_specific_output=said)


class Stop(Payload):
    """`Stop`: the session's own conversation ends its turn."""

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool = False
    """Whether the turn goes on because a `Stop` hook blocked it already."""

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = TurnEnded(session=self.session_id, agent=self.agent_id, cwd=self.cwd)
        reply = ended.apply(bench)
        return Blocked(reason=reply.block) if reply.block else None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Let the turn end, and warn the operator once: the agent can't fix it."""
        warning = judge_failed(failure)
        if not first_warning(bench.services.layout, self.session_id, warning):
            return None
        return OperatorWarning(system_message=warning)


class SubagentStop(Payload):
    """`SubagentStop`: a subagent's conversation ends."""

    hook_event_name: Literal["SubagentStop"]

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = ConversationEnded(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd
        )
        reply = ended.apply(bench)
        return Blocked(reason=reply.block) if reply.block else None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        return None


type Received = Annotated[
    SessionStart | PreToolUse | PostToolUse | Stop | SubagentStop,
    Field(discriminator="hook_event_name"),
]
"""Any hook payload this adapter answers, told apart by its event's name."""


def hook(raw: str, bench: Bench) -> str:
    """Answer one Claude Code hook: its payload in, what it prints out.

    A hook must answer whatever failed, so judging's failure is answered in the
    hook's own terms.
    """
    received: Payload = TypeAdapter[Received](Received).validate_json(raw)
    try:
        output = received.answer(bench)
    except Exception as failure:
        output = received.failed(bench, failure)
    if output is None:
        return ""
    return output.model_dump_json(by_alias=True, exclude_none=True)
