# The library: asking an agent from code

`lup` (`packages/lup/src/lup/`) is what a project imports to ask Claude or Codex a question from code and get a typed answer back, and to test that code without reaching a real agent. The same package compiles a declaration for a terminal and runs it in a room (`docs/launch.md`), and holds the speaking tools a launched session reuses (`docs/inbox.md`); this doc is the ask.

## An ask, from a project

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

- **The answer is a tool call.** The ask serves `submit`, a tool whose input is `Forecast`: pydantic validates each call, then `cites_sources` reviews the typed value, and a refusal is the tool's answer, so the agent fixes its answer in the same turn. `ask(question, Forecast)` gives the plain `Submit(Forecast)`; `ask(prompt)` with no model returns the final message's text.
- **`result` is a `TurnResult[Forecast]`:** `output`, `usage` (tokens, and `cost_usd` where the runtime reports it), `duration`, `session_id`, `rejected` (the refused submissions, oldest first), and what the agent said beside its answer: `notes`, `frictions` and `how_it_went`.
- **`Codex(model=…)` in place of `Claude(...)`** changes nothing else: both are an `Agent`, which is what code that shouldn't care holds.
- **The test** runs the real ask, its layers, the tool and the hook; only the turn is scripted.

## The front door, and a declaration

`lup` binds `Agent`, `Claude`, `Codex`, `TurnResult`, `Usage`, `Rejection`, `SessionLayers`, `Recovery`, `Submission`, `LupError` and the ask's errors (`RealCallInTestError` is `lup.sessions.errors`'); `lup.tools` holds `lup_tool`, `Tool`, `Allow`, `Deny`, `Submit` and `Receipt`; `lup.testing` holds `FakeAgents`, `FakeCall` and `UnscriptedAskError`. Everything is async. Each declaration imports its runtime's SDK only inside `ask`, so `import lup` reaches neither SDK, and an ask on a runtime whose extra isn't installed raises `RuntimeMissingError` naming it.

`Claude` and `Codex` are frozen models, each a `Declaration` and so an `Agent` (`sessions/declaration.py`):
- **`model`,** passed as given; none runs the runtime's default.
- **`system_prompt`,** replacing the runtime's own, which describes tools an ask doesn't have; none sends an empty one.
- **`effort`,** in the runtime's own levels; none leaves it to the runtime.
- **`layers`** (*The layers an ask runs in*).

A field arrives with the piece that uses it, so a declaration holds nothing an ask doesn't read. Permissions are never a field: each adapter derives them from the turn's tools, so a declaration can't contradict them. `Agent` is an ABC with one abstract method, `ask`, so something a project writes to stand in for an agent inherits it.

## Typed answers: the output tool and its guard

- **Validated, then reviewed.** `Submit` (`tools/submit.py`) is an ordinary lup tool: its arguments are validated as sent, then each `before` hook runs on the typed value, returning `Allow()` or `Deny(reason)`, so the answer keeps its type through review.
- **A refusal answers the call:** every validation error at once, or the hook's reason. No new prompt is sent; the agent corrects itself with its own context. An accepted answer is told to end its turn.
- **The guard.** A typed turn can't end until an answer is accepted, or the agent calls `blocked` or `stop`; trying, it's told which tools to call, the same on both runtimes. Claude Code hears it through a `Stop` hook, Codex as another turn on the same thread.
- **Bounded.** `Submission.attempts` (3) counts rejected answers and refused endings together; past it, the ask raises `OutputMissingError` with every rejection. An agent that keeps submitting without trying to end is bounded only by a timeout, which has none by default.

It's one mechanism on both runtimes, and neither's native structured output: Codex's `outputSchema` shapes the final message, so nothing could refuse an answer inside the turn. A tool keeps hooks, and the guard keeps the agent in its turn, where a correction sent as a new prompt would start it over. Claude Code shows the tool as `mcp__lup__submit`, Codex as a dynamic tool `submit`, which a code-mode model calls from JavaScript.

## The speaking tools

`blocked`, `stop`, `note`, `friction` and `how_it_went` (`tools/speaking.py`) are served on every ask, typed or not. They act on nothing, so they're safe where an agent has no other tool, and they're the same tools a launched session speaks to the operator through (`docs/inbox.md`), so an agent's habit carries between the two.
- **`blocked(problem)`** ends the turn without an answer because the work can't go on; the ask raises `BlockedError` with the agent's words, so a caller tells "the agent says this can't be done" from a failure. It isn't retried, since asking again gets the same problem.
- **`stop(why)`** ends it by the agent's own choice; the ask raises `StoppedError`, so a caller tells "the agent chose to end" from "the agent can't". It isn't retried either.
- **`note(remark)`, `friction(got_in_the_way, …)` and `how_it_went(…)`** say something without ending the turn, read in `TurnResult.notes`, `.frictions` and `.how_it_went`, and kept on `OutputMissingError`, `BlockedError` and `StoppedError`, which end a turn without a result.

## Tools

`@lup_tool` (`tools/tool.py`) makes an async function taking one pydantic model a tool, returning a model (answered as JSON) or `str`; on a method, each instance's own tool. Its name is the function's, its description the docstring, which is required since it's what the model reads, and its summary the docstring's first line, 50 characters at most, standing alone: a session finding tools through tool search lists it. A `Tool` can carry `before` hooks, as `Submit` does; `@lup_tool` takes none. A tool runs in the caller's process; a project's own tools on an ask are #180.

**Serving tools over MCP** (`tools/serving.py`): what a server serves is a `Toolset`, an ABC. `tool_server` is an MCP server on `mcp`'s low-level `Server`, handing each call over with its arguments as sent, so lup validates, refuses and records a malformed call like any other, where the SDK's own server would refuse it before lup saw it. `serve` serves one MCP session over a connection's streams. Results are one text block, since Codex would show `structuredContent` in its place. Claude Code gets a turn's tools through lup's MCP server, in-process; Codex as the thread's dynamic tools, fixed for its life.

## The layers an ask runs in

`layers: SessionLayers` (`sessions/layers.py`) wraps every ask:

| Layer | Default | What it does |
|---|---|---|
| `timeout` | none | Bounds the whole ask, recovery and submission included; when it passes, the turn is interrupted and the ask raises `TurnTimeoutError` |
| `recovery` | 3 attempts, exponential wait up to 30 s | Retries `AgentUnavailableError`, each attempt a fresh turn, with tenacity's strategies, which combine. The runtimes retry API errors first; this catches what they gave up on |
| `submission` | `attempts=3` | Bounds rejected answers and refused endings together |
| `trace` | none | Appends each ask's `CallRecord` to the file, one JSON line each |

## No tools but lup's own, and nothing of the operator's

An ask from code can't run commands, touch files, reach the network or start agents: it can only call lup's tools. Each adapter configures its runtime for that, and its module docstring lists each setting and what it rests on.
- **Claude Code:** no built-in tools, skills, plugins or MCP server but lup's; every other call denied; no settings files, so the operator's and the project's hooks, `CLAUDE.md` and servers don't load; prompts delivered verbatim, so text from data can't attach a local file with `@path`. **Checked on every call:** the session's `init` message lists the tools and MCP servers it loaded, and any beyond lup's interrupt the turn with `ToolsPresentError` before the model runs; skills, plugins and commands it lists aren't checked.
- **Codex:** an ephemeral thread with no shell or file tools, its subagents off, a read-only sandbox, and lup's own Codex home, so the operator's configuration, servers, hooks and skills don't load; an app-server thread loads no `AGENTS.md`. On code-mode models every tool is reached through a JavaScript `exec` tool, beside `wait` and `request_user_input_async`, which no setting removes; none reaches a shell, files, the network or another agent (`docs/field-notes.md`, *The Codex SDK*), so they're accepted. **The declared gap:** Codex has no API listing a session's tools, so nothing checks them per call; a check by hand on each pinned version confirms the request carries only lup's tools.

**Out of the operator's history.** Claude Code runs with `--no-session-persistence`, so no transcript reaches their history, on their own config home and CLI login: a home of lup's own would need a copy of the login, which goes stale when Claude Code replaces its credentials file. Codex runs ephemeral threads in lup's own home (`$XDG_STATE_HOME/lup/codex`), whose `auth.json` links to the operator's, so a refresh writes through to the one real copy. The operator's CLI login fits their own use; a product other people use needs an API key (#181).

## Errors

The errors lup raises descend from `LupError`, so one `except` catches them, though an invalid declaration raises pydantic's `ValidationError` when it's made. An ask's errors are classified from what the runtime reports in structured form, never its message, so a caller branches on the type; each adapter's docstrings give its mapping.

| Error | When | Retried |
|---|---|---|
| `TurnError` | The base of the ask's errors; raised itself for a failure not classified below, with what the runtime said | No |
| `AgentUnavailableError` | The model is out of reach for a while: overload, a rate limit, a server error, a dropped connection | Yes |
| `UsageLimitReachedError` | The account's usage window is spent; `reset_at` where the runtime said | No |
| `AuthMissingError` | No usable login, or the login refused | No |
| `OutputMissingError` | No answer accepted within `submission.attempts`, with every rejection | No |
| `BlockedError`, `StoppedError` | The agent called `blocked` or `stop`, with its words | No |
| `ToolsPresentError` | The session loaded tools beyond lup's | No |
| `TurnTimeoutError` | The timeout passed and the turn was interrupted; also a `TimeoutError` | No |
| `RuntimeMissingError` | The runtime's extra isn't installed, or no Claude Code is found at all; a `LupError`, not a `TurnError` | No |
| `RealCallInTestError` | A test reached a real agent (*Testing*); a `LupError` | No |

**The call record.** With `layers.trace` set, every ask, answered or failed, appends one `CallRecord` (`observability/trace.py`): the runtime and model, when and how long, the prompts, the output or the error, the rejections, what the agent said beside its answer, and the usage, all in full. It's derived from the result or the error and the request, so the two can't disagree. Codex reports no cost.

## Testing: the fake and the guard

**The fake replaces the adapter, not the agent** (`testing/fake.py`): a test's `Claude(...)` goes through the real `ask`, with its layers, tools, hooks and record, and only the turn is scripted. Nothing is patched, and no project writes its own stub (live-translator's took about 70 lines).
- `answer(Output, value, …)` queues an answer for the next ask of that output type, submitted through the real tool and its hooks, and `answer_text(text, …)` the next untyped one's; each takes what the agent says beside it.
- `reject_then(Output, invalid, value)` queues a refused submission, then the accepted one.
- `blocked(Output, problem)` and `stop(Output, why)` queue the agent ending without an answer; `fail(Output, error)` makes the next attempt raise.
- `calls` lists every attempt: the declaration, the prompt, the output model.

The fake stands in for the adapter, under the recovery layer, so a scripted `AgentUnavailableError` is retried like a real one, taking the next script.

An ask nothing scripted raises `UnscriptedAskError`, naming the type and the prompt.

**The guard** is on in every test session that has `lup` installed, through its pytest plugin: outside `fake_agents`, every declaration's turns raise `RealCallInTestError`, and each adapter checks it before starting a runtime; connections are refused except to loopback and Unix sockets (`pytest-socket`); and without `lup[testing]`, the plugin stops the session and names the extra rather than run unguarded. Tests that reached real agents were slow and flaky, 20 minutes a test in one project.

## The adapters

Each is the only module importing its SDK, and its docstring holds what it relies on, read in the SDK's source and checked against the runtime it pins (`docs/field-notes.md`, *The library's asks*).
- **`ClaudeAdapter`** runs each turn in a Claude Code process of its own through `ClaudeSDKClient`, the SDK's one client that can interrupt. Its `Stop` hook carries the guard; Claude Code honours 8 blocks in a row, so with up to 8 attempts, 3 by default, the submission attempts run out first.
- **`CodexAdapter`** starts a `codex app-server` of its own per ask, and closes it whatever happens. It drives the SDK's lower `CodexClient`, the one taking a handler for Codex's requests, on the SDK's reader thread, handing each tool call to the ask's event loop. Codex's hooks are commands in files, not callbacks, so the adapter guards the end itself, continuing the same thread.
- **Both** interrupt a cancelled turn before the cancellation goes on, and take their client factory as a field, so their tests drive the real server, hook and handler on a scripted client.

## Repository layout and packages

A uv workspace with one lock file: `packages/lup/`, the library, and `packages/lup-dev/`, the environment, which depends on it; `packages/lup-dashboard/` beside them. The library imports nothing of the environment, but in the environment side of a module kept in its directory (`github/`, `transcripts/`), which the import contract lists. Runtime-neutral code lives under `sessions/` and `tools/`; everything a runtime spells its own way, in its adapter under `adapters/`.
- **Dependencies:** `pydantic`, `pydantic-settings`, `tenacity`, `mcp`, `tomlkit`. **Extras:** `lup[claude]`, `lup[codex]`, `lup[testing]`. Each SDK ships its runtime's binary, a few hundred MB, so a project installs only the side it asks through, and the test tooling is an extra too; every other library is a dependency.
- **Pinned runtimes.** The lock file pins each SDK and the runtime it bundles, and the guarantees above are checked against those versions. A Codex ask runs the binary its SDK bundles; a Claude ask runs the bundled CLI where it's there, and the SDK falls back to a `claude` on the `PATH` where it isn't (#185).
- **Python 3.14 or later,** for lazily evaluated annotations: earlier, every file would need `from __future__ import annotations`, which turns them into strings, and pydantic then can't resolve a model naming one defined in an enclosing function.

What's coming: a project's own tools (#180), sessions held open across asks (#119), the connection (#181), checked model ids (#182), rooms from code (#158), events (#183), a distribution per module (#113).
