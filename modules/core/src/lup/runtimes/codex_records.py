"""Codex's records of its threads, read as lup's model of a conversation (`lup.runtimes.records`).

Codex keeps a rollout for each thread in its own directory (`CODEX_HOME`, or
`~/.codex`): `sessions/YYYY/MM/DD/rollout-*.jsonl`, whose first line, a
`session_meta`, says the thread's id, the session's (the thread at the root of
its tree), the directory it ran in, and, for a subagent's, the thread that
spawned them (`parent_thread_id`). Each line is `{timestamp, type, payload}`.
What each is read as rests on what was read of its source and measured of the
rollouts lup keeps (`docs/field-notes.md`, *A thread's rollout*, *Subagents'
records*):
- **Words** are events, never the `response_item` messages that repeat them
  among injected context: `user_message` and `agent_message` where the thread's
  `history_mode` is `legacy`, else `item_completed` with a `UserMessage` or
  `AgentMessage` item. A user's words in a subagent's thread are their parent's.
- **Calls** are `response_item`s: `function_call`, its `arguments` JSON in a
  string, and `custom_tool_call`, its `input` the text the tool takes, each by
  its `call_id`, named as Codex's hooks name them: a server's tool
  `mcp__<server>__<tool>`, any other namespace joined to the name with nothing
  between. Their results are the `*_output` naming the same id.
- **Calls a code-mode cell makes** come only as `item_completed` events while
  the `exec` cell that made them is open, each item a call and its result at
  once (`McpToolCall`, `CommandExecution`, `FileChange`, `WebSearch`,
  `DynamicToolCall`). Outside a cell those items repeat a call already read.
- **A turn's end** is `task_complete`, or `turn_aborted` where it was cut
  short; a compaction a `compacted` line; a name `thread_name_updated`.
"""

import json
from pathlib import Path
from typing import override
lazy from collections.abc import Iterator

from pydantic import AwareDatetime, Field, JsonValue, ValidationError

from lup.runtimes.records import (
    Called,
    Compacted,
    Counted,
    Ended,
    Place,
    Planned,
    Read,
    Reading,
    Record,
    Records,
    Returned,
    Said,
    Speaker,
    Stepped,
    Task,
    Titled,
    head,
    lined,
)
from lup.types import JsonObject, Model


class Text(Model):
    """A part of a message, a call's output, or an item's content: its text, where it's text."""

    type: str
    text: str | None = None


class McpResult(Model):
    """What a server's tool returned, as an `McpToolCall` item says."""

    content: list[Text] = []
    is_error: bool | None = Field(default=None, validation_alias="isError")


class Item(Model):
    """An item a `item_completed` event carries: words, or a call a code-mode cell made, with its result."""

    type: str
    id: str | None = None
    content: list[Text] | None = None
    server: str | None = None
    tool: str | None = None
    arguments: JsonValue = None
    result: McpResult | None = None
    error: JsonObject | None = None
    command: JsonValue = None
    aggregated_output: str | None = None
    exit_code: int | None = None
    changes: JsonValue = None
    stdout: str | None = None
    stderr: str | None = None
    query: str | None = None
    results: JsonValue = None
    content_items: JsonValue = None
    success: bool | None = None


class TokenUsage(Model):
    """What a request took, as a `token_count` event counts it."""

    total_tokens: int = 0
    reasoning_output_tokens: int = 0


class TokenInfo(Model):
    """What a `token_count` event says of the latest request: what it took, of how much the model holds."""

    last_token_usage: TokenUsage | None = None
    model_context_window: int | None = None


class Step(Model):
    """One step of the plan `update_plan` gives whole."""

    step: str
    status: str


class Plan(Model):
    """What an `update_plan` call is given: the whole plan."""

    plan: list[Step]


class Payload(Model):
    """What a line carries, every field lup reads of each kind, each read where it's there."""

    type: str | None = None
    id: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    parent_thread_id: str | None = None
    history_mode: str | None = None
    message: str | None = None
    item: Item | None = None
    name: str | None = None
    namespace: str | None = None
    arguments: str | None = None
    input: str | None = None
    call_id: str | None = None
    output: str | list[Text] | None = None
    thread_name: str | None = None
    info: TokenInfo | None = None
    model: str | None = None


class Line(Model):
    """One line of a rollout: when, what kind of line, and what it carries."""

    timestamp: AwareDatetime | None = None
    type: str
    payload: Payload = Payload()


class Carried(Model):
    """What a read of a rollout carries to the next: the code-mode cell still open, the calls read while it was, whose items repeat them, and the model the thread runs on."""

    cell: str | None = None
    direct: list[str] = []
    model: str | None = None
    """The model the thread's latest turn ran on, which its context is counted
    against."""


def parsed[M: Model](kind: type[M], text: bytes) -> M | None:
    """Read `text` as a `kind`; none where it isn't one, as a line half written, or a room's own, may not be."""
    try:
        return kind.model_validate_json(text)
    except ValidationError:
        return None


def joined(parts: list[Text]) -> str:
    """Return parts as text: their text in order, each other part named where it stood."""
    return "\n".join(
        each.text if each.text is not None else f"[{each.type}]" for each in parts
    )


def given(arguments: str) -> JsonValue:
    """Return a call's arguments as the JSON they're written in, or as written where they aren't JSON."""
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def named(name: str, namespace: str | None) -> str:
    """Return a tool's name as Codex's hooks name it: a server's `mcp__<server>__<tool>`, any other namespace's joined to its name with nothing between, as Codex flattens one."""
    match namespace:
        case None | "" | "functions":
            return name
        case str() as space if space.startswith("mcp__"):
            return f"{space}__{name}"
        case str() as space:
            return f"{space}{name}"


class CodexRecords(Records):
    """Codex's records: a rollout for each thread, a subagent's beside their session's."""

    own: Path = Path("~/.codex")

    @override
    def beside(self, record: Record) -> list[Path]:
        return []

    @override
    def found(self, home: Path, under: list[Path] | None = None) -> list[Record]:
        sessions = home / "sessions"
        paths = (
            sorted(sessions.glob("*/*/*/rollout-*.jsonl")) if sessions.is_dir() else []
        )
        records = [
            record for path in paths if (record := self.recorded(path)) is not None
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
        """Return what the rollout at `path` is, read from its first line; none where that isn't a `session_meta` saying its thread and directory."""
        meta = self.meta(path)
        if meta is None or meta.id is None or meta.cwd is None:
            return None
        session = meta.session_id or meta.id
        subagent = meta.id != session or meta.parent_thread_id is not None
        return Record(
            path=path,
            session=session,
            conversation=meta.id if subagent else None,
            spawner=meta.parent_thread_id if meta.parent_thread_id != session else None,
            directory=Path(meta.cwd),
        )

    def meta(self, path: Path) -> Payload | None:
        """Return what the rollout at `path` says of its thread on its first line; none where its first line isn't a `session_meta`."""
        try:
            first = next(head(path), None)
        except OSError:
            return None
        line = parsed(Line, first) if first is not None else None
        return (
            line.payload if line is not None and line.type == "session_meta" else None
        )

    @override
    def read(self, record: Record, since: Reading | None = None) -> Read:
        read = lined(record.path, since, longest=self.longest)
        meta = self.meta(record.path) or Payload()
        legacy = meta.history_mode is None or meta.history_mode == "legacy"
        heard: Speaker = (
            "conversation" if record.conversation is not None else "operator"
        )
        carried = (
            Carried.model_validate(since.carried)
            if since is not None and not read.again
            else Carried()
        )

        def made() -> Iterator[Stepped]:
            """Yield each step the rollout's new lines hold, keeping which code-mode cell is open."""
            nonlocal carried
            for each in read.lines:
                line = parsed(Line, each.text) if each.text is not None else None
                if line is None:
                    continue
                yield from self.stepped(
                    line, each.start, heard, carried=carried, legacy=legacy
                )
                carried = self.carried(line, carried)

        steps = list(made())
        reading = Reading(
            offset=read.end, begins=read.begins, carried=carried.model_dump(mode="json")
        )
        return Read(steps=steps, reading=reading, again=read.again)

    def stepped(
        self, line: Line, start: int, heard: Speaker, *, carried: Carried, legacy: bool
    ) -> list[Stepped]:
        """Return the steps one line holds, placed at the byte `start` its line starts at and its index among them, read with what earlier lines carried to it."""
        steps = list(
            self.held(line, Place(line=start), heard, carried=carried, legacy=legacy)
        )
        return [
            step.model_copy(update={"place": Place(line=start, index=index)})
            for index, step in enumerate(steps)
        ]

    def carried(self, line: Line, carried: Carried) -> Carried:
        """Return what's carried past `line`: a code-mode cell opened or closed, a call read while one is open."""
        payload = line.payload
        match line.type, payload.type:
            case "response_item", "custom_tool_call" if (
                payload.name == "exec" and payload.call_id
            ):
                return Carried(cell=payload.call_id, model=carried.model)
            case (
                "response_item",
                "function_call_output" | "custom_tool_call_output",
            ) if payload.call_id == carried.cell:
                return Carried(model=carried.model)
            case "response_item", "function_call" | "custom_tool_call" if (
                carried.cell is not None and payload.call_id
            ):
                return carried.model_copy(
                    update={"direct": [*carried.direct, payload.call_id]}
                )
            case "event_msg", "task_complete" | "turn_aborted":
                return Carried(model=carried.model)
            case "turn_context", _ if payload.model:
                return carried.model_copy(update={"model": payload.model})
            case _:
                return carried

    def held(
        self, line: Line, here: Place, heard: Speaker, *, carried: Carried, legacy: bool
    ) -> Iterator[Stepped]:
        """Yield each step `line` holds, each at `here` until it's given its index."""
        payload = line.payload
        at = line.timestamp
        match line.type, payload.type, payload.item:
            case "event_msg", "user_message", _ if (
                legacy and payload.message is not None
            ):
                yield Said(place=here, at=at, by=heard, text=payload.message)
            case "event_msg", "agent_message", _ if (
                legacy and payload.message is not None
            ):
                yield Said(place=here, at=at, by="agent", text=payload.message)
            case "event_msg", "item_completed", Item(
                type="UserMessage", content=list() as parts
            ):
                if not legacy:
                    yield Said(place=here, at=at, by=heard, text=joined(parts))
            case "event_msg", "item_completed", Item(
                type="AgentMessage", content=list() as parts
            ):
                if not legacy:
                    yield Said(place=here, at=at, by="agent", text=joined(parts))
            case "event_msg", "item_completed", Item(id=str() as call) as item:
                if carried.cell is not None and call not in carried.direct:
                    yield from self.nested(item, call, carried.cell, here, at)
            case "response_item", "function_call", _ if (
                payload.name and payload.call_id
            ):
                yield Called(
                    place=here,
                    at=at,
                    call=payload.call_id,
                    tool=named(payload.name, payload.namespace),
                    given=given(payload.arguments or ""),
                    within=carried.cell,
                )
                yield from self.plan(payload.name, payload.arguments, here, at)
            case "response_item", "custom_tool_call", _ if (
                payload.name and payload.call_id
            ):
                yield Called(
                    place=here,
                    at=at,
                    call=payload.call_id,
                    tool=named(payload.name, payload.namespace),
                    given=payload.input,
                    within=carried.cell if payload.name != "exec" else None,
                )
            case (
                "response_item",
                "function_call_output" | "custom_tool_call_output",
                _,
            ) if payload.call_id:
                yield Returned(
                    place=here,
                    at=at,
                    call=payload.call_id,
                    output=payload.output
                    if isinstance(payload.output, str)
                    else joined(payload.output or []),
                )
            case "event_msg", "token_count", _ if (
                payload.info is not None and payload.info.last_token_usage is not None
            ):
                usage = payload.info.last_token_usage
                yield Counted(
                    place=here,
                    at=at,
                    used=max(0, usage.total_tokens - usage.reasoning_output_tokens),
                    window=payload.info.model_context_window or None,
                    model=carried.model,
                )
            case "event_msg", "task_complete", _:
                yield Ended(place=here, at=at)
            case "event_msg", "turn_aborted", _:
                yield Ended(place=here, at=at, interrupted=True)
            case "compacted", _, _:
                yield Compacted(place=here, at=at)
            case "event_msg", "thread_name_updated", _ if payload.thread_name:
                yield Titled(place=here, at=at, title=payload.thread_name, how="named")
            case _:
                return

    def plan(
        self, name: str, arguments: str | None, here: Place, at: AwareDatetime | None
    ) -> Iterator[Stepped]:
        """Yield the plan as it stands where `name` is `update_plan`, which gives it whole; nothing for any other call, or one given what the tool doesn't take."""
        if name != "update_plan" or arguments is None:
            return
        plan = parsed(Plan, arguments.encode())
        if plan is None:
            return
        yield Planned(
            place=here,
            at=at,
            tasks=[
                Task(id=str(number), subject=each.step, status=each.status)
                for number, each in enumerate(plan.plan, start=1)
            ],
        )

    def nested(
        self, item: Item, call: str, cell: str, here: Place, at: AwareDatetime | None
    ) -> Iterator[Stepped]:
        """Yield the call a code-mode cell made, and its result, which its item says at once; nothing for an item that's no call."""
        match item:
            case Item(type="McpToolCall", server=str() as server, tool=str() as tool):
                failed = item.error is not None or bool(
                    item.result and item.result.is_error
                )
                said = (
                    joined(item.result.content)
                    if item.result
                    else json.dumps(item.error)
                )
                yield Called(
                    place=here,
                    at=at,
                    call=call,
                    tool=f"mcp__{server}__{tool}",
                    given=item.arguments,
                    within=cell,
                )
                yield Returned(place=here, at=at, call=call, output=said, failed=failed)
            case Item(type="CommandExecution"):
                yield Called(
                    place=here,
                    at=at,
                    call=call,
                    tool="exec_command",
                    given=item.command,
                    within=cell,
                )
                yield Returned(
                    place=here,
                    at=at,
                    call=call,
                    output=item.aggregated_output or "",
                    failed=bool(item.exit_code),
                )
            case Item(type="FileChange"):
                yield Called(
                    place=here,
                    at=at,
                    call=call,
                    tool="apply_patch",
                    given=item.changes,
                    within=cell,
                )
                yield Returned(
                    place=here,
                    at=at,
                    call=call,
                    output="\n".join(
                        each for each in [item.stdout, item.stderr] if each
                    ),
                )
            case Item(type="WebSearch"):
                yield Called(
                    place=here,
                    at=at,
                    call=call,
                    tool="web_search",
                    given=item.query,
                    within=cell,
                )
                yield Returned(
                    place=here, at=at, call=call, output=json.dumps(item.results)
                )
            case Item(type="DynamicToolCall", tool=str() as tool):
                yield Called(
                    place=here,
                    at=at,
                    call=call,
                    tool=tool,
                    given=item.arguments,
                    within=cell,
                )
                yield Returned(
                    place=here,
                    at=at,
                    call=call,
                    output=json.dumps(item.content_items),
                    failed=None if item.success is None else not item.success,
                )
            case _:
                return
