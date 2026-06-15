# claude: Also, what's the difference between realtime_relay and realtime?
"""Realtime relay for backends whose tools run in a subprocess.

On Claude, a persistent agent holds one never-ending SDK turn: its tools
share process state with the :class:`~lup.realtime.Scheduler`, ``sleep``
blocks in-process, and a Stop hook forbids ending the turn. Backends
without in-process tools (Codex, and OpenAI-compatible endpoints through
the Codex runtime) invert the loop: **each wake is one SDK turn**, and
the parent process owns the Scheduler between turns.

State crosses the process boundary through files in a realtime directory
(by convention ``session_dir/realtime/``, relayed to the tool subprocess
via ``LUP_REALTIME_DIR`` — see :class:`lup.paths.SessionContext`):

- ``actions.jsonl`` — agent → parent event stream appended by the served
  tools (reply, schedule_action, debounce, remind, meta, context reads).
  The parent applies events to the Scheduler as they arrive — a watcher
  polls *during* the turn, so replies are delivered promptly rather than
  at turn end.
- ``sleep_request.json`` — written by the served ``sleep`` tool, after
  which the agent ends its turn. The parent consumes the request, sleeps
  on the Scheduler, and starts the next turn with a wake message.
- ``state.json`` — parent → agent snapshot (unread event count plus any
  domain fields). The served ``context`` tool returns it; the ``sleep``
  tool refuses to record a sleep while unread events exist.
- ``meta_flag`` — file-backed :class:`~lup.reflect.ReflectionGate`. The
  ``meta`` tool marks it, ``reply`` resets it, and ``sleep`` requires it.
  Gate transitions triggered by the agent's own actions happen inside
  the tool subprocess so they follow the agent's tool-call order; the
  parent only resets the gate between turns, when no tool is running.

Wire the parent side with :func:`run_relay_session`; the tool side is
:func:`create_realtime_relay_tools`, served by the tool subprocess when
the realtime directory is relayed.

Examples:
    Parent process (environment layer)::

        >>> scheduler = Scheduler(on_action=deliver_to_user)
        >>> mailbox = RealtimeMailbox(notes.session / "realtime")
        >>> async with adapter.conversation() as conv:
        ...     await run_relay_session(
        ...         conv,
        ...         scheduler=scheduler,
        ...         mailbox=mailbox,
        ...         initial_prompt="[Session started — read context and engage]",
        ...         build_state=lambda: RelayState(unread_events=inbox.unread()),
        ...     )
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from lup.adapters.common import Conversation
from lup.mcp import LupMcpTool, ToolError, lup_tool
from lup.realtime import (
    ContextInput,
    ContextOutput,
    DebounceInput,
    DebounceOutput,
    MetaInput,
    MetaOutput,
    RemindInput,
    RemindOutput,
    ReplyInput,
    ReplyOutput,
    ScheduleActionInput,
    ScheduleActionOutput,
    Scheduler,
    SleepInput,
    SleepResult,
)
from lup.reflect import ReflectionGate
from lup.trace import TraceLogger

logger = logging.getLogger(__name__)

REALTIME_DIRNAME = "realtime"
ACTIONS_FILENAME = "actions.jsonl"
SLEEP_REQUEST_FILENAME = "sleep_request.json"
STATE_FILENAME = "state.json"
META_FLAG_FILENAME = "meta_flag"

MAX_ACTIONS_BYTES = 32 * 1024 * 1024
"""Default cap on the actions file — backpressure against a looping agent."""

MISSING_SLEEP_MESSAGE = (
    "Your turn ended without calling sleep. This is a persistent session: "
    "you yield control with the sleep tool, and the environment wakes you "
    "when something happens. Finish any pending replies, record a meta "
    "assessment, then call sleep."
)


# =====================================================================
# Relay events (agent → parent)
# =====================================================================


class ReplyEvent(BaseModel):
    """A message the agent wants delivered to the environment."""

    type: Literal["reply"] = "reply"
    message: str
    delay_seconds: int = 0


class ScheduleActionEvent(BaseModel):
    """A quiet-period action request (see Scheduler.start_scheduled_action)."""

    type: Literal["schedule_action"] = "schedule_action"
    content: str
    delay_seconds: int


class DebounceEvent(BaseModel):
    """A debounce window request (see Scheduler.start_debounce)."""

    type: Literal["debounce"] = "debounce"
    initial_seconds: int
    quiet_seconds: int


class RemindEvent(BaseModel):
    """A self-prompt reminder request (see Scheduler.add_reminder)."""

    type: Literal["remind"] = "remind"
    label: str
    delay_seconds: int


class MetaEvent(BaseModel):
    """A process self-assessment, relayed for trace logging."""

    type: Literal["meta"] = "meta"
    thought: str


class ContextReadEvent(BaseModel):
    """The agent read the state snapshot; the parent may mark events read."""

    type: Literal["context_read"] = "context_read"
    last_events: int = 5


type RelayEvent = Annotated[
    ReplyEvent
    | ScheduleActionEvent
    | DebounceEvent
    | RemindEvent
    | MetaEvent
    | ContextReadEvent,
    Field(discriminator="type"),
]

RELAY_EVENT_ADAPTER: TypeAdapter[RelayEvent] = TypeAdapter(RelayEvent)


class RelayState(BaseModel):
    """Parent-maintained snapshot served to the agent's context tool.

    ``unread_events`` drives the sleep guard; everything else is domain
    context — extra fields pass through to the agent verbatim.
    """

    model_config = {"extra": "allow"}

    unread_events: int = 0


class SleepRecordedOutput(BaseModel):
    """Output for the relay sleep tool."""

    status: str = "recorded"
    seconds: int
    instruction: str = "End your turn now — the environment will wake you."


# =====================================================================
# Mailbox (file protocol)
# =====================================================================


class RelayOverflowError(ToolError):
    """The actions file exceeded its cap — events are not being consumed.

    Raised by the writing side so a looping agent learns the channel is
    wedged (``ToolError`` → ``is_error`` tool response) instead of
    growing the file without bound. The file is append-only within a
    run; a very long legitimate session can raise ``max_actions_bytes``.
    """


class RealtimeMailbox:
    """File-backed agent↔parent relay rooted at a realtime directory.

    The tool subprocess appends events and writes the sleep request; the
    parent reads new events (offset-tracked, complete lines only),
    consumes the sleep request, and publishes state snapshots atomically.
    One instance per side — the read offset lives in the parent's copy.
    """

    def __init__(
        self, root: Path, *, max_actions_bytes: int | None = MAX_ACTIONS_BYTES
    ) -> None:
        self.root = root
        self.actions_path = root / ACTIONS_FILENAME
        self.sleep_request_path = root / SLEEP_REQUEST_FILENAME
        self.state_path = root / STATE_FILENAME
        self.meta_flag_path = root / META_FLAG_FILENAME
        self.max_actions_bytes = max_actions_bytes
        self.read_offset = 0

    # -- tool side (subprocess) -----------------------------------------

    def append_event(self, event: RelayEvent) -> None:
        """Append one event line for the parent to apply.

        Raises :class:`RelayOverflowError` once the actions file reaches
        ``max_actions_bytes`` (None disables the cap).
        """
        self.root.mkdir(parents=True, exist_ok=True)
        if (
            self.max_actions_bytes is not None
            and self.actions_path.exists()
            and self.actions_path.stat().st_size >= self.max_actions_bytes
        ):
            raise RelayOverflowError(
                f"Relay actions file reached {self.max_actions_bytes} bytes; "
                "the parent is not consuming events. Stop emitting and end "
                "the turn."
            )
        with self.actions_path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def write_sleep_request(self, request: SleepInput) -> None:
        """Record the sleep parameters the parent applies after the turn."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.sleep_request_path.write_text(request.model_dump_json(), encoding="utf-8")

    def read_state(self) -> RelayState | None:
        """Read the parent's latest state snapshot, or None when absent."""
        if not self.state_path.exists():
            return None
        try:
            return RelayState.model_validate_json(
                self.state_path.read_text(encoding="utf-8")
            )
        except ValidationError, OSError:
            logger.exception("Unreadable relay state at %s", self.state_path)
            return None

    # -- parent side -----------------------------------------------------

    def peek_new_events(self) -> list[tuple[RelayEvent, int]]:
        """Parse new events without advancing past un-applied ones.

        Returns ``(event, commit_offset)`` pairs in file order. Applying
        an event and then setting :attr:`read_offset` to its
        ``commit_offset`` consumes exactly that event (and any malformed
        or blank lines preceding it); the final pair's offset covers the
        whole complete region. The caller commits per event so a crash or
        cancellation between events never drops an un-applied one.
        """
        if not self.actions_path.exists():
            return []
        with self.actions_path.open("rb") as f:
            f.seek(self.read_offset)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return []
        region = data[: end + 1]
        region_end = self.read_offset + len(region)

        pairs: list[tuple[RelayEvent, int]] = []
        consumed = self.read_offset
        for raw_line in region.splitlines(keepends=True):
            consumed += len(raw_line)
            line = raw_line.strip()
            if not line:
                continue
            try:
                pairs.append((RELAY_EVENT_ADAPTER.validate_json(line), consumed))
            except ValidationError:
                logger.exception("Skipping malformed relay event: %r", line)
        if pairs:
            event, _ = pairs[-1]
            pairs[-1] = (event, region_end)
        return pairs

    def read_new_events(self) -> list[RelayEvent]:
        """Return events appended since the last read (complete lines only)."""
        pairs = self.peek_new_events()
        if pairs:
            self.read_offset = pairs[-1][1]
        return [event for event, _ in pairs]

    def consume_sleep_request(self) -> SleepInput | None:
        """Read and remove the sleep request, or None when the agent didn't sleep."""
        try:
            text = self.sleep_request_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        self.sleep_request_path.unlink(missing_ok=True)
        try:
            return SleepInput.model_validate_json(text)
        except ValidationError:
            logger.exception("Malformed sleep request: %r", text)
            return None

    def write_state(self, state: RelayState) -> None:
        """Publish a state snapshot atomically (write-then-rename)."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".tmp")
        tmp_path.write_text(state.model_dump_json(), encoding="utf-8")
        os.replace(
            tmp_path, self.state_path
        )  # claude: ignore — atomic file rename, not str.replace

    def reset_for_new_run(self) -> None:
        """Clear leftover protocol files so a fresh run starts clean.

        Re-running the same ``session_id`` (crash recovery or an
        intentional resume) must not replay the previous run's events: a
        leftover ``actions.jsonl`` would be consumed from offset 0, and a
        stale ``sleep_request.json`` or ``meta_flag`` would mis-drive the
        first turn. Truncating here is safe — the within-run protocol
        appends and offset-tracks only after this point.
        """
        self.read_offset = 0
        if self.actions_path.exists():
            self.actions_path.write_text("", encoding="utf-8")
        self.sleep_request_path.unlink(missing_ok=True)
        self.meta_flag_path.unlink(missing_ok=True)


# =====================================================================
# Served tools (subprocess side)
# =====================================================================


def create_realtime_relay_tools(realtime_dir: Path) -> list[LupMcpTool]:
    """Create the realtime tool set for subprocess backends.

    Same tool names and schemas as the in-process Claude set (see
    ``create_realtime_tools`` in the template), but instead of touching a
    Scheduler directly the handlers relay through the mailbox: actions
    stream to the parent as events, and ``sleep`` records a request and
    instructs the agent to end its turn — the parent does the waiting.

    Enforcement is in-handler (no hooks required on any backend):
    ``sleep`` requires a fresh ``meta`` (file-backed gate, reset by
    ``reply``) and refuses while the state snapshot shows unread events
    the agent hasn't looked at via ``context``.
    """
    mailbox = RealtimeMailbox(realtime_dir)
    gate = ReflectionGate(flag_path=mailbox.meta_flag_path)
    context_read = [False]  # Mutable container for closure

    # claude: Wait I'm very confused, shouldn't this go to template instead? This seems rigid
    @lup_tool(
        "Deliver a message to the environment. Text output and thinking "
        "don't reach the user — this is the only way to communicate. "
        "Messages are relayed to the environment immediately, while your "
        "turn continues. For a sequence of short reactions you can batch "
        "with staggered delay_seconds; delayed messages cancel if an "
        "external event arrives. Sending also cancels any pending "
        "scheduled_action and requires a fresh meta before sleep.",
        name="reply",
    )
    async def reply_tool(inp: ReplyInput) -> ReplyOutput:
        sent = 0
        scheduled = 0
        cumulative_delay = 0
        for item in inp.messages:
            cumulative_delay += item.delay_seconds
            mailbox.append_event(
                ReplyEvent(message=item.message, delay_seconds=cumulative_delay)
            )
            if cumulative_delay == 0:
                sent += 1
            else:
                scheduled += 1
        if sent or scheduled:
            gate.reset()
        return ReplyOutput(sent=sent, scheduled=scheduled)

    @lup_tool(
        "Schedule an action that fires if the environment stays quiet for "
        "delay_seconds. Cancels (saved as idea) if an event arrives or "
        "you send a reply. Only one at a time — calling again replaces "
        "the previous one. Does not generate a new turn when it fires.",
        name="schedule_action",
    )
    async def schedule_action_tool(inp: ScheduleActionInput) -> ScheduleActionOutput:
        mailbox.append_event(
            ScheduleActionEvent(content=inp.content, delay_seconds=inp.delay_seconds)
        )
        return ScheduleActionOutput(delay_seconds=inp.delay_seconds)

    @lup_tool(
        "Suppress wake events until activity stops. Two phases: waits "
        "up to initial_seconds for the first event; once activity starts, "
        "holds wake until quiet_seconds elapse with no new activity. "
        "Events still go to state — context works during debounce. "
        "Returns immediately. Only one debounce at a time — calling "
        "again replaces the previous one.",
        name="debounce",
    )
    async def debounce_tool(inp: DebounceInput) -> DebounceOutput:
        mailbox.append_event(
            DebounceEvent(
                initial_seconds=inp.initial_seconds, quiet_seconds=inp.quiet_seconds
            )
        )
        return DebounceOutput(
            initial_seconds=inp.initial_seconds,
            quiet_seconds=inp.quiet_seconds,
        )

    @lup_tool(
        "Yield control until something happens. Records your sleep "
        "parameters and instructs you to end your turn — the environment "
        "sleeps on them and wakes you with a new turn (external event, "
        "reminder, or timer), so this is how every turn should end. "
        "You MUST call meta before sleeping. Blocked while unread events "
        "exist that you haven't read via context — use force=true to "
        "bypass. Set debounce_initial/debounce_quiet to batch event "
        "bursts; follow_ups send messages at intervals while you sleep.",
        name="sleep",
    )
    async def sleep_tool(inp: SleepInput) -> SleepRecordedOutput:
        if not gate.reflected:
            raise ToolError(
                "You must call meta with a process assessment before "
                "sleeping. Reflect first, then sleep."
            )
        state = mailbox.read_state()
        unread = state.unread_events if state is not None else 0
        if (
            unread > 0
            and not inp.force
            and inp.debounce_initial is None
            and not context_read[0]
        ):
            raise ToolError(f"Blocked — {unread} unread event(s). Call context first.")
        mailbox.write_sleep_request(inp)
        context_read[0] = False
        return SleepRecordedOutput(seconds=inp.seconds)

    @lup_tool(
        "Schedule a self-prompt that fires after delay_seconds. "
        "When it fires, it wakes you with fired_reminders in the wake "
        "message. Multiple reminders can be active simultaneously. "
        "Use for things you want to come back to — checking in, "
        "revisiting a topic, following up on something.",
        name="remind",
    )
    async def remind_tool(inp: RemindInput) -> RemindOutput:
        mailbox.append_event(
            RemindEvent(label=inp.label, delay_seconds=inp.delay_seconds)
        )
        return RemindOutput(label=inp.label, delay_seconds=inp.delay_seconds)

    @lup_tool(
        "Get current state and read new events. Returns the environment's "
        "latest snapshot: unread event count, timing info, and any "
        "domain-specific context the environment publishes. Reading "
        "context tells the environment you've seen pending events, which "
        "unblocks sleep.",
        name="context",
    )
    async def context_tool(inp: ContextInput) -> ContextOutput:
        mailbox.append_event(ContextReadEvent(last_events=inp.last_events))
        context_read[0] = True
        state = mailbox.read_state()
        if state is None:
            return ContextOutput()
        return ContextOutput(**state.model_dump())

    @lup_tool(
        "Record a process assessment for the improvement loop. "
        "What worked this turn? What was friction? Are you missing "
        "tools or information? Rate pacing, timing, quality. "
        "Be specific. Required before sleep.",
        name="meta",
    )
    async def meta_tool(inp: MetaInput) -> MetaOutput:
        mailbox.append_event(MetaEvent(thought=inp.thought))
        gate.mark_reflected()
        return MetaOutput()

    return [
        reply_tool,
        schedule_action_tool,
        debounce_tool,
        sleep_tool,
        remind_tool,
        context_tool,
        meta_tool,
    ]


# =====================================================================
# Parent side: event application + wake loop
# =====================================================================


async def apply_relay_event(
    event: RelayEvent,
    *,
    scheduler: Scheduler,
    trace_logger: TraceLogger | None = None,
) -> None:
    """Apply one agent event to the parent's Scheduler.

    Mirrors what the in-process Claude tools do directly, with one
    deliberate exception: meta-gate transitions stay tool-side (the
    reply tool resets the gate in its own process) so the gate always
    follows the agent's tool-call order — a parent-side reset could race
    a meta the agent recorded just after replying.
    """
    match event:
        case ReplyEvent():
            if event.delay_seconds == 0:
                await scheduler.send_action(event.message)
            else:
                scheduler.add_delayed_action(event.message, event.delay_seconds)
            scheduler.cancel_scheduled_action()
        case ScheduleActionEvent():
            scheduler.start_scheduled_action(event.content, event.delay_seconds)
        case DebounceEvent():
            scheduler.start_debounce(event.initial_seconds, event.quiet_seconds)
        case RemindEvent():
            scheduler.add_reminder(event.label, event.delay_seconds)
        case MetaEvent():
            if trace_logger:
                trace_logger.log_text(event.thought, heading="Meta")
        case ContextReadEvent():
            scheduler.consume_wake()


def default_wake_message(result: SleepResult) -> str:
    """Minimal wake message; supply build_wake_message for domain context."""
    parts = [f"[wake] reason: {result.get('reason', 'timer')}"]
    fired = result.get("fired_reminders")
    if fired:
        parts.append("fired reminders: " + ", ".join(fired))
    parts.append("Read context, act as needed, then meta and sleep again.")
    return "\n".join(parts)


async def run_relay_session(
    conversation: Conversation,
    *,
    scheduler: Scheduler,
    mailbox: RealtimeMailbox,
    initial_prompt: str,
    build_wake_message: Callable[[SleepResult], str] | None = None,
    build_state: Callable[[], RelayState] | None = None,
    on_event: Callable[[RelayEvent], Awaitable[None]] | None = None,
    should_continue: Callable[[], bool] | None = None,
    poll_interval_seconds: float = 0.3,
    max_missing_sleep_retries: int = 3,
    trace_logger: TraceLogger | None = None,
) -> int:
    """Run the persistent wake loop over a multi-turn conversation.

    Each cycle: publish state, run one turn (applying mailbox events as
    they appear), consume the sleep request, sleep on the Scheduler,
    wake, and start the next turn with a wake message. The relay
    counterpart of the Claude Stop-hook loop: an agent that ends its
    turn without sleeping gets a bounded number of corrective turns
    (mirroring the Stop hook's forced continuation) before the session
    ends.

    Args:
        conversation: An open multi-turn conversation (Codex thread).
        scheduler: The parent's Scheduler; the environment layer calls
            ``scheduler.wake(...)`` / ``extend_debounce()`` on events.
        mailbox: The relay mailbox (parent-side copy).
        initial_prompt: First-turn message starting the session.
        build_wake_message: Builds each wake turn's message from the
            sleep result; defaults to :func:`default_wake_message`.
        build_state: Builds the state snapshot published before each
            turn (unread counts, domain context).
        on_event: Optional domain hook invoked after each applied event
            (e.g. mark inbox messages read on ContextReadEvent).
        should_continue: Pure predicate ending the session when False.
            Checked at each cycle start and again before sleeping (a
            finished session must not wait out a final sleep). None runs
            until cancelled or the budget is exhausted
            (BudgetExceededError propagates to the caller).
        poll_interval_seconds: Mailbox poll cadence during a turn.
        max_missing_sleep_retries: Corrective turns granted to an agent
            that ends a turn without sleeping before the session ends.
        trace_logger: Receives turn traces and meta assessments.

    Returns:
        The number of completed turns.
    """
    mailbox.reset_for_new_run()
    gate = ReflectionGate(flag_path=mailbox.meta_flag_path)
    builder = build_wake_message or default_wake_message
    message = initial_prompt
    turns = 0
    missing_sleep = 0

    async def apply_new_events() -> None:
        # Commit the read offset per event, only after it is fully
        # applied — a cancellation or a raising handler then leaves the
        # offset on the first un-applied event, so the next poll redelivers
        # it. No agent event (the user-facing replies) is ever dropped.
        for event, commit_offset in mailbox.peek_new_events():
            await apply_relay_event(
                event, scheduler=scheduler, trace_logger=trace_logger
            )
            if on_event is not None:
                await on_event(event)
            mailbox.read_offset = commit_offset

    async def watch_mailbox() -> None:
        while not stop_watching.is_set():
            await apply_new_events()
            try:
                await asyncio.wait_for(stop_watching.wait(), poll_interval_seconds)
            except TimeoutError:
                pass
        await apply_new_events()

    while should_continue is None or should_continue():
        if build_state is not None:
            mailbox.write_state(build_state())

        stop_watching = asyncio.Event()
        watcher = asyncio.create_task(watch_mailbox())
        try:
            await conversation.send(message, trace_logger=trace_logger)
        finally:
            stop_watching.set()
            await watcher
        await apply_new_events()
        turns += 1

        request = mailbox.consume_sleep_request()
        if request is None:
            missing_sleep += 1
            if missing_sleep > max_missing_sleep_retries:
                logger.error(
                    "Agent ended %d consecutive turns without sleeping; "
                    "ending relay session",
                    missing_sleep,
                )
                break
            message = MISSING_SLEEP_MESSAGE
            continue
        missing_sleep = 0

        gate.reset()
        if request.debounce_initial is not None:
            scheduler.start_debounce(
                request.debounce_initial,
                request.debounce_quiet or request.debounce_initial,
                wake_on_empty=request.wake_on_empty,
            )
        for follow_up in request.follow_ups:
            scheduler.add_delayed_action(follow_up.message, follow_up.delay_seconds)

        if should_continue is not None and not should_continue():
            break
        result = await scheduler.sleep(request.seconds)
        message = builder(result)

    return turns
