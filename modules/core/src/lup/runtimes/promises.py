"""The runtimes' promises: what whoever reads a conversation from its runtime's record can count on, the dashboard's buffer and transcripts among them.

Each record here is written as its runtime writes one, line by line, with only
the fields its reader reads (`docs/field-notes.md`, *Where each runtime keeps its
sessions' records*).
"""

import io
import json
import tempfile
from pathlib import Path
lazy from collections.abc import Iterator

lazy from pydantic import JsonValue

import lup
from lup import Model, Part
from lup.runtimes import (
    Called,
    ClaudeRecords,
    CodexRecords,
    Counted,
    Planned,
    Read,
    Record,
    Records,
    Refused,
    Returned,
    Said,
    copied,
)
from lup.testing import Testing

SESSION = "0b0c5f0e-1d1e-4c5a-9f31-6a0c3b2d9e11"
"""A session's id, as a runtime names one."""


def lined(*lines: JsonValue) -> bytes:
    """Return a record holding `lines`, each a line of JSON."""
    return b"".join(json.dumps(each).encode() + b"\n" for each in lines)


def claude(**fields: JsonValue) -> JsonValue:
    """Return a line of a Claude Code session's record, its session and directory said."""
    return {
        "sessionId": SESSION,
        "cwd": "/work",
        "timestamp": "2026-11-19T20:00:00Z",
        **fields,
    }


def typed(text: str, uuid: str) -> JsonValue:
    """Return the line of a Claude Code record holding words the operator typed."""
    return claude(
        type="user",
        uuid=uuid,
        origin={"kind": "human"},
        promptSource="typed",
        message={"role": "user", "content": text},
    )


def answered(text: str, call: str, uuid: str) -> JsonValue:
    """Return the line of a Claude Code record holding the agent's words, then a call."""
    return claude(
        type="assistant",
        uuid=uuid,
        message={
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [
                {"type": "thinking", "thinking": "…"},
                {"type": "text", "text": text},
                {
                    "type": "tool_use",
                    "id": call,
                    "name": "mcp__lup__ask",
                    "input": {"q": text},
                },
            ],
        },
    )


def returned(call: str, output: str, uuid: str, result: JsonValue = None) -> JsonValue:
    """Return the line of a Claude Code record holding what a call returned, and what Claude Code says of the result beside it (`toolUseResult`), where given."""
    return claude(
        type="user",
        uuid=uuid,
        toolUseResult=result,
        message={
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call, "content": output}
            ],
        },
    )


CLAUDE_LINES: list[JsonValue] = [
    {
        "type": "permission-mode",
        "permissionMode": "bypassPermissions",
        "sessionId": SESSION,
    },
    typed("the first words", "u1"),
    answered("an answer", "toolu_1", "a1"),
    returned("toolu_1", "what it returned", "r1"),
    claude(type="system", subtype="turn_duration", uuid="s1", durationMs=10),
    {"type": "custom-title", "customTitle": "a name", "sessionId": SESSION},
    typed("more words", "u2"),
    answered("another answer", "toolu_2", "a2"),
    returned("toolu_2", "more it returned", "r2"),
]
"""A Claude Code session's record, line by line."""


def rollout(kind: str, **payload: JsonValue) -> JsonValue:
    """Return a line of a Codex rollout."""
    return {"timestamp": "2026-11-19T20:00:00.000Z", "type": kind, "payload": payload}


def meta(thread: str = SESSION, mode: str = "paginated") -> JsonValue:
    """Return a rollout's first line, saying its thread and where it ran."""
    return rollout(
        "session_meta", id=thread, session_id=SESSION, cwd="/work", history_mode=mode
    )


def said(kind: str, text: str) -> JsonValue:
    """Return a rollout's line holding words, as an item completed."""
    return rollout(
        "event_msg",
        type="item_completed",
        item={"type": kind, "id": text, "content": [{"type": "text", "text": text}]},
    )


def mcp(call: str, tool: str, *, failed: bool = False) -> JsonValue:
    """Return a rollout's line holding a call to a server's tool, and its result, as an item completed: one that failed, where `failed` says."""
    return rollout(
        "event_msg",
        type="item_completed",
        item={
            "type": "McpToolCall",
            "id": call,
            "server": "lup",
            "tool": tool,
            "status": "completed",
            "arguments": {"text": tool},
            "result": {
                "content": [{"type": "text", "text": f"{tool} done"}],
                "isError": failed,
            },
        },
    )


CODEX_LINES: list[JsonValue] = [
    meta(),
    said("UserMessage", "the first words"),
    rollout(
        "response_item",
        type="function_call",
        namespace="mcp__lup",
        name="rename",
        arguments=json.dumps({"name": "x"}),
        call_id="call_direct",
    ),
    mcp("call_direct", "rename"),
    rollout(
        "response_item",
        type="function_call_output",
        call_id="call_direct",
        output="named",
    ),
    rollout(
        "response_item",
        type="custom_tool_call",
        name="exec",
        input="await tools.stop()",
        call_id="cell_1",
    ),
    mcp("call_in_cell", "stop", failed=True),
    rollout(
        "response_item",
        type="custom_tool_call_output",
        call_id="cell_1",
        output=[{"type": "input_text", "text": "cell done"}],
    ),
    said("AgentMessage", "an answer"),
    rollout("event_msg", type="task_complete", turn_id="t1"),
]
"""A Codex thread's rollout, line by line: a direct call to a server's tool, whose item repeats it, then a code-mode cell calling one."""


class Cuts(Model):
    """Where a record is cut as it grows: each a byte, in any order, at its start where it's below, at its end where it's past."""

    at: list[int]


def grown(records: Records, record: Record, whole: bytes, cuts: Cuts) -> Read:
    """Write `whole` to `record`'s path a cut at a time, reading what each added from where the last read stopped, and return every step read, in order, and where the last read stopped."""
    ends = sorted(
        dict.fromkeys(min(max(each, 0), len(whole)) for each in [*cuts.at, len(whole)])
    )
    stream = io.BytesIO(whole)

    def reads() -> Iterator[Read]:
        """Yield each read, made once the record has grown to the next cut."""
        since = None
        with record.path.open("wb") as written:
            for end in ends:
                written.write(stream.read(end - stream.tell()))
                written.flush()
                read = records.read(record, since)
                since = read.reading
                yield read

    everything = list(reads())
    return Read(
        steps=[step for each in everything for step in each.steps],
        reading=everything[-1].reading,
    )


class RecordsPromises(Part):
    """What whoever reads conversations from the runtimes' records can count on."""

    @lup.promise
    async def a_record_read_as_it_grows_reads_as_one_read_whole(
        self, by: Testing
    ) -> None:
        """A record read again each time it grows, from where the last read stopped, gives the steps one read of it whole gives, in the same order, on both runtimes: a line still being written waits for the next read."""
        cuts = by.any(Cuts)
        with tempfile.TemporaryDirectory() as made:
            for records, lines in [
                (ClaudeRecords(), CLAUDE_LINES),
                (CodexRecords(), CODEX_LINES),
            ]:
                whole = lined(*lines)
                path = Path(made) / "record.jsonl"
                record = Record(path=path, home=path.parent, session=SESSION)
                pieces = grown(records, record, whole, cuts)
                path.write_bytes(whole)
                assert pieces.steps == records.read(record).steps

    @lup.promise
    async def a_record_replaced_is_read_again_from_its_start(self, by: Testing) -> None:
        """A record whose first line changed, or that shrank, since an earlier read is read from its start, and the read says so."""
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "record.jsonl"
            record = Record(path=path, home=path.parent, session=SESSION)
            records = ClaudeRecords()
            path.write_bytes(lined(*CLAUDE_LINES))
            before = records.read(record)
            shrunk = by.any(bool)
            replaced = (
                lined(CLAUDE_LINES[0], typed("fewer words", "u1"))
                if shrunk
                else lined(typed("other words", "u9"), *CLAUDE_LINES)
            )
            path.write_bytes(replaced)
            after = records.read(record, before.reading)
            assert after.again
            path.write_bytes(replaced)
            assert after.steps == records.read(record).steps

    @lup.promise
    async def a_line_too_long_to_hold_is_skipped(self, by: Testing) -> None:
        """A line longer than the reader holds is skipped, and every line after it read, so a room can't make a reader hold what it writes."""
        longest = 1000
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "record.jsonl"
            record = Record(path=path, home=path.parent, session=SESSION)
            records = ClaudeRecords(longest=longest)
            path.write_bytes(lined(typed("x" * (longest * 3), "u0"), *CLAUDE_LINES))
            read = records.read(record)
            words = [each.text for each in read.steps if isinstance(each, Said)]
            assert "the first words" in words
            assert "another answer" in words
            assert all(len(each) < longest for each in words)

    @lup.promise
    async def who_said_what_is_read_from_how_it_came(self, by: Testing) -> None:
        """Claude Code's lines say who said what: the operator typing, lup's push, another conversation's message, words queued while the agent worked, and the runtime's own, each read as theirs."""
        lines = [
            typed("typed", "u1"),
            claude(
                type="user",
                uuid="u2",
                isMeta=True,
                origin={"kind": "channel"},
                promptSource="system",
                message={"role": "user", "content": "pushed"},
            ),
            claude(
                type="user",
                uuid="u3",
                isMeta=True,
                origin={"kind": "peer"},
                message={"role": "user", "content": "a peer's"},
            ),
            claude(
                type="attachment",
                uuid="u4",
                attachment={
                    "type": "queued_command",
                    "commandMode": "prompt",
                    "prompt": "queued",
                    "origin": {"kind": "human"},
                },
            ),
            claude(
                type="user",
                uuid="u5",
                origin={"kind": "task-notification"},
                message={"role": "user", "content": "a task's"},
            ),
            claude(
                type="user",
                uuid="u6",
                promptSource="sdk",
                message={"role": "user", "content": "held"},
            ),
            claude(
                type="attachment",
                uuid="u7",
                attachment={"type": "hook_additional_context", "content": ["told"]},
            ),
        ]
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "record.jsonl"
            path.write_bytes(lined(*lines))
            read = ClaudeRecords().read(
                Record(path=path, home=path.parent, session=SESSION)
            )
        heard = {
            each.text: (each.by, each.queued)
            for each in read.steps
            if isinstance(each, Said)
        }
        assert heard == {
            "typed": ("operator", False),
            "pushed": ("lup", False),
            "a peer's": ("conversation", False),
            "queued": ("operator", True),
            "a task's": ("runtime", False),
            "held": ("lup", False),
            "told": ("lup", False),
        }

    @lup.promise
    async def a_long_output_is_read_whole_from_the_sessions_own_folder(
        self, by: Testing
    ) -> None:
        """A call's output too long for Claude Code's record is read whole from the file the record names, in the session's own folder alone: a file of that name reached through a link, or elsewhere, isn't read."""
        linked = by.any(bool)
        whole = "the whole output"
        with tempfile.TemporaryDirectory() as made:
            folder = Path(made) / "projects" / "-work"
            saved = folder / SESSION / "tool-results"
            saved.mkdir(parents=True)
            outside = Path(made) / "elsewhere.txt"
            outside.write_text("not the session's")
            if linked:
                (saved / "call.txt").symlink_to(outside)
            else:
                (saved / "call.txt").write_text(whole)
            path = folder / f"{SESSION}.jsonl"
            named = f"/elsewhere/{SESSION}/tool-results/call.txt"
            path.write_bytes(
                lined(
                    returned(
                        "toolu_1",
                        "<persisted-output>a preview</persisted-output>",
                        "r1",
                        result={"persistedOutputPath": named},
                    )
                )
            )
            read = ClaudeRecords().read(
                Record(path=path, home=path.parent, session=SESSION)
            )
        outputs = [each.output for each in read.steps if isinstance(each, Returned)]
        assert outputs == [
            "<persisted-output>a preview</persisted-output>" if linked else whole
        ]

    @lup.promise
    async def a_call_a_cell_makes_is_read_once_within_it(self, by: Testing) -> None:
        """On Codex, a call a code-mode cell makes is read once, within the cell, with what it returned and whether it failed, and a call made directly is read once, though an item repeats it; each named as the hooks name it."""
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "rollout.jsonl"
            path.write_bytes(lined(*CODEX_LINES))
            read = CodexRecords().read(
                Record(path=path, home=path.parent, session=SESSION)
            )
        calls = {
            each.call: (each.tool, each.within)
            for each in read.steps
            if isinstance(each, Called)
        }
        assert calls == {
            "call_direct": ("mcp__lup__rename", None),
            "cell_1": ("exec", None),
            "call_in_cell": ("mcp__lup__stop", "cell_1"),
        }
        results = [
            (each.call, each.failed)
            for each in read.steps
            if isinstance(each, Returned)
        ]
        assert sorted(call for call, _ in results) == sorted(calls)
        assert ("call_in_cell", True) in results

    @lup.promise
    async def every_record_in_a_home_is_found_with_who_spawned_it(
        self, by: Testing
    ) -> None:
        """Every record in a runtime's home is found, a subagent's with the conversation and the call that spawned them, and a file that isn't one of the runtime's records is left out."""
        with tempfile.TemporaryDirectory() as made:
            home = Path(made)
            folder = home / "projects" / "-work"
            subagents = folder / SESSION / "subagents"
            subagents.mkdir(parents=True)
            (folder / f"{SESSION}.jsonl").write_bytes(lined(*CLAUDE_LINES))
            (folder / "stray.jsonl").write_bytes(b"not a record\n")
            (subagents / "agent-a1.jsonl").write_bytes(
                lined(
                    claude(
                        type="user",
                        uuid="b1",
                        agentId="a1",
                        isSidechain=True,
                        message={"role": "user", "content": "a brief"},
                    )
                )
            )
            (subagents / "agent-a1.meta.json").write_text(
                json.dumps({"toolUseId": "toolu_spawn", "parentAgentId": "a0"})
            )
            found = ClaudeRecords().found(home)
            nowhere = ClaudeRecords().found(home, under=[Path("/elsewhere")])
        spawned = {each.conversation: (each.spawner, each.call) for each in found}
        assert spawned == {None: (None, None), "a1": ("a0", "toolu_spawn")}
        assert all(
            each.session == SESSION and each.directory == Path("/work")
            for each in found
        )
        assert nowhere == []

    @lup.promise
    async def the_context_is_counted_once_a_message(self, by: Testing) -> None:
        """On Claude Code, the context a request took is counted once for each message of the agent's, however many lines the message is written over."""
        usage: JsonValue = {
            "input_tokens": 3,
            "cache_creation_input_tokens": 5,
            "cache_read_input_tokens": 7,
        }
        lines = [
            claude(
                type="assistant",
                uuid=f"a{each}",
                message={
                    "role": "assistant",
                    "id": message,
                    "model": "claude-opus-5-5",
                    "usage": usage,
                    "content": [{"type": "text", "text": f"part {each}"}],
                },
            )
            for each, message in enumerate(["msg_1", "msg_1", "msg_2"])
        ]
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "record.jsonl"
            path.write_bytes(lined(*lines))
            read = ClaudeRecords().read(
                Record(path=path, home=path.parent, session=SESSION)
            )
        counted = [each.used for each in read.steps if isinstance(each, Counted)]
        assert counted == [15, 15]

    @lup.promise
    async def the_task_list_stands_as_the_agents_calls_left_it(
        self, by: Testing
    ) -> None:
        """On Claude Code, the agent's task list is said whole each time their calls change it: a task asked for once its result gives its id, changed, then deleted."""
        deleted = by.any(bool)

        def called(call: str, tool: str, given: JsonValue, uuid: str) -> JsonValue:
            return claude(
                type="assistant",
                uuid=uuid,
                message={
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": call, "name": tool, "input": given}
                    ],
                },
            )

        lines = [
            called(
                "t1", "TaskCreate", {"subject": "port it", "description": "…"}, "a1"
            ),
            returned(
                "t1", "made", "r1", result={"task": {"id": "1", "subject": "port it"}}
            ),
            called("t2", "TaskUpdate", {"taskId": "1", "status": "in_progress"}, "a2"),
            called(
                "t3",
                "TaskUpdate",
                {"taskId": "1", "status": "deleted" if deleted else "completed"},
                "a3",
            ),
        ]
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "record.jsonl"
            path.write_bytes(lined(*lines))
            read = ClaudeRecords().read(
                Record(path=path, home=path.parent, session=SESSION)
            )
        lists = [
            [(task.id, task.subject, task.status) for task in each.tasks]
            for each in read.steps
            if isinstance(each, Planned)
        ]
        assert lists == [
            [("1", "port it", "pending")],
            [("1", "port it", "in_progress")],
            [] if deleted else [("1", "port it", "completed")],
        ]

    @lup.promise
    async def a_call_refused_reads_as_refused(self, by: Testing) -> None:
        """On Claude Code, a call a hook refused before it ran reads as refused, told apart from one that ran and failed, what it returned saying why."""
        lines = [
            answered("an answer", "toolu_1", "a1"),
            claude(
                type="attachment",
                uuid="h1",
                attachment={
                    "type": "hook_permission_decision",
                    "decision": "deny",
                    "hookEvent": "PreToolUse",
                    "toolUseID": "toolu_1",
                },
            ),
            returned("toolu_1", "refused: why", "r1"),
        ]
        with tempfile.TemporaryDirectory() as made:
            path = Path(made) / "record.jsonl"
            path.write_bytes(lined(*lines))
            read = ClaudeRecords().read(
                Record(path=path, home=path.parent, session=SESSION)
            )
        refused = [each.call for each in read.steps if isinstance(each, Refused)]
        assert refused == ["toolu_1"]

    @lup.promise
    async def a_copy_reads_as_the_home_it_was_copied_from(self, by: Testing) -> None:
        """A home's records copied, and copied again once they grew, read as the home's do, a long output saved beside them among it; a file reached through a link isn't copied."""
        grows = by.any(bool)
        with tempfile.TemporaryDirectory() as made:
            home = Path(made) / "home"
            into = Path(made) / "copy"
            folder = home / "projects" / "-work"
            saved = folder / SESSION / "tool-results"
            saved.mkdir(parents=True)
            (saved / "call.txt").write_text("the whole output")
            outside = Path(made) / "secret.txt"
            outside.write_text("not the session's")
            (saved / "linked.txt").symlink_to(outside)
            record = folder / f"{SESSION}.jsonl"
            record.write_bytes(lined(CLAUDE_LINES[0], CLAUDE_LINES[1]))
            records = ClaudeRecords()
            copied(records, home, into)
            if grows:
                record.write_bytes(lined(*CLAUDE_LINES))
                copied(records, home, into)
            original = records.read(Record(path=record, home=home, session=SESSION))
            copy = into / record.relative_to(home)
            kept = records.read(Record(path=copy, home=into, session=SESSION))
            assert kept.steps == original.steps
            copied_saved = into / saved.relative_to(home)
            assert (copied_saved / "call.txt").read_text() == "the whole output"
            assert not (copied_saved / "linked.txt").exists()

    @lup.promise
    async def nothing_is_read_through_a_link_out_of_its_home(self, by: Testing) -> None:
        """A record, or a whole folder of them, reached through a link pointing out of the home it's found in isn't read, so a room can't have the reader read a file of the operator's by linking to it."""
        whole_folder = by.any(bool)
        with tempfile.TemporaryDirectory() as made:
            home = Path(made) / "home"
            outside = Path(made) / "outside"
            elsewhere = outside / "-work"
            elsewhere.mkdir(parents=True)
            (elsewhere / f"{SESSION}.jsonl").write_bytes(lined(*CLAUDE_LINES))
            projects = home / "projects"
            projects.mkdir(parents=True)
            if whole_folder:
                (projects / "-work").symlink_to(elsewhere)
            else:
                (projects / "-work").mkdir()
                (projects / "-work" / f"{SESSION}.jsonl").symlink_to(
                    elsewhere / f"{SESSION}.jsonl"
                )
            assert ClaudeRecords().found(home) == []
