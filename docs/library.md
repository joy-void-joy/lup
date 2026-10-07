# The library, first slice: asking an agent from code

**One sentence:** `lup` lets production code ask Claude or Codex a question and get a typed answer back, and lets that code's tests run without reaching a real agent.

This slice is the first item of the build order in `DESIGN.md`. It covers:
- the `Claude` and `Codex` declarations and their `ask`;
- typed answers through `lup_submit`, a lup tool that validates and guards each answer;
- the layers an ask runs in: timeout, recovery, submission, trace;
- the guarantee that a call has no tools but lup's own;
- the fake agent and the test guard.

Later slices add, on the same declarations:
- conversations (`open`), with `Conversation` and `Turn`;
- project tools, as tool groups;
- containers and mounts;
- rooms, `spawn`, `launch`;
- runs and the outcome loop;
- `SharedBudget`;
- events for the dashboard.

Each section below says what the first lup did, and whether this keeps, reshapes or drops it. The first lup's code is evidence, read under `lup-legacy`; nothing is copied.

## Who it serves first

live-translator moves onto this slice as soon as it lands. It needed five things from the first lup, each of which cost it work:

| Need | What it had to do in the first lup | In this slice |
|---|---|---|
| A provider switch | Two config classes and two factories (`agent/core.py:45-92`) | `Claude(...)` and `Codex(...)` both satisfy `Agent` |
| A timeout | `asyncio.timeout` around the call | `layers.timeout` |
| A trace | Its own `TraceLogger` | `layers.trace` |
| A guarantee of no tools | Built upstream first (#188, #433), then asserted in its own test | The default, checked on every Claude call |
| A fake for tests | About 60 lines of stubs per test module | The `fake_agents` fixture |

## The public API

```python
from datetime import timedelta
from pathlib import Path
from lup import Claude, Codex, SessionLayers

translator = Claude(
    model="opus",
    system_prompt=PROMPT,
    effort="low",
    layers=SessionLayers(timeout=timedelta(seconds=30), trace=Path("traces/translator.jsonl")),
)

result = await translator.ask(segment.model_dump_json(), Translations)
result.output            # Translations
result.usage.cost_usd    # where the runtime reports it
```

- **`ask(prompt, output, gate=None)` returns a `TurnResult[T]`.** Its `output` is an instance of the output model, or the answer's text when no model is given.
- **A failure is always an error,** never an empty result.
- **`gate` is an optional async check on the validated answer.** It returns a verdict: accepted, or rejected with a message the agent reads.
- **A runtime-neutral protocol.** Code that shouldn't care which runtime it gets takes an `Agent`, the protocol both declarations satisfy.

```python
from lup import Agent

def translator_for(settings: Settings) -> Agent:
    match settings.runtime:
        case "claude":
            return Claude(model="opus", system_prompt=PROMPT)
        case "codex":
            return Codex(model="gpt-6", system_prompt=PROMPT)
```

Testing it:

```python
from lup.testing import FakeAgents

async def test_translates_a_segment(fake_agents: FakeAgents) -> None:
    fake_agents.answer(Translations, Translations(lines=["Bonjour"]))

    result = await translate(segment)

    assert result.lines == ["Bonjour"]
    assert fake_agents.calls[0].prompt == segment.model_dump_json()
```

## What the first lup did, area by area

| Area | The first lup | Here | Why |
|---|---|---|---|
| Front door | `lup/__init__.py` bound the neutral names and resolved `Claude`, `Codex` and the launch vocabulary on first access, through one table; a `TYPE_CHECKING` block gave checkers the real classes; nothing inside the library imported from it | **Kept** | `import lup` reaches neither SDK until an agent is named. That is also what makes the runtimes optional extras |
| Neutral code and adapters | `sessions/` was provider-neutral; `providers/claude/` and `providers/codex/` each held a declaration and its runtime, plus much launch and home machinery | **Kept, as `adapters/`.** The launch, home, profile and preference machinery belongs to the environment | `DESIGN.md` says "an adapter per runtime". In the first lup, "provider" also meant model providers and compatible endpoints (`routing.py`) |
| The declaration | 36 fields on `Claude`, mixing what production code needs (model, prompt, tools, layers) with what only developing a project needs (plugin, policy, identity, companions, profiles) | **Reshaped:** `model`, `system_prompt`, `effort`, `layers` in this slice. Every other field is placed in *Where the first lup's fields go* | `DESIGN.md`'s split between what production code imports and what development uses |
| Default tools | `builtin="web"` and `permission_mode="bypassPermissions"`: a bare `Claude(...)` could search and fetch | **Reshaped:** no tools but lup's own, checked per call on Claude | live-translator had to get "no tools" built upstream before it could rely on it |
| Protocols | Structural `Agent`, `Conversation`, `Turn` in `sessions/surface.py`, satisfied by having the methods | **Kept.** `Agent` now; `Conversation` and `Turn` arrive with conversations | Code naming no runtime, and the fake, satisfy them without registering |
| The result | `TurnResult[T]`: `output`, `messages`, `blocks`, `usage`, `duration`, `identifiers`; failures only as errors | **Kept, slimmer:** `output`, `usage`, `duration`, `session_id`, `rejected`. `messages` arrives with project tools, when a turn has something in it | Callers outside the library read `.output` about 25 times, `.usage` 8, `.duration` 6, `.session_id` 5 |
| Typed output | Claude: a `submit_output` tool that validated, ran a gate and answered `accepted: false` with the reason. Codex: native strict `outputSchema`, a string carrier for schemas outside the strict subset, then the same validation. A turn ending without a valid answer was re-sent with "Correction required: …" appended, twice | **Reshaped:** one lup tool, `lup_submit`, on both runtimes. Native structured output is used on neither. Instead of a re-send, a guard won't let the turn end without an accepted answer | ADR-010 kept one mechanism per turn because two raced. Here it's one mechanism for both runtimes. Codex's native output isn't a tool call, so nothing could reject it inside the turn, and its strict subset is what needed the carrier |
| Layers | `SessionLayers`, one field on the agent: timeout, budget, recovery, correction, continuation, persistence, tracing, usage, display, serialization and session wrappers. Middleware switched event streams between correction cycles | **Reshaped:** the same single field, with four layers: timeout, recovery, submission, trace | Declared on the agent rather than stacked by hand was right. The rest arrives when something needs it, conversations first |
| Retries | `with_retry` on tenacity (`execution/resilience/retry.py`), and `RecoveryConfig(retries=1)` in the middleware | **Kept on tenacity.** `Recovery` takes tenacity's own `stop` and `wait` | Not reinventing a retry library |
| Tools | `@lup_tool` with typed input and output models; tools grouped into servers, addressed `mcp__group__tool`; each adapter converted servers to its runtime's form (in-process SDK servers on Claude, dynamic tools on Codex) | **Kept, minimal here:** the tool construct and its delivery, with `lup_submit` its one user. Groups and project tools come with the tools slice | `lup_submit` is an ordinary lup tool; only `ask` adding it and the guard checking it are special |
| Errors | Typed: `ProviderTurnError`, `StructuredOutputError`, `TurnTimeoutError`, `BudgetExceededError` | **Kept**, each classified from what the runtime reports in structured form | Callers branch on the type, never on message text |
| Trace and cost | `observability/trace.py`, and `observability/cost.py` with its own pricing tables | **Reshaped:** one `CallRecord` derived from the `TurnResult`, and cost as the runtime reports it | Pricing tables go stale; Claude reports cost itself |
| Out of the operator's history | Sessions from code ran in the operator's config home by default. Derived homes copied the credentials file, because Claude Code replaces it on refresh | **Reshaped:** no session persistence and no user settings (see below) | Same result, no second login to keep fresh |
| Driving Codex | lup's own JSON-RPC client for `codex app-server` | **Reshaped:** the official `openai-codex` SDK, whose raw `request` reaches anything it doesn't wrap | The SDK exists now |
| Fake and guard | Test doubles in lup's own tests only (`tests/unit/doubles.py`); no guard against real calls | **New:** both ship in the library | live-translator's 60-line stub |

## Where the first lup's fields go

A plain ask can carry tools without becoming a room. `DESIGN.md` draws the line at running code or writing files: "a container is required whenever an agent can run code or write files". Web search, a project's own function tools (they run in the caller's process) and reading a directory need no container.

| Where | The first lup's fields |
|---|---|
| This slice | `model`, `system_prompt`, `effort`, `layers` |
| The tools slice: a plain declaration, no container | `tools` (web, read-only file tools, MCP servers, lup function tools); `cwd` and the directories it may read; `max_turns` |
| A slice for products others use | `endpoint`, `api_key` |
| The conversations slice | `resume` and history; `delta_streaming`, for live events |
| Observability | `record`: what is kept of a session |
| The runtime's process | `environment`: the variables it starts with |
| The containers slice, where rooms build on it | `sandbox` and writable mounts, with Bash and the tools that write |
| The environment (`lup-dev`), for developing a project | `plugin` (the compiled harness), `policy`, `hooks`, `requirements` (checks before a launch), `identity` (a place on the roster), `companions` (processes kept beside a session), `max_recursive_agent` (spawn depth, which belongs to budgets), and the account fields `profile`, `home`, `move_sessions` |
| Derived, not declared | `permission_mode`, `allowed_tools`, `disallowed_tools`: lup sets permissions from the declared tools, so a declaration can't contradict its own tools |
| Dropped | `max_thinking_tokens` (superseded by `effort` in the SDK); `setting_sources`, `cli_path`, `max_buffer_size`, `stderr_tail_lines` and the `extra_args` escape hatch (adapter internals); `subagents` (`DESIGN.md`'s spawn replaces native subagents); `submission_gate_resolver` (the gate moves to `ask`, see below) |

## Typed answers: `lup_submit` and its guard

1. **The tool.** A typed ask gives the session one lup tool, `lup_submit`, whose input is the output model.
2. **The handler is the guard.** It validates the submission with pydantic, then runs the `gate` if one was given.
   - A rejection answers the tool call with every validation error, or the gate's message.
   - The agent corrects its answer within the same turn, with its own context. No new prompt is sent.
   - An accepted answer is kept for the turn.
3. **The turn can't end without an accepted answer.**
   - **On Claude**, an in-process `Stop` hook (the SDK runs hooks as Python callbacks) refuses to let the turn finish, saying why: "call `lup_submit` with your answer". The turn continues; it isn't restarted.
   - **On Codex**, hooks are commands configured in files, not callbacks. So when the turn ends without an accepted answer, the adapter continues the same thread with that one sentence. The conversation stays, and the original request isn't re-sent.
4. **Bounded.** `layers.submission.attempts` (default 3) counts rejected answers and refused endings together. Past it, the ask stops the turn and raises `OutputMissing`, carrying every rejected attempt in full.
5. **Untyped asks** get no tool. The answer is the final message's text.

`rejected` on the result keeps the attempts that were refused before the accepted one, so a caller (and the trace) can see why an answer took three tries.

## Tools, minimally

A lup tool is a Python function with a typed input model and a typed output model, declared with `@lup_tool`. It is delivered in each runtime's own way:
- **Claude:** through the SDK's in-process server, so the tool runs in the caller's process. The agent sees it as `mcp__lup__submit`.
- **Codex:** as a dynamic tool on the thread, answered in-process through the SDK client's server-request callback.

The tool construct is public, but in this slice the only tool is `lup_submit`. Project tools, groups and toolsets, and the declaration's `tools` field come with the tools slice. They don't need a container: a function tool runs in the caller's process, not in the agent's.

## The layers an ask runs in

`layers: SessionLayers` is one field on the declaration, applied around every session the agent opens:

| Layer | Field | Default | What it does |
|---|---|---|---|
| Timeout | `timeout: timedelta \| None` | None | Bounds the whole ask, recovery and submission included. When it passes, the turn is interrupted before `TimeoutError` is raised |
| Recovery | `recovery: Recovery` | `stop=stop_after_attempt(3)`, `wait=wait_exponential(multiplier=1, max=30)` | Retries `AgentUnavailable` with tenacity's own strategies, which callers can combine (`stop_after_attempt(5) \| stop_after_delay(120)`). Both runtimes also retry API errors themselves, so this catches what they gave up on |
| Submission | `submission: Submission` | `attempts=3` | Bounds rejected answers and refused endings |
| Trace | `trace: Path \| None` | None | Appends each ask's `CallRecord` to the file, as a JSON line |

## No tools but lup's own

- **Claude:**
  - **Configuration.** Built-in tools off (`tools=[]`), no MCP servers except lup's own in-process one (`strict_mcp_config`), and no skills or plugins.
  - **No filesystem settings** (`setting_sources=[]`), so the user's and project's hooks, `CLAUDE.md` and MCP servers don't load.
  - **No `@path` expansion.** Prompts are delivered verbatim (`verbatim_prompts`), so text from data can't make Claude Code read a local file.
  - **Checked on every call.** The CLI's first message lists the tools the session loaded. Anything beyond lup's own stops the call with `ToolsPresent` before the model can use it. Tool calls are also refused by the permission mode (`dontAsk`, nothing pre-approved but lup's tools).
- **Codex:**
  - **Configuration.** Environment tools off per thread (`environments: []`, documented in the app-server protocol, sent through the SDK's raw `request`), web search disabled, its own subagents disabled (`agents.enabled=false`), and the other built-in features disabled.
  - **Isolation.** It runs in lup's own Codex home, so the user's MCP servers and hooks don't load.
  - **Declared gap.** Codex has no API that lists a session's tools. A live check, run by hand whenever the pinned Codex version changes, confirms the request carries only lup's tool; Codex's rollout trace records the raw request. It becomes part of the capability check when that lands.

## Out of the operator's history

- **Claude:**
  - `--no-session-persistence`, so nothing is written to the operator's history or resume list.
  - The login is the operator's own CLI login.
- **Codex:**
  - `ephemeral` threads, which persist nothing.
  - They run under a lup-owned Codex home whose `auth.json` is a symlink to the operator's. Codex rewrites that file in place, so a refresh writes through the link to the one real copy.
  - A login kept in the keyring instead of a file raises `AuthMissing`, saying so.
- **Where an own config home becomes necessary:** `DESIGN.md` says sessions started from code run under their own config home. That arrives with rooms and long sessions, when transcripts must be kept. For a quick call, `DESIGN.md` says only the cost is recorded, and the trace keeps it.

## Errors

| Error | When | Retried by recovery |
|---|---|---|
| `AgentUnavailable` | Overload, rate limit, a dropped connection, a 5xx. Classified from `ResultError.api_error_status` (Claude) or `codexErrorInfo` (Codex) | Yes |
| `UsageLimitReached` | The subscription's window is spent: Claude's `RateLimitEvent` with status `rejected`, or Codex's `usageLimitExceeded`. Carries the reset time when reported | No |
| `AuthMissing` | No usable login | No |
| `OutputMissing` | No accepted answer within `submission.attempts` | No |
| `ToolsPresent` | The tool check failed | No |
| `RuntimeMissing` | The runtime's extra isn't installed: `install lup[codex]` | No |
| `TimeoutError` (built-in) | `timeout` passed | No |

## The call record

Every ask, successful or not, appends one `CallRecord` to `layers.trace` when it's set. A record holds:
- runtime and model;
- start time and duration;
- the prompt and system prompt, in full;
- the output, in full, or the error;
- the rejected attempts;
- token usage;
- cost where the runtime reports it.

It's derived from the `TurnResult` (or the error) and the request, so the two can't disagree. Claude reports cost; Codex reports tokens only, taken per turn. The dashboard reads the same records once events exist.

## Testing: the fake and the guard

**The fake replaces the adapter, not the agent.** A test's `Claude(...)` goes through the real `ask`: layers, the guard's bookkeeping, the record. Only the turn is scripted.
- `fake_agents.answer(Output, value)` queues an accepted answer for the next ask of that output type.
- `fake_agents.answer_text(str)` queues an answer for a plain ask.
- `fake_agents.reject_then(Output, invalid_json, value)` scripts a rejected submission before the accepted one, to exercise `rejected` and the gate.
- `fake_agents.fail(Output, error)` scripts a failure.
- `fake_agents.calls` lists every call, with its declaration and prompt.
- An ask with nothing scripted raises `UnscriptedAsk`, naming the output type and the prompt.

**The guard is on in every test session of every project that installs `lup[testing]`,** through a pytest plugin entry point.
- **Real turns:** a real adapter refuses to start, raising `RealCallInTest`, which names the fixture to use instead.
- **Network:** connections are refused except to loopback and Unix sockets, through `pytest-socket`. Its per-test `enable_socket` marker is listed by the gate like a suppression.
- **Missing extra:** without `lup[testing]` installed, the plugin stops the session and names the extra, rather than passing silently.

## Modules

```
packages/lup/src/lup/
  __init__.py              the front door: neutral names bound, Claude and Codex resolved on first use
  types.py                 JsonObject and the other shared aliases
  sessions/
    surface.py             Agent, the protocol code naming no runtime holds
    declaration.py         the fields every declaration has, and ask: the layers around the adapter
    contract.py            what an adapter implements: open a session, run a turn; and the seam the fake replaces
    layers.py              SessionLayers, Recovery, Submission
    submission.py          lup_submit: validation, the gate, the accepted answer, the rejected ones
    results.py             TurnResult, Usage, Rejection
    errors.py              the errors above
  tools/
    tool.py                @lup_tool: a typed Python function as a tool
  adapters/
    claude/__init__.py     the Claude declaration
    claude/runtime.py      the Agent SDK session: options, in-process tools, the Stop guard, the tool check
    codex/__init__.py      the Codex declaration
    codex/runtime.py       the app-server session: thread settings, dynamic tools, the continuation guard, lup's Codex home
  observability/
    trace.py               CallRecord, and appending it to the trace
  testing/
    fake.py                FakeAgents
    plugin.py              the fixture and the guard
```

Each adapter imports its SDK at the top of `runtime.py`. Only the front door's first-use resolution reaches an adapter, which is how a missing extra becomes `RuntimeMissing` instead of an import error deep inside.

## Repository layout and packages

One repository holding a few packages, versioned and installed separately, sharing one lock file (a uv workspace):
- **`packages/lup/`:** the library, `lup`.
- **`packages/lup-dev/`:** the environment, `lup-dev` (imported as `lup_dev`), when its first piece starts.
- **`packages/lup-dashboard/`:** the dashboard, behind the typed protocol.

Dependencies run one way only: dashboard, then `lup-dev`, then `lup`.

**Extras:** `lup[claude]` (`claude-agent-sdk`), `lup[codex]` (`openai-codex`), and `lup[testing]` (`pytest`, `pytest-socket`). Each SDK ships its runtime as a binary (the Linux wheels are 107 MB and 141 MB), so a project installs only the side it uses. lup's own tests install all three, since every shared construct is tested on both runtimes.

**Pinned runtimes.** The runtime versions are the ones the lock file pins through the SDKs, not whatever is on `PATH`.

**Python 3.14 or later**, for its lazily evaluated annotations. Python 3.12 would need `from __future__ import annotations` in every file, which turns annotations into strings. Pydantic then fails on names imported only for type checking and on models defined inside functions.

**Code follows the first lup's rule catalog** (`docs/rules.md` in `lup-legacy`), checked by the interim hook until lup's own engine lands.

## Decisions

Each with the alternative and where it lives. **(yours)** marks the operator's.

1. **(yours, agreed)** The workspace and packages above. *Alternative:* one distribution with extras. *Where:* `pyproject.toml`, `packages/`.
2. **(yours, agreed)** Python 3.14. *Alternative:* 3.12 with string annotations. *Where:* `packages/lup/pyproject.toml`.
3. **(yours, agreed)** Dependencies:
   - `claude-agent-sdk` and `openai-codex` as extras;
   - `pytest-socket` in `lup[testing]`;
   - `tenacity` for recovery.

   *Alternatives:* our own runtime clients; a hand-written retry loop. *Where:* `adapters/`, `testing/plugin.py`, `sessions/layers.py`.
4. **(yours, agreed)** `adapters/`, not `providers/`. *Alternative:* the first lup's name. *Where:* `lup/adapters/`.
5. **(yours, agreed)** `ask` returns `TurnResult[T]`. *Alternatives:* the output itself; the output plus an opt-in recorder. *Where:* `sessions/results.py`.
6. **(yours, agreed)** Typed answers through `lup_submit` on both runtimes, guarded at turn end. Native structured output is used on neither. *Alternatives:* the first lup's split (a tool on Claude, native on Codex) with a "Correction required" re-send; native output on both. *Where:* `sessions/submission.py`, `adapters/*/runtime.py`.
7. **(yours)** `gate` is a parameter of `ask`, not of the declaration.
   - A gate checks one output type, and a declaration answers many. On the declaration, the first lup needed a resolver from output type to gate, which erased the type and re-validated the answer to recover it.
   - Its own docstring (`sessions/composition.py`) says moving the gate beside the output type on the turn "would remove it entirely".
   - *Alternatives:* the first lup's resolver on the declaration; both, with the declaration's as a default; a gate method on the output model, which lacks the context a reviewer needs.
   - *Where:* `sessions/declaration.py`.
8. **(yours)** This slice's fields are `model`, `system_prompt`, `effort` and `layers`, and every one of the first lup's 36 fields has a place in *Where the first lup's fields go*. *Alternative:* carrying more of them into this slice before anything uses them. *Where:* `adapters/*/__init__.py`.
9. Layers as one field with four layers. *Alternative:* flat fields on the declaration. *Where:* `sessions/layers.py`.
10. No session persistence and no user settings for calls from code, until rooms need an own config home. *Alternative:* the first lup's derived homes with a copied login. *Where:* `adapters/*/runtime.py`.
11. The fake replaces the adapter under the real `ask`. *Alternatives:* a fake `Agent`; monkeypatching per project. *Where:* `sessions/contract.py`, `testing/fake.py`.
12. The guard is on wherever `lup[testing]` is installed. *Alternative:* opt-in per project. *Where:* `testing/plugin.py`.
13. Async only. *Alternative:* sync wrappers beside each method. *Where:* `sessions/declaration.py`.

## Checks owed

- **Codex's dynamic tool:** that a dynamic `lup_submit` call reaches the SDK client's server-request callback, and that its answer reaches the model. Checked in the implementation's tests against recorded protocol messages, and in the live check.
- **Claude's `Stop` hook:** that it can refuse the end of a turn in an SDK session with no persistence, and how its refusals count against Claude Code's cap of 8 consecutive refusals.
- **Parallel startups.** The first lup gave parallel Claude sessions their own config homes because simultaneous startups corrupted `~/.claude.json`. This slice uses the default home, so the live check must show whether CLI 2.1.29x still does that.
- **Codex's tool-free configuration**, confirmed by the live check on each pinned version.

## Terms

The operator's CLI login is the default, which fits their own use. A product other people use declares an API key:
- Anthropic's terms reserve subscription logins for ordinary individual use.
- Codex's docs say app-server authentication "has never been permitted for commercial or hosted services".

How a declaration names an API key comes with the slice that needs it.
