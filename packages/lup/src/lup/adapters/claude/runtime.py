"""Claude Code, driven through its Agent SDK: one turn, with no tools but lup's own.

`ClaudeAdapter` runs each turn in a Claude Code process of its own, configured so
that nothing can happen but calls to lup's tools: no commands, no files, no
network, no agents. A session gets:
- no built-in tools (`tools=[]`), no MCP server but lup's own
  (`strict_mcp_config`), and no skills or plugins;
- lup's tools pre-approved (`allowed_tools`), and every other call denied
  (`permission_mode="dontAsk"`);
- no settings from the filesystem (`setting_sources=[]`), so the operator's and the
  project's hooks, `CLAUDE.md` and MCP servers don't load; auto memory, which loads
  whatever the settings say, is turned off by its variable;
- the prompt delivered verbatim (`verbatim_prompts`): no `@path` expansion and no
  slash commands, so text from data can't make Claude Code read a local file;
- no session persistence, so nothing reaches the operator's history or resume
  list.

**lup's tools** are served in-process by lup's own MCP server over the turn's
toolbox (`tool_server`, `lup.tools.serving`), rather than by the SDK's
`create_sdk_mcp_server`, which checks a call's arguments against the schema
before the handler runs. Every call reaches the toolbox as the model sent it, so
lup validates it: a malformed call is refused, counted and recorded like any
other.

**The turn's guard** is a `Stop` hook asking the toolbox whether the turn may end.
Blocking keeps the same turn going, and the model reads the reason; letting it end
after the attempts are spent leaves the ask without an answer, which `Asking`
raises.

**The tool check.** The session's first message (`init`) lists the tools and MCP
servers it loaded; anything beyond lup's own interrupts the turn and raises
`ToolsPresentError` before the model can use it. The message also lists skills,
plugins, agents and slash commands, which it lists even when nothing can call
them (no `Skill` or `Agent` tool is loaded, and a verbatim prompt dispatches no
slash command), so only the tools and the servers are checked.

**Errors** are classified from what Claude Code reports in structured form, never
from its text:
- a login missing or refused, as an assistant message's `authentication_failed`
  or an API status of 401: `AuthMissingError`;
- a failed turn whose last rate-limit event said `rejected`:
  `UsageLimitReachedError`, with the window's reset;
- an API status of 429 or 5xx, an assistant message's `rate_limit` or
  `server_error`, or an API error with no status (no response arrived):
  `AgentUnavailableError`, which recovery retries;
- the bundled CLI missing: `RuntimeMissingError`;
- anything else, such as a refused request: `TurnError`, carrying what was
  reported.

A cancelled turn, as when the timeout passes, is interrupted before the
cancellation goes on.

What this relies on, from claude-agent-sdk 0.2.165 and the Claude Code 2.1.294 it
bundles, read in the SDK's source and checked live against a scripted Messages
API:
- `tools=[]` becomes `--tools ""`, after which `init` lists only MCP tools;
- without `verbatim_prompts`, `@/etc/hostname` in a prompt attached the file;
- `--no-session-persistence`, which has no option of its own, wrote no
  transcript;
- auto memory is read whatever `setting_sources` says, unless
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY` is set;
- a `Stop` hook answering `decision: block` continues the turn, and the model
  reads the reason. Claude Code allows 8 blocks in a row, a tool call resetting
  the count, and the submission layer's attempts (3 by default) run out first.
  `Stop` doesn't fire on an interrupt or an API error;
- an overloaded API (529) showed as an assistant message's `server_error`, then a
  result with `is_error`, `api_error_status` 529 and `terminal_reason`
  `api_error`; a 429 as `rate_limit` and 429; a bad key as
  `authentication_failed` and 401; no login at all as `authentication_failed`
  with no status;
- `ClaudeSDKClient` raises nothing on an error result: the result's `is_error`
  says so;
- after `interrupt()` the stream ends with a result `error_during_execution`
  whose `terminal_reason` is `aborted_streaming`.

Not checked live: how the rate-limit event behaves under a subscription login, and
how a dropped connection shows (taken as unavailable, since an API error with no
HTTP status means no response arrived).
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLINotFoundError,
    HookMatcher,
    McpSdkServerConfig,
    RateLimitEvent,
    ResultError,
    ResultMessage,
    SystemMessage,
)
from claude_agent_sdk.types import AssistantMessageError, SyncHookJSONOutput

from lup.adapters.claude import Effort
from lup.adapters.claude.terminal import AUTO_MEMORY_OFF
from lup.sessions.contract import Adapter, RawTurn, TurnRequest, guarded
from lup.sessions.errors import (
    AgentUnavailableError,
    AuthMissingError,
    RealCallInTestError,
    RuntimeMissingError,
    ToolsPresentError,
    TurnError,
    UsageLimitReachedError,
)
from lup.sessions.results import Usage
from lup.sessions.submission import End, GiveUp, KeepGoing, Toolbox
from lup.tools.serving import tool_server
from lup.types import Model

if TYPE_CHECKING:
    from claude_agent_sdk import HookContext, HookInput, HookJSONOutput, Message

SERVER = "lup"
"""The name lup's tool server goes by in Claude Code."""

TOOL_PREFIX = f"mcp__{SERVER}__"
"""What Claude Code puts before the name of each of the server's tools: `mcp__lup__submit`."""

NO_PERSISTENCE = "no-session-persistence"
"""The flag that keeps Claude Code from writing the session to the operator's history."""


def sdk_client(options: ClaudeAgentOptions) -> ClaudeSDKClient:
    """Return the SDK's own client, which starts Claude Code with `options`, unless real turns are refused."""
    if guarded.get():
        message = (
            "a test reached Claude Code: ask for the `fake_agents` fixture and script "
            "the answer with `fake_agents.answer(...)`"
        )
        raise RealCallInTestError(message)
    return ClaudeSDKClient(options)


class LoadedServer(Model):
    """An MCP server a session loaded, as the `init` message lists it."""

    name: str


class Loaded(Model):
    """What a session loaded, as Claude Code's `init` message lists it."""

    tools: list[str]
    mcp_servers: list[LoadedServer]

    def beyond(self, allowed: list[str]) -> list[str]:
        """Return what was loaded beyond lup's own: tools outside `allowed`, and other servers."""
        tools = [tool for tool in self.tools if tool not in allowed]
        servers = [
            f"the MCP server `{server.name}`"
            for server in self.mcp_servers
            if server.name != SERVER
        ]
        return [*tools, *servers]


class Tokens(Model):
    """The tokens a turn used, as Claude Code's result counts them."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def usage(self, cost_usd: float | None) -> Usage:
        """Return these counts as lup's usage, with the cost Claude Code reported."""
        return Usage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_input_tokens,
            cache_write_tokens=self.cache_creation_input_tokens,
            cost_usd=cost_usd,
        )


class Failure(Model):
    """What Claude Code reported about a turn that ended in error."""

    subtype: str | None = None
    api_error_status: int | None = None
    """The failing API call's HTTP status; none where no response arrived, or no call failed."""
    terminal_reason: str | None = None
    errors: list[str] = []
    result: str | None = None
    said: list[AssistantMessageError] = []
    """The errors the turn's assistant messages carried: a missing login shows only here."""
    limited: bool = False
    """Whether the last rate-limit event said the account's usage window is spent."""
    reset_at: datetime | None = None
    """When the spent window resets, where the event said."""

    @classmethod
    def of(cls, ended: ResultMessage | ResultError, messages: list[Message]) -> Failure:
        """Read the failure off the turn's result, or the error raised for it, and its messages."""
        limits = [
            each.rate_limit_info
            for each in messages
            if isinstance(each, RateLimitEvent)
        ]
        limit = limits[-1] if limits else None
        limited = limit is not None and limit.status == "rejected"
        resets_at = None if limit is None else limit.resets_at
        return cls(
            subtype=ended.subtype,
            api_error_status=ended.api_error_status,
            terminal_reason=ended.terminal_reason,
            errors=ended.errors or [],
            result=ended.result,
            said=[
                each.error
                for each in messages
                if isinstance(each, AssistantMessage) and each.error is not None
            ],
            limited=limited,
            reset_at=None
            if resets_at is None
            else datetime.fromtimestamp(resets_at, UTC),
        )

    def unavailable(self) -> bool:
        """Say whether the model couldn't be reached: overloaded, rate limited, a server error, or no response."""
        if "rate_limit" in self.said or "server_error" in self.said:
            return True
        status = self.api_error_status
        if status is None:
            return self.terminal_reason == "api_error"
        return status == 429 or status >= 500

    def error(self) -> TurnError:
        """Return lup's error for this failure."""
        detail = "; ".join(self.errors) or self.result or "nothing more was reported"
        message = (
            f"Claude Code's turn ended in error ({self.subtype}, API status "
            f"{self.api_error_status}, ended by {self.terminal_reason}): {detail}"
        )
        if "authentication_failed" in self.said or self.api_error_status == 401:
            return AuthMissingError(message)
        if self.limited:
            return UsageLimitReachedError(message, reset_at=self.reset_at)
        if self.unavailable():
            return AgentUnavailableError(message)
        return TurnError(message)


async def received(
    client: ClaudeSDKClient, prompt: str, allowed: list[str]
) -> list[Message]:
    """Send `prompt`, and return the turn's messages, up to and including its result.

    The `init` message is checked as it arrives: anything loaded beyond `allowed`
    and lup's server interrupts the turn before the model can use it. A cancelled
    turn is interrupted, then cancelled.
    """

    async def checked() -> AsyncIterator[Message]:
        async for message in client.receive_response():
            if isinstance(message, SystemMessage) and message.subtype == "init":
                loaded = Loaded.model_validate(message.data)
                beyond = loaded.beyond(allowed)
                if beyond:
                    await client.interrupt()
                    refusal = (
                        "the session loaded more than lup's own tools, so the call "
                        f"stopped before the model ran: {', '.join(beyond)}"
                    )
                    raise ToolsPresentError(refusal, tools=loaded.tools)
            yield message

    try:
        await client.query(prompt)
        return [message async for message in checked()]
    except asyncio.CancelledError:
        await client.interrupt()
        raise


def finished(messages: list[Message]) -> RawTurn:
    """Read the turn's report off its messages, or raise what its result says went wrong.

    A turn whose loaded tools were never listed raises too, answered or not: the
    check didn't run.
    """
    results = [each for each in messages if isinstance(each, ResultMessage)]
    if not results:
        message = "Claude Code's turn ended without a result"
        raise TurnError(message)
    result = results[-1]
    if result.is_error:
        raise Failure.of(result, messages).error()
    checked = [
        each
        for each in messages
        if isinstance(each, SystemMessage) and each.subtype == "init"
    ]
    if not checked:
        message = "Claude Code didn't list what the session loaded, so its tools weren't checked"
        raise TurnError(message)
    tokens = Tokens.model_validate(result.usage or {})
    return RawTurn(
        text=result.result or "",
        usage=tokens.usage(result.total_cost_usd),
        session_id=result.session_id,
    )


class ClaudeAdapter(Model, Adapter, arbitrary_types_allowed=True):
    """Runs turns in Claude Code, with no tools but lup's own."""

    model: str | None = None
    """None passes no `--model`, so Claude Code runs its default: the session
    loads none of the operator's settings to choose another."""
    system_prompt: str | None = None
    """Replaces Claude Code's system prompt; none sends an empty one."""
    effort: Effort | None = None
    client: Callable[[ClaudeAgentOptions], ClaudeSDKClient] = sdk_client
    """Make the client a turn runs on, from the session's options; a test gives a scripted one."""

    def options(self, toolbox: Toolbox, allowed: list[str]) -> ClaudeAgentOptions:
        """Return a session's options: the toolbox's tools and guard, and nothing of the operator's.

        `allowed` is what Claude Code calls the toolbox's tools.
        """

        async def stopping(
            event: HookInput, tool_use_id: str | None, context: HookContext
        ) -> HookJSONOutput:
            del event, tool_use_id, context
            match toolbox.end(TOOL_PREFIX):
                case KeepGoing(reason=reason):
                    return SyncHookJSONOutput(decision="block", reason=reason)
                case End() | GiveUp():
                    return SyncHookJSONOutput()

        server = McpSdkServerConfig(
            type="sdk", name=SERVER, instance=tool_server(toolbox, SERVER)
        )
        return ClaudeAgentOptions(
            model=self.model,
            system_prompt=self.system_prompt,
            effort=self.effort,
            tools=[],
            allowed_tools=allowed,
            permission_mode="dontAsk",
            mcp_servers={SERVER: server},
            strict_mcp_config=True,
            setting_sources=[],
            skills=[],
            plugins=[],
            verbatim_prompts=True,
            env={AUTO_MEMORY_OFF: "1"},
            extra_args={NO_PERSISTENCE: None},
            hooks={"Stop": [HookMatcher(hooks=[stopping])]},
        )

    @override
    async def run(self, request: TurnRequest) -> RawTurn:
        """Run one turn in Claude Code through the toolbox's guard, and report it."""
        allowed = [f"{TOOL_PREFIX}{spec.name}" for spec in request.toolbox.specs()]
        client = self.client(self.options(request.toolbox, allowed))
        try:
            await client.connect()
            try:
                messages = await received(client, request.prompt, allowed)
            finally:
                await client.disconnect()
        except CLINotFoundError as missing:
            message = (
                "Claude Code isn't installed: reinstall the `lup[claude]` extra, "
                "whose SDK bundles it"
            )
            raise RuntimeMissingError(message) from missing
        except ResultError as failed:
            raise Failure.of(failed, []).error() from failed
        except ClaudeSDKError as failed:
            message = f"Claude Code failed: {failed}"
            raise TurnError(message) from failed
        return finished(messages)
