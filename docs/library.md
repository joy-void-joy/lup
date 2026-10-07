# The library, first slice: asking an agent from code

**One sentence:** `lup` lets production code ask Claude or Codex a question and get a typed answer back, and lets that code's tests run without reaching a real agent.

This slice is the first item of the build order in `DESIGN.md`. It covers:
- the `Claude` and `Codex` declarations and their `ask`, with typed output;
- the guarantee that a call has no tools;
- timeouts, retries and errors;
- a record of every call (the trace, with cost);
- the fake agent and the test guard.

Later slices add, on the same declarations: conversations (`open`), tools from Python functions, containers and mounts, rooms, `spawn`, `launch`, runs, the outcome loop, `SharedBudget`, and events for the dashboard. Nothing here should need to change shape for them; where a choice below would, it says so.

## Who it serves first

live-translator moves onto this slice as soon as it lands. It needed five things from the first lup, each of which cost it work:

| Need | What it had to do in the first lup | In this slice |
|---|---|---|
| A provider switch | Two config classes and two factories (`agent/core.py:45-92`) | `Claude(...)` and `Codex(...)` both satisfy `Agent` |
| A timeout | `asyncio.timeout` around the call | `timeout=` on the declaration |
| A trace | Its own `TraceLogger` | `trace=` on the declaration |
| A guarantee of no tools | Built upstream first (#188, #433), then asserted in its own test | The default, checked on every Claude call |
| A fake for tests | About 60 lines of stubs per test module | The `fake_agents` fixture |

## The public API

```python
from datetime import timedelta
from pathlib import Path
from lup import Claude, Codex

translator = Claude(
    model="opus",
    system_prompt=PROMPT,
    effort="low",
    timeout=timedelta(seconds=30),
    trace=Path("traces/translator.jsonl"),
)

translations = await translator.ask(segment.model_dump_json(), Translations)  # -> Translations
greeting = await translator.ask("Say hello in French")                         # -> str
```

`Codex(...)` takes the same fields, with Codex's own model names and effort levels. Code that should not care which runtime it uses takes an `Agent`:

```python
from lup import Agent

def translator_for(settings: Settings) -> Agent:
    match settings.provider:
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

The whole public surface of this slice:
- `Claude`, `Codex`: frozen pydantic models. Fields: `model`, `system_prompt`, `effort`, `timeout`, `trace`. An unknown field is an error when the declaration is built.
- `Agent`: the protocol both satisfy. Its one method is `ask(prompt, output=None)`.
- `CallRecord`: one line of a trace.
- The errors (see *Errors, retries and the timeout*).
- `lup.testing`: `FakeAgents`, the `fake_agents` fixture, and `RealCallInTest`.

## Modules

All under `packages/lup/src/lup/`.

| Module | What it's for |
|---|---|
| `__init__.py` | The front door: re-exports the public names above, importing each runtime's SDK lazily so `import lup` stays fast. |
| `agent.py` | The `Agent` protocol, and the part of `ask` that doesn't depend on the runtime: the timeout, retrying transient errors, validating the output and asking again, writing the call record. |
| `claude.py` | The `Claude` declaration and its adapter, which runs one turn through the Claude Agent SDK. |
| `codex.py` | The `Codex` declaration and its adapter, which runs one turn through the Codex Python SDK. |
| `runtime.py` | Internal. The contract an adapter implements: run one turn and return what came back, with no retries or validation of its own. The fake implements the same contract. |
| `output.py` | Turns a pydantic model into the schema each runtime accepts, and validates what comes back. |
| `record.py` | `CallRecord`, and appending records to a trace file. |
| `errors.py` | The error types. |
| `testing/fake.py` | `FakeAgents`: scripted answers, and the calls it received. |
| `testing/plugin.py` | The pytest plugin: the `fake_agents` fixture and the guard. |

## How each runtime is driven

- **Claude** through `claude-agent-sdk` (0.2.164 today), the official SDK. It runs the Claude Code CLI as a subprocess and bundles a pinned copy of it (2.1.292 today).
- **Codex** through `openai-codex` (0.160.1), the official Python SDK, marked stable. It runs `codex app-server` over JSON-RPC and depends on a pinned Codex binary (`openai-codex-cli-bin`).

Each runtime is an optional extra: `lup[claude]`, `lup[codex]`, or both. A project installs only the side it uses. Building a `Codex(...)` without the `codex` extra fails at once, naming the extra to install. lup's own tests install both, since every shared construct is tested on both runtimes.

**The runtime versions are the ones the lock file pins**, not whatever is on `PATH`. Today this machine has three Codex installs on `PATH` (0.156.1 from npm shadowing 0.160.0 in `/usr/bin`), behind a shell function that still calls the old `lup-devtools`. Production code like live-translator shouldn't depend on that. The environment's interactive launch is a separate question for the launch piece.

Each `ask` is one turn in a fresh session, with the session kept open only while lup may need to ask again (see *Typed output*).

## Typed output

`ask(prompt, Output)` returns an instance of `Output`, a pydantic model. `ask(prompt)` returns the answer's text.

- **Claude:** the SDK's native structured output (`output_format`, a JSON schema from `Output.model_json_schema()`). The CLI validates the answer against the schema and asks the model again on a mismatch. If that fails, it ends with `error_max_structured_output_retries`. The answer arrives in `ResultMessage.structured_output`.
- **Codex:** the turn's `output_schema`, which Codex sends to the model in OpenAI's strict mode. Strict mode accepts a subset of JSON Schema: every field required, no extra properties, no free-form `dict` fields. lup converts the model's schema to that subset: optional fields become required-but-nullable. A model that can't be converted, such as one with a `dict[str, X]` field, is asked for through a carrier instead: a strict schema with one string field holding the JSON, which pydantic then validates. The first lup did the same (`providers/codex/output.py`). Codex doesn't validate the answer itself.
- **On both:** lup validates the answer with pydantic. Validators can check more than a schema can. If validation fails, lup asks again in the same session, quoting the validation errors, up to twice, then raises `OutputInvalid` with every attempt's errors. This is the library's own gate from `DESIGN.md` ("validates … or rejects with feedback and asks again"). Holding an answer for a reflection gate comes later, with gates.

## No tools, and how it's checked

A bare `Claude(...)` or `Codex(...)` has no tools. In the first lup the default was web search and fetch, so a call meant to be tool-free had to say so.

- **Claude:** built-in tools off (`tools=[]`), no MCP servers (`strict_mcp_config`), no skills or plugins, and no filesystem settings (`setting_sources=[]`), so the user's and project's hooks, `CLAUDE.md` and MCP servers don't load. **Checked on every call:** the CLI's first message lists the tools the session loaded (checked against the effects probe's stream). If it lists anything but the structured-output tool, the call stops with `ToolsPresent` before the prompt is sent.
- **Codex:** environment tools off (shell, `apply_patch`, `view_image`), web search disabled, its own subagents disabled (`agents.enabled=false`; `--disable multi_agent` alone isn't enough on current models), and the other built-in features disabled (apps, image generation, goals, sleep, plugins). It also runs in lup's own Codex home, so the user's MCP servers and hooks don't load (see the next section).
  - Environment tools are removed per thread with `environments: []`, which the app-server protocol documents (as experimental).
  - The SDK's `thread_start` doesn't take that field, so lup starts the thread through the SDK client's raw `request(method, params)`, which reaches any app-server method the SDK doesn't wrap.
  - **Declared gap:** Codex has no API that lists a session's tools, so this is configuration, not a per-call check.
  - So a live check, run by hand whenever the pinned Codex version changes, confirms the request carries no tools (Codex's rollout trace records the raw request). It becomes part of the capability check when that lands.

## Out of the operator's history

Calls from code must not show up among the operator's own sessions.

- **Claude:** `--no-session-persistence` (passed through the SDK's `extra_args`). Nothing is written to the operator's history or resume list. The login is the operator's own CLI login, read from the default config home.
- **Codex:** `ephemeral` threads, which persist nothing. The calls run under a lup-owned Codex home, so the user's `config.toml` (MCP servers, hooks, plugins) doesn't load. Its `auth.json` is a symlink to the operator's.
  - Codex rewrites that file in place, without replacing it (`login/src/auth/storage.rs`), so a refresh writes through the link to the one real copy.
  - If the operator stores the login in the keyring instead of a file, the lup-owned home can't see it, and the call raises `AuthMissing` saying so.
- `DESIGN.md` says sessions started from code run under their own config home. For calls with no tools, skipping persistence gives the same result with no second login to keep fresh. An own config home becomes necessary when transcripts must be kept (rooms, long sessions), in the slice that adds them. Per `DESIGN.md`, a quick call records only its cost, which the call record keeps.

## Errors, retries and the timeout

| Error | When | Retried by lup |
|---|---|---|
| `AgentUnavailable` | Overload, rate limit, a dropped connection, a 5xx. Classified from `ResultError.api_error_status` (Claude) or `codexErrorInfo` (Codex), never from message text | Yes, with backoff, within the timeout |
| `UsageLimitReached` | The subscription's window is spent | No: it won't clear within a call. Carries the reset time when the runtime reports it |
| `AuthMissing` | No usable login | No |
| `OutputInvalid` | Still invalid after asking again | No |
| `ToolsPresent` | The no-tools check failed | No |
| `TimeoutError` (built-in) | `timeout` passed | No |

- **The timeout covers the whole `ask`:** retries and re-asks included. When it passes, lup interrupts the turn (`interrupt()` on Claude, `turn/interrupt` on Codex) before raising.
- **Without a timeout**, transient errors are retried three times.
- **Both runtimes also retry some API errors themselves.** lup only retries what reaches it.

## The call record

Every `ask`, successful or not, produces one `CallRecord`:
- runtime and model;
- start time and duration;
- the prompt and system prompt, in full;
- the output, in full, or the error;
- attempts and re-asks;
- token usage (input, cached input, cache writes, output);
- cost in dollars where the runtime reports it.

With `trace=` set, it's appended to that file as one JSON line. Nothing in a record is truncated.

- Claude reports cost (`total_cost_usd`). Codex reports tokens only, so its `cost_usd` is `None`.
- Codex's usage is taken per turn (`tokenUsage.last`). Its exec stream reports the thread's running total, an easy mistake.

The dashboard will read the same records once events exist. That's the later slice, and it doesn't change this shape.

## Testing: the fake and the guard

**The fake replaces the runtime, not the agent.** A test's `Claude(...)` goes through the real `ask`: validation, re-asks, the timeout, the record. Only the turn itself is scripted. A fake that replaced the whole `Agent` would let a project's tests pass while the real path failed.

- `fake_agents.answer(Output, value)` queues an answer for the next `ask` of that output type. `answer_text(str)` does the same for plain asks.
- `fake_agents.answer_with(Output, function)` computes the answer from the prompt.
- `fake_agents.fail(Output, error)` scripts a failure, to test the retry path or the caller's handling of `OutputInvalid`.
- `fake_agents.calls` lists every call, with its declaration and prompt.
- An `ask` with nothing scripted raises `UnscriptedAsk`, naming the output type and the prompt.

**The guard is on in every test session of every project that installs lup**, through a pytest plugin entry point (`pytest11`). Under it:
- **A real turn refuses to start**, raising `RealCallInTest`, which names the fixture to use instead.
- **Network connections are refused** except to loopback addresses and Unix sockets, through `pytest-socket`, which the plugin turns on for the session.
  - `pytest-socket` is a small pytest plugin. During tests it replaces Python's socket, so any connection outside the allowed hosts raises `SocketBlockedError`.
  - It covers only the test process. That's why the guard above refuses real runtime subprocesses separately.
  - It offers a per-test marker that re-enables the network (`enable_socket`). The gate will list uses of it like suppressions.

Real calls belong in the live check above, not in tests (`AGENTS.md`: tests that reached real agents were slow and flaky). nori, which `DECISIONS.md` cites as having such a guard, in fact has a clock guard; neither nori nor the first lup refused real calls. So this is new.

## Repository layout

One repository holding a few packages, versioned and installed separately, sharing one lock file (a uv workspace):

```
pyproject.toml          the workspace: members, dev dependencies (ruff, pyright, pytest), tool config
packages/lup/           the library: distribution `lup`, imported as `lup`
  pyproject.toml
  src/lup/
  tests/
docs/                   one design note per piece
```

Two more packages arrive with their first pieces:
- `packages/lup-dev/` (distribution `lup-dev`, imported as `lup_dev`): the environment, meaning everything a project uses only while it's being developed.
- `packages/lup-dashboard/`: the dashboard, the one part with its own stack (the web build), behind the typed protocol `DESIGN.md` describes.

Dependencies run one way only: `lup-dashboard` depends on `lup-dev`, which depends on `lup`.

**Python 3.14 or later**, for its lazily evaluated annotations (PEP 649). The alternative is 3.12 with `from __future__ import annotations` in every file, which turns every annotation into a string. Pydantic resolves those strings, except:
- names imported only for type checking;
- models defined inside a function;
- anything else that reads annotations at runtime, which gets strings.

The first lup required 3.14 from its first week without recording why.

`lup`, `lup-dev` and `lup-dashboard` are free on PyPI. Publishing is a decision for the release piece. The first lup's tag-triggered publish never ran (no trusted publisher was set up), and every downstream project installed from git.

## Decisions

Each with the alternative, and where it lives. The ones marked **(yours)** are shape decisions for the operator.

1. **(yours, agreed)** One repository with a uv workspace. The packages are `lup`, later `lup-dev` (`lup_dev`), and `lup-dashboard`, with dependencies running one way. *Alternatives:* one distribution with extras, where the split in `DESIGN.md` becomes a convention instead of a dependency boundary; or a namespace package `lup.dev`, which is awkward beside `lup/__init__.py`. *Where:* `pyproject.toml`, `packages/`.
2. **(yours, agreed)** Python 3.14 or later, for lazy annotations. *Alternative:* 3.12 with `from __future__ import annotations` everywhere. *Where:* `packages/lup/pyproject.toml`.
3. **(yours, agreed)** Three new dependencies:
   - `claude-agent-sdk` and `openai-codex`, as the optional extras `lup[claude]` and `lup[codex]`;
   - `pytest-socket`, for the network guard.

   *Alternatives:*
   - lup's own subprocess and JSON-RPC clients, which is what the first lup did for Codex before an official SDK existed. The Codex SDK's raw `request` covers what it doesn't wrap.
   - `codex exec --json`, whose event stream drops the error classification (`willRetry`, `codexErrorInfo`), so errors could only be told apart by parsing text.
   - A hand-written socket patch for the guard.

   *Where:* `claude.py`, `codex.py`, `testing/plugin.py`.
4. The SDKs' pinned runtime binaries, not `PATH`. *Alternative:* `PATH`, as the first lup did. *Where:* `claude.py`, `codex.py`.
5. `ask` returns the output itself; per-call facts go to the call record. *Alternative:* a `Reply[T]` wrapper with `.output`, `.usage` and `.cost`, which every caller would unwrap. *Where:* `agent.py`.
6. Native typed output on both runtimes, with lup's validation and re-asks on top, and a string carrier for schemas Codex's strict mode refuses. *Alternative:* a submit tool lup hosts, as the first lup did on Claude. It let a gate reject a submission mid-turn, but needed the prompt to name the tool and raced with native output. *Where:* `output.py`, `agent.py`.
7. No tools by default, checked per call on Claude, declared as a gap on Codex. *Alternative:* trust the configuration on both. *Where:* `claude.py`, `codex.py`.
8. No session persistence and no user settings, instead of an own config home, for calls with no tools. *Alternative:* an own config home per process, with a copied login, as the first lup did. Claude replaces its credentials file on refresh, so a link wouldn't survive and a copy goes stale. *Where:* `claude.py`, `codex.py`.
9. The fake replaces the runtime under the real `ask`, scripted by output type. *Alternatives:* a fake `Agent` passed in by the caller; monkeypatching in each project. *Where:* `runtime.py`, `testing/fake.py`.
10. The guard is on automatically, with no opt-out in this slice. *Alternatives:* opt-in per project through a fixture; an opt-out marker with a reason, which the gate would list. *Where:* `testing/plugin.py`.
11. The trace is a file path on the declaration. *Alternatives:* a process-wide list of sinks; OpenTelemetry spans (Claude Code emits them, Codex doesn't). *Where:* `record.py`.
12. Async only. *Alternative:* a sync wrapper beside each method, two ways to do one thing. live-translator is async. *Where:* `agent.py`.

## Checks owed

- **Parallel startups.** The first lup gave parallel Claude sessions their own config homes because simultaneous startups corrupted `~/.claude.json`. This slice uses the default home, so a test with parallel real calls (in the live check, not the test suite) must show whether CLI 2.1.29x still does that.
- **Codex's tool-free configuration**, confirmed by the live check on each pinned version (see above).
- **Does Claude's structured-output tool reach hooks?** aib's hooks saw a `StructuredOutput` tool. That matters when gates hold answers, not in this slice.

## Terms

The operator's CLI login is the default, which fits their own use. A product other people use declares an API key:
- Anthropic's terms reserve subscription logins for ordinary individual use.
- Codex's docs say app-server authentication "has never been permitted for commercial or hosted services".

How a declaration names an API key comes with the slice that needs it.
