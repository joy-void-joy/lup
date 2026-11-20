"""Claude Code's records of its conversations, read as lup's model of one (`lup.runtimes.records`).

Claude Code keeps them in its own directory (`CLAUDE_CONFIG_DIR`, or `~/.claude`):
`projects/<folder>/<session>.jsonl` for a session, its folder named for the
directory it ran in, and `projects/<folder>/<session>/subagents/agent-<id>.jsonl`
for each subagent, with `agent-<id>.meta.json` beside it naming the call that
spawned them (`toolUseId`) and the subagent who did, where one did
(`parentAgentId`). A command's output too long for the record is saved whole in
`<session>/tool-results/`. What each line is read as rests on what was measured
of them (`docs/field-notes.md`, *Where each runtime keeps its sessions' records*
and what follows it, *A fork of a session*):
- **Who said what** is a `user` line's `origin`: `human` the operator, typed or
  queued; `channel` lup's push; `peer` and `coordinator` another conversation's
  message; any other, such as `task-notification`, Claude Code's own. A line
  with none is older or written without a terminal: a turn lup wrote, held
  (`promptSource` `sdk`); Claude Code's own context (`isMeta`), command tags
  (text opening with `<`), an interruption (text in parts) or a compaction's
  summary (`isCompactSummary`); a subagent's brief, the first words of their
  record; else, in records from before `origin`, the operator's.
- **Words sent while the agent works** are an `attachment` of `queued_command`,
  its `prompt` the words, its `origin` whose they are.
- **What lup told** at a hook is an `attachment` of `hook_additional_context`.
- **The agent's words** are an `assistant` line's text, its calls its
  `tool_use` parts; a reply Claude Code made up on an error (`<synthetic>`) is
  its own.
- **A call's result** is a `tool_result` part of a later `user` line; where the
  output was too long for the record, its line's `persistedOutputPath` names
  the file holding it whole, read from the session's own folder alone.
- **A turn's end** is a `system` line of `turn_duration`; a compaction one of
  `compact_boundary`.
- **A fork's copied history** keeps the parent's `uuid`s, which are steps'
  keys; a subagent forked from the session's own conversation names it
  (`fork-context-ref`) rather than copying it.
"""

import functools
from pathlib import Path
from typing import override
lazy from collections.abc import Iterator

from pydantic import AliasGenerator, AwareDatetime, Field, JsonValue, ValidationError
from pydantic.alias_generators import to_camel

from lup.runtimes.records import (
    Called,
    Compacted,
    Continued,
    Counted,
    Ended,
    Forked,
    Place,
    Planned,
    Read,
    Reading,
    Record,
    Records,
    Refused,
    Returned,
    Said,
    Speaker,
    Stepped,
    Task,
    Titled,
    head,
    lined,
    opened,
)
from lup.types import Model


class Camel(Model, alias_generator=AliasGenerator(validation_alias=to_camel)):
    """A part of a line Claude Code writes in camel case, read by its fields' names in snake case."""


class Origin(Model):
    """Where a prompt came from, as Claude Code marks it."""

    kind: str | None = None


class Content(Model):
    """A part of a call's result: text, an image, or a reference to a tool found."""

    type: str
    text: str | None = None
    tool_name: str | None = None


class Part(Model):
    """A part of a message: text, a call, a call's result, or anything else, such as the agent's thinking, which is read as nothing."""

    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: JsonValue = None
    tool_use_id: str | None = None
    content: str | list[Content] | None = None
    is_error: bool | None = None


class Usage(Model):
    """What a request took of the model's context, in its three parts."""

    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class Message(Model):
    """A message a line carries: its parts, or its text whole, and, where the agent's, the model that wrote it and what the request took."""

    content: str | list[Part] = []
    id: str | None = None
    model: str | None = None
    usage: Usage | None = None


class Attachment(Camel):
    """What an `attachment` line carries: words queued for the agent, or a hook's context."""

    type: str
    prompt: str | None = None
    command_mode: str | None = None
    origin: Origin | None = None
    content: list[str] | str | None = None
    decision: str | None = None
    tool_use: str | None = Field(default=None, validation_alias="toolUseID")


class Created(Model):
    """The task a `TaskCreate` call made, as its result says: its id in the list."""

    id: str


class Persisted(Camel):
    """What a call's result line says of its output beside the result, where it's an object: where the output was saved whole, or the task it made."""

    persisted_output_path: str | None = None
    task: Created | None = None


class Creating(Camel):
    """What a `TaskCreate` call is given."""

    subject: str
    active_form: str | None = None


class Updating(Camel):
    """What a `TaskUpdate` call is given."""

    task_id: str
    status: str | None = None
    subject: str | None = None
    active_form: str | None = None


class Todo(Camel):
    """One of the list a `TodoWrite` call gives whole."""

    content: str
    status: str
    active_form: str | None = None


class Writing(Model):
    """What a `TodoWrite` call is given: the whole list."""

    todos: list[Todo]


class Pending(Model):
    """A task asked for, waiting for its call's result to say its id."""

    call: str
    task: Task


class Carried(Model):
    """What a read of a record carries to the next: the agent's message whose usage was counted, and their task list, the tasks asked for among it."""

    message: str | None = None
    tasks: list[Task] = []
    pending: list[Pending] = []


class Line(Camel):
    """One line of a Claude Code record, every field it may carry that lup reads, each read where it's there."""

    type: str
    uuid: str | None = None
    timestamp: AwareDatetime | None = None
    session_id: str | None = None
    agent_id: str | None = None
    cwd: str | None = None
    message: Message | None = None
    origin: Origin | None = None
    prompt_source: str | None = None
    is_meta: bool = False
    is_compact_summary: bool = False
    is_sidechain: bool = False
    requested_model: str | None = None
    tool_use_result: Persisted | list[JsonValue] | str | None = None
    attachment: Attachment | None = None
    subtype: str | None = None
    custom_title: str | None = None
    agent_name: str | None = None
    ai_title: str | None = None
    parent_session_id: str | None = None
    parent_last_uuid: str | None = None
    continued_in_session_id: str | None = None


class Meta(Camel):
    """What Claude Code writes beside a subagent's record of their spawn: the call that spawned them, and the subagent who did, where one did."""

    tool_use_id: str | None = None
    parent_agent_id: str | None = None


def parsed[M: Model](kind: type[M], text: bytes) -> M | None:
    """Read `text` as a `kind`; none where it isn't one, as a line half written, or a room's own, may not be."""
    try:
        return kind.model_validate_json(text)
    except ValidationError:
        return None


def output(content: str | list[Content] | None) -> str:
    """Return a call's result as text: its text parts in order, each other part named where it stood."""
    match content:
        case str():
            return content
        case None:
            return ""
        case list():
            return "\n".join(
                each.text
                if each.type == "text" and each.text is not None
                else f"[{each.type}: {each.tool_name}]"
                if each.tool_name is not None
                else f"[{each.type}]"
                for each in content
            )


class ClaudeRecords(Records):
    """Claude Code's records: a session's and each of its subagents', in a folder per directory they ran in."""

    own: Path = Path("~/.claude")

    @override
    def beside(self, record: Record) -> list[Path]:
        if record.conversation is not None:
            return [record.path.with_suffix(".meta.json")]
        saved = record.path.with_suffix("") / "tool-results"
        if not saved.is_dir() or saved.is_symlink():
            return []
        return sorted(
            each for each in saved.iterdir() if each.is_file() and not each.is_symlink()
        )

    @override
    def found(self, home: Path, under: list[Path] | None = None) -> list[Record]:
        projects = home / "projects"
        folders = (
            [
                each
                for each in projects.iterdir()
                if each.is_dir() and not each.is_symlink()
            ]
            if projects.is_dir()
            else []
        )
        records = [
            record
            for folder in folders
            for path in [
                *sorted(folder.glob("*.jsonl")),
                *sorted(folder.glob("*/subagents/agent-*.jsonl")),
            ]
            if (record := self.recorded(path)) is not None
        ]
        return [
            record
            for record in records
            if under is None
            or (
                record.directory is not None
                and any(record.directory.is_relative_to(each) for each in under)
            )
        ]

    def recorded(self, path: Path) -> Record | None:
        """Return what the record at `path` is, read from its first lines and, for a subagent's, the spawn's record beside it; none where it says neither its session nor its directory."""
        try:
            first = next(
                (
                    line
                    for text in head(path)
                    if (line := parsed(Line, text)) is not None
                    and line.session_id is not None
                    and line.cwd is not None
                ),
                None,
            )
        except OSError:
            return None
        if first is None or first.session_id is None or first.cwd is None:
            return None
        if path.parent.name != "subagents":
            return Record(
                path=path, session=first.session_id, directory=Path(first.cwd)
            )
        meta = self.spawn(path.with_suffix(".meta.json"))
        return Record(
            path=path,
            session=first.session_id,
            conversation=first.agent_id,
            spawner=meta.parent_agent_id,
            call=meta.tool_use_id,
            directory=Path(first.cwd),
        )

    def spawn(self, path: Path) -> Meta:
        """Return what Claude Code wrote of a subagent's spawn at `path`; nothing said where it wrote nothing readable."""
        try:
            with opened(path) as meta:
                return parsed(Meta, meta.read()) or Meta()
        except OSError:
            return Meta()

    @override
    def read(self, record: Record, since: Reading | None = None) -> Read:
        read = lined(record.path, since, longest=self.longest)
        subagent = record.conversation is not None
        folder = record.path.parent.parent if subagent else record.path.with_suffix("")
        carried = (
            Carried.model_validate(since.carried)
            if since is not None and not read.again
            else Carried()
        )

        def made() -> Iterator[Stepped]:
            """Yield each step the record's new lines hold, keeping what's carried from line to line."""
            nonlocal carried
            for each in read.lines:
                line = parsed(Line, each.text) if each.text is not None else None
                if line is None or line.is_sidechain != subagent:
                    continue
                after = self.carried(line, carried)
                yield from self.stepped(
                    line, each.start, folder, before=carried, after=after
                )
                carried = after

        steps = list(made())
        reading = Reading(
            offset=read.end, begins=read.begins, carried=carried.model_dump(mode="json")
        )
        return Read(steps=steps, reading=reading, again=read.again)

    def stepped(
        self, line: Line, start: int, folder: Path, *, before: Carried, after: Carried
    ) -> list[Stepped]:
        """Return the steps one line holds, each placed at the byte `start` its line starts at and its index among them: what it says, then the context counted and the task list as it changed, where they did.

        `folder` is the session's own, where its saved outputs are; `before` and
        `after` are what's carried to the line and past it.
        """
        here = Place(line=start)
        counted = [
            Counted(
                place=here,
                at=line.timestamp,
                key=line.uuid,
                used=usage.input_tokens
                + usage.cache_creation_input_tokens
                + usage.cache_read_input_tokens,
                model=line.requested_model or line.message.model,
            )
            for usage in [line.message.usage if line.message else None]
            if usage is not None
            and line.message is not None
            and line.message.model != "<synthetic>"
            and after.message != before.message
        ]
        planned = [
            Planned(place=here, at=line.timestamp, key=line.uuid, tasks=after.tasks)
            for _ in [after.tasks]
            if after.tasks != before.tasks
        ]
        steps = [*self.held(line, here, folder), *counted, *planned]
        return [
            step.model_copy(update={"place": Place(line=start, index=index)})
            for index, step in enumerate(steps)
        ]

    def carried(self, line: Line, carried: Carried) -> Carried:
        """Return what's carried past `line`: the agent's message counted, and the task list as its calls and their results change it."""
        message = (
            line.message.id
            if line.type == "assistant" and line.message is not None and line.message.id
            else carried.message
        )
        changed = carried.model_copy(update={"message": message})
        match line:
            case Line(type="assistant", message=Message(content=list() as parts)):
                calls = [each for each in parts if each.type == "tool_use"]
                return functools.reduce(self.planned, calls, changed)
            case Line(
                type="user",
                tool_use_result=Persisted(task=Created(id=task)),
                message=Message(content=list() as parts),
            ):
                answered = [
                    each.tool_use_id for each in parts if each.tool_use_id is not None
                ]
                made = [
                    each.task.model_copy(update={"id": task})
                    for each in changed.pending
                    if each.call in answered
                ]
                return changed.model_copy(
                    update={
                        "tasks": [*changed.tasks, *made],
                        "pending": [
                            each
                            for each in changed.pending
                            if each.call not in answered
                        ],
                    }
                )
            case _:
                return changed

    def planned(self, carried: Carried, call: Part) -> Carried:
        """Return the task list once `call` changed it: a task asked for, one changed or deleted, or the list written whole; as it was for any other call, or one given what the tool doesn't take."""
        try:
            match call:
                case Part(name="TaskCreate", id=str() as id):
                    asked = Creating.model_validate(call.input)
                    task = Task(
                        id="",
                        subject=asked.subject,
                        status="pending",
                        active=asked.active_form,
                    )
                    return carried.model_copy(
                        update={
                            "pending": [*carried.pending, Pending(call=id, task=task)]
                        }
                    )
                case Part(name="TaskUpdate"):
                    update = Updating.model_validate(call.input)
                    tasks = [
                        each
                        if each.id != update.task_id
                        else each.model_copy(
                            update={
                                "status": update.status or each.status,
                                "subject": update.subject or each.subject,
                                "active": update.active_form or each.active,
                            }
                        )
                        for each in carried.tasks
                        if each.id != update.task_id or update.status != "deleted"
                    ]
                    return carried.model_copy(update={"tasks": tasks})
                case Part(name="TodoWrite"):
                    written = Writing.model_validate(call.input)
                    return carried.model_copy(
                        update={
                            "tasks": [
                                Task(
                                    id=str(number),
                                    subject=each.content,
                                    status=each.status,
                                    active=each.active_form,
                                )
                                for number, each in enumerate(written.todos, start=1)
                            ]
                        }
                    )
                case _:
                    return carried
        except ValidationError:
            return carried

    def held(self, line: Line, here: Place, folder: Path) -> Iterator[Stepped]:
        """Yield each step `line` holds, each at `here` until it's given its index."""
        match line:
            case Line(type="user", message=Message(content=list() as parts)) if any(
                each.type == "tool_result" for each in parts
            ):
                whole = self.saved(line, folder) if len(parts) == 1 else None
                yield from (
                    Returned(
                        place=here,
                        at=line.timestamp,
                        key=line.uuid,
                        call=each.tool_use_id,
                        output=whole if whole is not None else output(each.content),
                        failed=each.is_error,
                    )
                    for each in parts
                    if each.type == "tool_result" and each.tool_use_id is not None
                )
            case Line(type="user", message=Message(content=content)):
                yield Said(
                    place=here,
                    at=line.timestamp,
                    key=line.uuid,
                    by=self.speaker(line),
                    text=content if isinstance(content, str) else self.words(content),
                    queued=line.prompt_source == "queued",
                )
            case Line(
                type="assistant", message=Message(content=list() as parts, model=model)
            ):
                yield from (
                    step
                    for each in parts
                    if (step := self.assistant(line, each, model, here)) is not None
                )
            case Line(
                type="attachment",
                attachment=Attachment(
                    type="queued_command", command_mode="prompt", prompt=str() as prompt
                ) as attachment,
            ):
                yield Said(
                    place=here,
                    at=line.timestamp,
                    key=line.uuid,
                    by=self.origin(attachment.origin, unmarked="operator"),
                    text=prompt,
                    queued=True,
                )
            case Line(
                type="attachment",
                attachment=Attachment(
                    type="hook_additional_context", content=str() as text
                ),
            ):
                yield Said(
                    place=here, at=line.timestamp, key=line.uuid, by="lup", text=text
                )
            case Line(
                type="attachment",
                attachment=Attachment(
                    type="hook_additional_context", content=list() as texts
                ),
            ):
                yield Said(
                    place=here,
                    at=line.timestamp,
                    key=line.uuid,
                    by="lup",
                    text="\n".join(texts),
                )
            case Line(
                type="attachment",
                attachment=Attachment(
                    type="hook_permission_decision",
                    decision="deny",
                    tool_use=str() as call,
                ),
            ):
                yield Refused(place=here, at=line.timestamp, key=line.uuid, call=call)
            case Line(type="system", subtype="turn_duration"):
                yield Ended(place=here, at=line.timestamp, key=line.uuid)
            case Line(type="system", subtype="compact_boundary"):
                yield Compacted(place=here, at=line.timestamp, key=line.uuid)
            case Line(type="custom-title", custom_title=str() as title):
                yield Titled(place=here, title=title, how="named")
            case Line(type="agent-name", agent_name=str() as title):
                yield Titled(place=here, title=title, how="agent")
            case Line(type="ai-title", ai_title=str() as title):
                yield Titled(place=here, title=title, how="guessed")
            case Line(type="fork-context-ref", parent_session_id=str() as session):
                yield Forked(place=here, session=session, through=line.parent_last_uuid)
            case Line(type="continued-in", continued_in_session_id=str() as session):
                yield Continued(place=here, at=line.timestamp, session=session)
            case _:
                return

    def assistant(
        self, line: Line, part: Part, model: str | None, here: Place
    ) -> Stepped | None:
        """Return the step one part of the agent's message is: their words, or a call; none for their thinking, or anything else."""
        match part:
            case Part(type="text", text=str() as text):
                return Said(
                    place=here,
                    at=line.timestamp,
                    key=line.uuid,
                    by="runtime" if model == "<synthetic>" else "agent",
                    text=text,
                )
            case Part(type="tool_use", id=str() as call, name=str() as tool):
                return Called(
                    place=here,
                    at=line.timestamp,
                    key=line.uuid,
                    call=call,
                    tool=tool,
                    given=part.input,
                )
            case _:
                return None

    def speaker(self, line: Line) -> Speaker:
        """Say who said what a `user` line holds, from its `origin`, else from what it is."""
        if line.is_compact_summary:
            return "runtime"
        if line.origin is not None:
            return self.origin(line.origin, unmarked="runtime")
        if line.is_meta:
            return "runtime"
        if line.prompt_source == "sdk":
            return "lup"
        if line.is_sidechain:
            return "conversation"
        match line.message:
            case Message(content=str() as text) if not text.startswith("<"):
                return "operator"
            case _:
                return "runtime"

    def origin(self, origin: Origin | None, unmarked: Speaker) -> Speaker:
        """Say whose words a prompt's `origin` marks as: `unmarked`'s where it marks none."""
        match origin:
            case Origin(kind="human"):
                return "operator"
            case Origin(kind="channel"):
                return "lup"
            case Origin(kind="peer" | "coordinator"):
                return "conversation"
            case Origin(kind=str()):
                return "runtime"
            case _:
                return unmarked

    def words(self, parts: list[Part]) -> str:
        """Return a message's parts as text: its text in order, each other part named where it stood."""
        return output([Content(type=each.type, text=each.text) for each in parts])

    def saved(self, line: Line, folder: Path) -> str | None:
        """Return a call's output whole from the file Claude Code saved it in, where its line names one: by its name, in the session's own `tool-results`, never elsewhere; none where there's none to read."""
        match line.tool_use_result:
            case Persisted(persisted_output_path=str() as saved):
                path = folder / "tool-results" / Path(saved).name
            case _:
                return None
        try:
            with opened(path) as whole:
                return whole.read().decode(errors="replace")
        except OSError:
            return None
