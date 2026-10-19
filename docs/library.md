# The library: asking an agent from code

`lup` (`packages/lup/src/lup/`) is what a project imports to ask Claude or Codex a question from code and get a typed answer back, and to test that code without reaching a real agent. The same package compiles a declaration for a terminal and runs it in a room (`docs/launch.md`), and holds the tools a launched session gets (`docs/host-tools.md`); this doc is the ask.

## What we have

### An ask, from a project

```python
# forecasts.py
from datetime import timedelta
from pathlib import Path

from lup import Agent, BlockedError, Claude, SessionLayers
from lup.tools import Allow, Deny, Submit
from pydantic import BaseModel


class Forecast(BaseModel):
    probability: float
    sources: list[str]


async def cites_sources(forecast: Forecast) -> Allow | Deny:
    if not forecast.sources:
        return Deny(reason="Cite at least one source for the probability.")
    return Allow()


forecaster = Claude(
    model="opus",
    system_prompt="You forecast the weather for the question you're given.",
    effort="low",
    layers=SessionLayers(
        timeout=timedelta(minutes=2), trace=Path("traces/forecasts.jsonl")
    ),
)


async def forecast(question: str, agent: Agent = forecaster) -> Forecast | None:
    try:
        result = await agent.ask(question, Submit(Forecast, before=[cites_sources]))
    except BlockedError:
        return None  # the agent called `blocked`: it says the question can't be answered
    return result.output  # a Forecast; result.notes, .rejected and .usage sit beside it
```

```python
# test_forecasts.py
import asyncio

from lup.testing import FakeAgents

from forecasts import Forecast, forecast


def test_a_forecast_must_cite_its_sources(fake_agents: FakeAgents) -> None:
    cited = Forecast(probability=0.7, sources=["Met Office"])
    fake_agents.reject_then(Forecast, {"probability": 0.7, "sources": []}, cited)

    assert asyncio.run(forecast("Will it rain in London tomorrow?")) == cited
    assert fake_agents.calls[0].prompt == "Will it rain in London tomorrow?"
```

- **The answer is a tool call.** The ask serves `submit`, a tool whose input is `Forecast`: pydantic validates each call, then `cites_sources` reviews the typed value, and a refusal is the tool's answer, so the agent fixes its answer in the same turn. `ask(question, Forecast)` gives the plain `Submit(Forecast)`.
- **Every ask also serves the speaking tools** (*The speaking tools*): `blocked` and `stop` end the turn without an answer, raising `BlockedError` or `StoppedError`; `note`, `friction` and `how_it_went` are read in `result.notes`, `.frictions` and `.how_it_went`.
- **`result` is a `TurnResult[Forecast]`:** `output`, `usage` (tokens, and `cost_usd` where the runtime reports it), `duration`, `session_id`, `rejected` (the refused submissions, oldest first), `notes`, `frictions` and `how_it_went`. `ask(prompt)` with no model returns the final message's text, a `TurnResult[str]`.
- **`Codex(model="gpt-6.1-sol", ...)` in place of `Claude(...)`** changes nothing else: both are an `Agent`, which is what code that shouldn't care holds.
- **The test** runs the real ask, its layers, the tool and the hook; only the turn is scripted. The hook refuses the first submission, so `rejected` holds it.

A project's own tools can't be served on an ask yet (*Where it's going*).

### The front door

`lup/__init__.py` binds `Agent`, `Claude`, `Codex`, `TurnResult`, `Usage`, `Rejection`, `SessionLayers`, `Recovery`, `Submission`, `LupError` and the ask's errors; `lup.tools` holds `lup_tool`, `Tool`, `Allow`, `Deny`, `Submit` and `Receipt` (with `lup_hook` and `Hook`, for a launched session's modules, `docs/declaration.md`); `lup.testing` holds `FakeAgents`, `FakeCall` and `UnscriptedAskError`. Everything is async.

Each declaration imports its runtime's SDK inside `ask`, under `needs_extra` (`sessions/errors.py`). So `import lup` reaches neither SDK, a declaration compiles for a terminal without its extra, and an ask on a runtime whose extra isn't installed raises `RuntimeMissingError` saying which to install.

### What a declaration holds

`Claude` and `Codex` (`adapters/<runtime>/__init__.py`) are frozen models, each a `Declaration` (`sessions/declaration.py`) and so an `Agent`:
- `model`: the runtime's model id, passed as given. None passes none, so the runtime's default runs (an ask loads none of the operator's settings to choose another), and the trace records none.
- `system_prompt`: replaces the runtime's own prompt, which describes tools an ask doesn't have; none sends an empty one.
- `effort`: in the runtime's own levels (`Effort`, beside each declaration); none leaves it to the runtime.
- `layers` (*The layers an ask runs in*).

A field arrives with the piece that uses it, so a declaration holds nothing an ask doesn't read: no tools, connection or history yet. Permissions are never a field: each adapter derives them from the turn's tools, so a declaration can't contradict them.

`Agent` (`sessions/surface.py`) is an ABC with one abstract method, `ask`, whose overloads type the result by the output given. Something a project writes to stand in for an agent inherits it, as every interface lup owns is an ABC (`docs/conventions.md`, *Interfaces*).

### How an ask runs

A declaration's `ask` builds its runtime's adapter from its own fields and hands the ask to `Asking` (`sessions/declaration.py`), the behaviour every declaration shares. The adapter takes the fields, not the declaration, since the declaration's module imports the adapter and pydantic reads field types at runtime: an adapter holding a `Claude` would import it back in a cycle.

`Asking` gives each attempt a fresh `Toolbox` (`sessions/submission.py`) of the speaking tools and, on a typed ask, `submit`, and runs it on the adapter `seam` chooses (`sessions/contract.py`): the declaration's own, unless a test set the fake. An `Adapter` takes a `TurnRequest` (prompt, toolbox, output model) and returns a `RawTurn` (final text, usage, session id). It serves the toolbox's specs, routes each call to `Toolbox.call`, asks `Toolbox.end` when the model tries to end its turn, and raises the errors of *Errors*.

The calls the toolbox records are the one source of what a turn said: the last accepted `submit` is the answer, the refused ones are `rejected`, the last `blocked` or `stop` call why the turn ended without one, and the other speaking tools' calls what the agent said beside it. A turn that both answered and called `blocked` or `stop` raises.

### Typed answers: the output tool and its guard

- **Validated, then reviewed.** `Submit` (`tools/submit.py`) is an ordinary lup tool: the arguments are validated as sent, then each `before` hook runs in order on the typed value, returning `Allow()` or `Deny(reason)`. Review is a hook on the tool, so the answer keeps its type through it.
- **A refusal answers the call:** every validation error at once, or the hook's reason, as `Refused: …`, marked as an error. No new prompt is sent; the agent corrects itself with its own context. An accepted answer gets a `Receipt` ("Your answer is accepted. End your turn.").
- **The guard.** A typed turn can't end until an answer is accepted, or the agent calls `blocked` or `stop`. `Toolbox.end` decides, the same on both runtimes: `End`, `GiveUp`, or `KeepGoing` with a reason naming the tools as the model sees them ("Call the `mcp__lup__submit` tool with your final answer, `mcp__lup__blocked` if it can't be answered, or `mcp__lup__stop` to stop by your own choice: your turn can't end until one is accepted."). Claude Code hears it through a `Stop` hook, Codex as another turn on the same thread.
- **Bounded.** `Submission.attempts` (3) counts rejected answers and refused endings together, checked when the model tries to end. Past it, the turn ends and the ask raises `OutputMissingError` with every rejection. An agent that keeps submitting without trying to end is bounded by the timeout.

It's one mechanism on both runtimes, and neither's native structured output: Codex's (`outputSchema`) shapes the final message, so nothing could refuse an answer inside the turn. A tool keeps hooks, and the guard keeps the agent in its turn, where a correction sent as a new prompt would start it over.

The tool is `submit`. Claude Code shows it as `mcp__lup__submit`, a tool of lup's MCP server `lup` (`SERVER`, `TOOL_PREFIX` in `adapters/claude/runtime.py`); Codex as a dynamic `function` tool `submit` with no namespace, which a code-mode model calls from JavaScript as `await tools.submit({...})`.

### The speaking tools

`blocked`, `stop`, `note`, `friction` and `how_it_went` (`tools/speaking.py`, `SPEAKING`) are served on every ask, typed or not. They act on nothing, so they're safe where an agent has no other tool. What the last three take is kept on the result, and on `OutputMissingError`, `BlockedError` and `StoppedError` where there's none.
- **`blocked(problem)`** stops the turn without an answer because the work can't go on: the question can't be answered, something needed is missing, an instruction seems wrong. The ask raises `BlockedError` with the agent's words, so a caller tells "the agent says this can't be done" from a failure. It isn't retried: asking again gets the same problem.
- **`stop(why)`** stops the turn without an answer by the agent's own choice: it's done and nothing more is worth doing, or it would rather not go on. The ask raises `StoppedError`, so a caller tells "the agent chose to end" from "the agent can't". It isn't retried.
- **`note(remark)`** attaches an assumption, a doubt or a counterargument without ending the turn, read in `TurnResult.notes`.
- **`friction(got_in_the_way, trying, would_change)`** says what got in the agent's way, at the moment it does, the exact command and message where there's one; only the first is required. Read in `TurnResult.frictions` (`Friction`).
- **`how_it_went(got_in_the_way, smooth, would_change, felt)`** says how the work went as a whole, once near its end, every field optional: none says nothing was notable. Read in `TurnResult.how_it_went` (`HowItWent`), the last where it's called twice.

### Tools

`@lup_tool` (`tools/tool.py`) makes an async function taking one pydantic model a tool, returning a model (answered as JSON) or `str` (answered in those words); on a method, each instance's own tool (`Method`). Its name is the function's and its description the docstring, required since it's what the model reads. Its summary is the docstring's first line, standing alone, 50 characters at most, which a session finding tools through tool search lists (`ToolSpec.summary`); read with `pydoc.splitdoc`, so a first sentence wrapped onto a second line is refused rather than cut. Anything else raises `ToolError`, for a `Tool` or `ToolSpec` made directly too. Any tool can carry `before` hooks. A tool runs in the caller's process.

**Serving tools over MCP** (`tools/serving.py`): what a server serves is a `Toolset`, an ABC (`specs()`, `call(name, arguments) -> Answer`). A turn's `Toolbox` is one; the tools a launch gives its session another (`docs/host-tools.md`).
- `tool_server(toolset, name="lup")` is an MCP server on `mcp`'s low-level `Server`, handing each call over with its arguments as sent, so lup validates, refuses, counts and records a malformed call like any other; the SDK's `create_sdk_mcp_server` would refuse it before lup saw it.
- `serve(toolset, reader, writer, name="lup")` serves one MCP session over a connection's streams, newline-delimited JSON-RPC as stdio carries it, so a stdio server that only bridges to a socket reaches a toolset served there.
- Results are `content` only, one text block, never `structuredContent`, which Codex would show in its place (`docs/field-notes.md`, *MCP in a launched session*).

Claude Code gets a turn's tools through lup's MCP server, in-process. Codex gets them as the thread's dynamic tools, declared when the thread starts and fixed for its life, each call arriving as an `item/tool/call` request.

### The layers an ask runs in

`layers: SessionLayers` (`sessions/layers.py`) wraps every ask:

| Layer | Field | Default | What it does |
|---|---|---|---|
| Timeout | `timeout: timedelta \| None` | none | Bounds the whole ask, recovery and submission included; when it passes, the turn is interrupted and the ask raises `TurnTimeoutError` |
| Recovery | `recovery: Recovery` | `stop_after_attempt(3)`, `wait_exponential(multiplier=1, max=30)` | Retries `AgentUnavailableError`, each attempt a fresh turn, with tenacity's strategies, which combine (`stop_after_attempt(5) \| stop_after_delay(120)`). The runtimes retry API errors first; this catches what they gave up on |
| Submission | `submission: Submission` | `attempts=3` | Bounds rejected answers and refused endings together |
| Trace | `trace: Path \| None` | none | Appends each ask's `CallRecord` to the file, one JSON line each |

### No tools but lup's own

An ask from code can't run commands, touch files, reach the network or start agents: it can only call lup's tools. Each adapter configures its runtime for that (the module docstrings list each setting and what it rests on).
- **Claude Code:** no built-in tools, skills or plugins, and no MCP server but lup's; lup's tools pre-approved and every other call denied (`dontAsk`); no settings files, so the operator's and the project's hooks, `CLAUDE.md` and servers don't load, and auto memory off by its variable; prompts delivered verbatim, so text from data can't attach a local file with `@path`. **Checked on every call:** the session's `init` message lists the tools and servers it loaded, and anything beyond lup's interrupts the turn with `ToolsPresentError` before the model runs. A turn whose `init` never came raises `TurnError`, since its check never ran.
- **Codex:** an ephemeral thread with no environment (no shell, no file tools), Codex's subagents off, approvals never asked, a read-only sandbox; `LAUNCH`'s overrides turn off web search, skills, each built-in feature that brings a tool and the instructions describing them; lup's own Codex home, so the operator's configuration, servers, hooks and skills and a project's `AGENTS.md` don't load. A question for the user is answered that no one can answer, pointing at `blocked`; any other request from Codex fails the ask.
  - **Code mode.** On `code_mode_only` models, the default `gpt-6.1-sol` among them, every tool is reached through a JavaScript `exec` tool, beside `wait` (which polls a running cell) and `request_user_input_async`, and no setting removes them. None of the three reaches a shell, files, the network or another agent (`docs/field-notes.md`, *The Codex SDK*), so code-mode models are accepted, with the code-mode host on, since lup's tools are out of reach without it.
  - **The declared gap:** Codex has no API listing a session's tools, so nothing checks them per call; a check by hand on each pinned version confirms the model's request carries only lup's tools.

### Out of the operator's history

An ask persists no session and loads none of the operator's settings.
- **Claude Code:** `--no-session-persistence`, so no transcript reaches their history or resume list. It runs on the operator's own config home and CLI login: a home of lup's own would need a copy of the login, which goes stale as Claude Code replaces its credentials file on a refresh, and with nothing loaded and nothing kept the default home serves.
- **Codex:** ephemeral threads, in lup's own home, `$XDG_STATE_HOME/lup/codex` (`adapters/codex/layout.py`), whose `auth.json` is a symbolic link to the operator's (`$CODEX_HOME/auth.json`). Codex rewrites that file in place, so a refresh writes through to the one real copy, and a logout from lup's home removes only the link. Credentials stay in the file store, since under `keyring` or `auto` a refresh deletes `auth.json`. The login is checked (`account/read`) before the thread starts; without one, `AuthMissingError` names both homes.

The operator's CLI login fits their own use; a product other people use needs an API key (`docs/field-notes.md`, *Claude Code 2.1.291* and *The library's asks*), which comes with the connection (*Where it's going*).

### Errors

Every error lup raises descends from `LupError` (`lup/errors.py`), so one `except` catches them all (`docs/conventions.md`, *Errors*). An ask's errors (`sessions/errors.py`) are classified from what the runtime reports in structured form, never its message, so a caller branches on the type; each adapter's mapping is in its module's docstring.

| Error | When | Retried |
|---|---|---|
| `TurnError` | The base of the ask's errors; raised itself for a failure not classified below, carrying what the runtime said | No |
| `AgentUnavailableError` | The model is out of reach for a while: overload, a rate limit, a server error, a connection that failed or dropped | Yes |
| `UsageLimitReachedError` | The account's usage window is spent; `reset_at` where the runtime said | No |
| `AuthMissingError` | No usable login, or the login refused | No |
| `OutputMissingError` | No answer accepted within `submission.attempts`; `rejected`, `notes`, `frictions`, `how_it_went`, `usage` | No |
| `BlockedError` | The agent called `blocked`; `problem`, `notes`, `frictions`, `how_it_went`, `usage` | No |
| `StoppedError` | The agent called `stop`; `why`, `notes`, `frictions`, `how_it_went`, `usage` | No |
| `ToolsPresentError` | The session loaded tools beyond lup's; `tools` lists what it loaded | No |
| `TurnTimeoutError` | The timeout passed and the turn was interrupted; also the built-in `TimeoutError` | No |
| `RuntimeMissingError` | The runtime's extra isn't installed, or Claude Code's bundled CLI is missing; a `LupError`, not a `TurnError` | No |
| `RealCallInTestError` | A test reached a real agent (*Testing*); a `LupError` | No |

Outside an ask: `ToolError` (`lup.tools.tool`) and `UnscriptedAskError` (`lup.testing.fake`).

### The call record

With `layers.trace` set, every ask, answered or failed, appends one `CallRecord` (`observability/trace.py`): the runtime, the model named, the start and duration, the prompt and system prompt, the output (the model as JSON, or the text) or the error's type and message, the rejections, the notes, the frictions, how it went and the usage, all in full. A failed ask keeps what the agent said and the usage where its turn ran, and the rejections on `OutputMissingError`. The record is derived from the result or the error, and the request, so the two can't disagree. Codex reports no cost.

### Testing: the fake and the guard

**The fake replaces the adapter, not the agent** (`testing/fake.py`): a test's `Claude(...)` goes through the real `ask`, with its layers, tools, hooks and record, and only the turn is scripted, its answers and what the agent says beside or instead of them going through the real tools. It stands in at the seam, so nothing is patched, and no project writes its own stub (live-translator's took about 70 lines, `docs/field-notes.md`, *From the downstream projects*).
- `answer(Output, value, notes=[...], frictions=[...], how_it_went=...)` queues an accepted answer for the next ask of that output type; `answer_text(text, ...)` the next untyped one's.
- `reject_then(Output, invalid, value)` queues a refused submission, then the accepted one.
- `blocked(Output, problem, ...)` and `stop(Output, why, ...)` queue the agent ending without an answer (`Output` is `None` for an untyped ask); `fail(Output, error)` makes the next such ask raise `error`.
- `calls` lists every ask as a `FakeCall`: the declaration, the prompt, the output model.

Scripts match by output type, first queued first; an ask with none raises `UnscriptedAskError` naming the type and the prompt. A fake turn reports zero usage and the session ids `fake-1`, `fake-2`, and so on.

**The guard** is on in every test session that has `lup` installed, through its pytest plugin (a `pytest11` entry point, `testing/plugin.py`):
- outside `fake_agents`, every declaration's turns raise `RealCallInTestError`, naming the fixture; the plugin also sets `guarded`, which each adapter's client factory checks before it starts a runtime, so an adapter built directly refuses too;
- connections are refused except to loopback (unless the project names its hosts) and Unix sockets, through `pytest-socket`, whose `enable_socket` marker lifts it for a test;
- without `lup[testing]`, the plugin stops the session and names the extra, rather than run unguarded.

### The adapters

Each is the only module importing its SDK, and its docstring holds what it relies on, read in the SDK's source and checked against the runtime it pins (and `docs/field-notes.md`, *The Claude Agent SDK 0.2.165*, *The Codex SDK*, *The library's asks*).
- **`ClaudeAdapter`** (`adapters/claude/runtime.py`) runs each turn in a Claude Code process of its own through `ClaudeSDKClient`, the SDK's one client that can interrupt. Its `Stop` hook answers `decision: block` with the guard's reason; Claude Code honours 8 blocks in a row, so the submission attempts run out first. A failed turn raises nothing in the SDK, so the adapter classifies the result's status and the assistant messages' errors. Usage includes Claude Code's cost.
- **`CodexAdapter`** (`adapters/codex/runtime.py`) starts a `codex app-server` of its own per ask, and closes it whatever happens. It drives the SDK's lower `CodexClient`, the one that takes a handler for Codex's requests to the client; the handler runs on the SDK's reader thread and hands each tool call to the ask's event loop, kept free by running every blocking client call in a worker thread. Codex's hooks are commands in files, not callbacks, so the adapter guards the end itself, continuing the same thread with the reason; the thread keeps its history, so the prompt isn't sent again. A spent window's reset comes from the last rate-limit report, which arrives outside the turn's stream. Usage is the thread's running total, with cached input counted apart as on Claude Code.
- **Both** interrupt a cancelled turn before the cancellation goes on, and take their client factory as a field (`client`, `connect`), so their tests drive the real server, hook and handler on a scripted client.

### Modules

| Module (`packages/lup/src/lup/`) | What it holds |
|---|---|
| `__init__.py` | The front door |
| `types.py` | `Model`, `MutableModel` and `Settings`, the bases every model starts from; `JsonObject` |
| `errors.py` | `LupError` |
| `sessions/surface.py` | `Agent` |
| `sessions/declaration.py` | `Declaration`, the fields every declaration has; `Asking`, an ask inside its layers |
| `sessions/contract.py` | `Adapter`, `TurnRequest`, `RawTurn`; the seam and `guarded` |
| `sessions/layers.py` | `SessionLayers`, `Recovery`, `Submission` |
| `sessions/submission.py` | `Toolbox`: one turn's tools, the calls made to them, and the guard |
| `sessions/results.py` | `TurnResult`, `Usage`, `Rejection`, `Friction`, `HowItWent` |
| `sessions/errors.py` | The ask's errors, `RuntimeMissingError`, `RealCallInTestError`; `needs_extra` |
| `tools/tool.py` | `@lup_tool`, `Tool`, `Method`, `AgentTool`, `ToolSpec` and `summary_of`; `Allow`, `Deny`; `ToolError` |
| `tools/submit.py` | `Submit` and its `Receipt` |
| `tools/speaking.py` | `blocked`, `stop`, `note`, `friction` and `how_it_went` |
| `tools/serving.py` | `Toolset`, `Answer`, `tool_server`, `serve` |
| `observability/trace.py` | `CallRecord` |
| `testing/fake.py`, `testing/plugin.py` | `FakeAgents`, `FakeCall`, `UnscriptedAskError`; the pytest plugin, its guard and `fake_agents` |
| `adapters/claude/__init__.py`, `adapters/codex/__init__.py` | `Claude` and `Codex`, with their `Effort` |
| `adapters/claude/runtime.py`, `adapters/codex/runtime.py` | `ClaudeAdapter`, `CodexAdapter` (with `LAUNCH`) |
| `adapters/codex/layout.py`, `adapters/codex/settings.py` | `CodexLayout`, lup's Codex home and the login it links to; `CodexSettings`, the variables it reads |

Beside the ask, in other docs: the terminal a declaration compiles to (`sessions/terminal.py`, each adapter's `terminal.py`, `adapters/claude/layout.py` and `settings.py`) and rooms (`rooms/`), in `docs/launch.md`; the bridge to lup's tool server (`sessions/bridge.py`) and the GitHub tools (`github/`), in `docs/host-tools.md`; transcripts (`transcripts/`), in `docs/resume-guidance.md`; `@lup_hook` (`tools/hook.py`), in `docs/declaration.md`; and running a program (`programs.py`).

Runtime-neutral code lives under `sessions/` and `tools/`; everything a runtime spells its own way lives in its adapter under `adapters/` (`docs/conventions.md`, *Imports and boundaries*), named so rather than `providers`, which also means a model provider or an endpoint. Import contracts in the root `pyproject.toml` keep each SDK in its adapter, and anything inside `lup` from importing its front door, which imports the adapters. The tests are in `packages/lup/tests/`.

### Repository layout and packages

A uv workspace with one lock file, whose packages are versioned and installed separately: `packages/lup/`, the library, and `packages/lup-dev/`, the environment (`lup_dev`), which depends on it. The library imports nothing of the environment but in a module's environment side kept in its directory of `lup` (`github/`, `transcripts/`), which the import contract lists.

**Dependencies:** `pydantic`, `pydantic-settings`, `tenacity`, `mcp`, `tomlkit`. **Extras:** `lup[claude]` (`claude-agent-sdk`), `lup[codex]` (`openai-codex`), `lup[testing]` (`pytest`, `pytest-socket`). Each SDK ships its runtime's binary, a few hundred MB (`docs/field-notes.md`, *The library's asks*), so a project installs only the side it asks through; that's the one reason for an extra, so every other library is a dependency, even one a single adapter uses. lup's own development group installs all three, since every shared construct is tested on both runtimes.

**Pinned runtimes.** An ask runs the runtime its SDK bundles, not whatever is on `PATH`, so the lock file pins it: claude-agent-sdk 0.2.165 bundles Claude Code 2.1.294, and openai-codex 0.162.0 pins codex-cli 0.162.0. The guarantees above are checked against those versions.

**Python 3.14 or later,** for lazily evaluated annotations: an earlier Python would need `from __future__ import annotations` in every file, which turns them into strings, and pydantic then fails on names imported only for type checking and on models defined inside functions.

## Where it's going

- **A project's own tools on an ask:** a `tools` field on the declaration, taking `lup_tool`s and their groups, each tool saying whether it runs in the caller's process or inside a room; neutral hooks on the runtime's own tools; a large result written to a file, the agent given its path and a preview; a third-party MCP server passed through. On Codex a project's tool could share `submit`'s name, which Codex's namespaced dynamic tools can keep apart.
- **Conversations:** `async with agent.open()` holding a session across asks, its history from the runtime's own record with lup keeping a scrubbed copy; each turn awaited for its result or iterated for its content, and interruptible. Kept sessions run under a config home of their own. Forking at a turn needs a turn id, which `TurnResult` doesn't carry yet.
- **The connection:** an endpoint and an API key as one value, given when a client is made, for products other people use.
- **Checked model ids,** with portable tiers, and an effort a model can't take refused when the declaration is made.
- **Rooms from code:** a `Room` that's an `Agent`, asking and spawning in a container (`docs/launch.md`); runs, durable work outliving the call that started it, and the outcome loop; budgets shared across processes.
- **Events** from anything long-running, which the dashboard reads beside the call records; the capability check, which takes in Codex's hand-run tool check.
- **A distribution per module:** the library core requiring its modules, each runtime and the test kit modules of their own, pulled in by the same extras.
