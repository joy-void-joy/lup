# The library, first slice: asking an agent from code

**One sentence:** `lup` lets production code ask Claude or Codex a question and get a typed answer back, and lets that code's tests run without reaching a real agent.

This is the first step of `DESIGN.md`'s build order. `DESIGN.md` (*The library*) is the design; this note is the slice as built. It covers:
- the `Claude` and `Codex` declarations, `Agent`, and `ask`;
- typed answers through `submit`, a lup tool that validates and reviews each answer, and the guard that keeps a typed turn open until one is accepted;
- the speaking tools, `report` and `note`, served on every ask;
- tools as typed Python functions, and how each runtime is given them;
- the layers an ask runs in: timeout, recovery, submission, trace;
- the guarantee that an ask can only call lup's tools, and keeping asks out of the operator's history;
- the errors, the call record, the fake agent and the test guard;
- each runtime's adapter.

What comes after is under *Later slices*. A choice the operator hasn't confirmed is marked **(leaning)** where it's stated.

## Who it serves first

live-translator moves onto this slice as soon as it lands. It needs five things (`docs/field-notes.md`, *From the downstream projects*):

| Need | In this slice |
|---|---|
| A provider switch | `Claude(...)` and `Codex(...)` are both an `Agent` |
| A timeout | `layers.timeout` |
| A trace | `layers.trace`, one `CallRecord` per ask |
| A guarantee of no tools | each adapter's configuration (*No tools but lup's own*), checked on every Claude call |
| A fake for tests | the `fake_agents` fixture, where stubbing one call by hand took about 70 lines |

## The public API

```python
from datetime import timedelta
from pathlib import Path

from lup import Claude, SessionLayers

translator = Claude(
    model="opus",
    system_prompt=PROMPT,
    effort="low",
    layers=SessionLayers(timeout=timedelta(seconds=30), trace=Path("traces/translator.jsonl")),
)

result = await translator.ask(segment.model_dump_json(), Translations)
result.output            # Translations
result.notes             # the remarks the agent attached, if any
result.usage.cost_usd    # where the runtime reports it
```

- **`ask(prompt, output)` returns a `TurnResult[T]`:** `output`, `usage`, `duration`, `session_id`, `rejected` (the submissions refused before the accepted one, oldest first) and `notes`. `output` is an instance of the output model, or the final message's text when no model is given. Returning the result, not the bare output, keeps the cost, the refusals and the notes beside the answer; the output plus an opt-in recorder would split what one ask said in two.
  - `Usage` holds `input_tokens` (the input not read from cache), `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, and `cost_usd`, none where the runtime reports tokens only. It's the usage of the attempt that answered.
  - A `Rejection` holds what was submitted, as the agent sent it, and the reason it was refused.
- **`output` is a model type or an output tool.** `ask(prompt, Forecast)` builds `Submit(Forecast)`; to review an answer before it's accepted, build the tool with `before` hooks (*Typed answers*).
- **A failure is always an error,** never an empty result (*Errors*).
- **Async only,** with no sync wrapper beside each method.
- **The front door** (`lup/__init__.py`) binds the runtime-neutral names (`Agent`, `TurnResult`, `Usage`, `Rejection`, `SessionLayers`, `Recovery`, `Submission`, and the errors), and `Claude` and `Codex` from their adapters. Each adapter imports its runtime's SDK when an ask first runs, so `import lup` reaches neither SDK, a declaration compiles for a terminal without its extra (a launch runs the CLI it fetches, `docs/launch.md`), and asking a runtime whose extra isn't installed raises `RuntimeMissingError` naming the extra.

**`Agent` is what code naming no runtime holds.** It's an ABC with one abstract method, `ask`, typed by overloads: `ask(prompt)` returns a `TurnResult[str]`, `ask(prompt, Forecast)` a `TurnResult[Forecast]`. Both declarations inherit it, as anything a project writes to stand in for one would. It's an ABC, not a `Protocol` matched by shape, as every interface lup owns is (`docs/conventions.md`, *Interfaces*): the declarations and the fake are lup's, and inherit.

```python
from lup import Agent, Claude, Codex

def translator_for(settings: Settings) -> Agent:
    match settings.runtime:
        case "claude":
            return Claude(model="opus", system_prompt=PROMPT)
        case "codex":
            return Codex(model="gpt-6.1-sol", system_prompt=PROMPT)
```

Testing it:

```python
import asyncio

from lup.testing import FakeAgents

def test_translates_a_segment(fake_agents: FakeAgents) -> None:
    fake_agents.answer(Translations, Translations(lines=["Bonjour"]))

    result = asyncio.run(translate(segment))

    assert result.lines == ["Bonjour"]
    assert fake_agents.calls[0].prompt == segment.model_dump_json()
```

### What a declaration holds

`Claude` and `Codex` are frozen models, each a `Declaration` and an `Agent`. In this slice their fields are **(leaning)**:
- `model`: the runtime's model id, passed as given; none leaves it to the runtime (the operator's decision): in a terminal, the person's own settings choose, and in an ask, the runtime's default, since an ask loads none of their settings. So an ask passes no model to either SDK (`claude_agent_sdk` then passes no `--model`, and Codex's `thread/start` leaves its optional `model` out), and the trace records none;
- `system_prompt`: replaces the runtime's own prompt; none sends no prompt of lup's own (what reaches the model is in each adapter's section);
- `effort`: in each runtime's own levels, Claude Code's `low`, `medium`, `high`, `xhigh`, `max`, and Codex's `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`; none leaves it to the runtime;
- `layers` (*The layers an ask runs in*).

A field arrives with the slice that uses it, not before. What a declaration doesn't hold:
- tools, which are `lup_tool` constructs (the tools slice adds the field that takes them);
- an endpoint and an API key, given as one connection value when a client is created;
- resume and history, which belong to the session holder (`open`);
- transcripts, which belong to lup's own writer;
- permissions (a permission mode, allowed and disallowed tools), which are derived from the declared tools, so a declaration can't contradict its own tools.

### How a declaration asks

An adapter (`Adapter`, `sessions/contract.py`) runs one turn on its runtime. It's given a `TurnRequest`: the prompt, the turn's `Toolbox`, and `output`, the answer's model (none for an untyped turn), on which the fake matches its scripts. It serves the toolbox's tools, routes the model's calls to them, holds the turn open until the toolbox lets it end, and reports a `RawTurn`: the final message's text, the usage, and the session's id. It raises the errors of *Errors*.

Each declaration's `ask` builds its runtime's adapter from its own fields and hands the ask to `Asking` (`sessions/declaration.py`), which runs it inside the layers on the adapter the seam chooses: the declaration's own, unless a test's fake stands in (*Testing*). The shared behaviour is composed into each declaration through `Asking`, since an ABC carries no behaviour of its own (`docs/conventions.md`, *Interfaces*).

The adapter takes the declaration's fields, not the declaration **(leaning)**. The declaration's module imports its adapter, and pydantic reads a field's type at runtime, so an adapter holding a `Claude` would import its declaration back: a cycle no `TYPE_CHECKING` import breaks. The cost is that each field is passed by hand in `ask`.

## Typed answers: the output tool and its guard

1. **The tool.** A typed ask gives the session `submit`, an ordinary lup tool whose input is the output model: `Submit(Forecast)`, built for you when `ask` is given the model type. How each runtime shows it is in *The output tool's name*.
2. **It validates, then reviews.** pydantic validates the arguments as the model sent them, then the tool's `before` hooks run in order on the validated value. A hook receives the typed answer and returns `Allow()` or `Deny(reason)`:

   ```python
   from lup.tools import Allow, Deny, Submit

   async def cites_sources(forecast: Forecast) -> Allow | Deny:
       if not forecast.sources:
           return Deny(reason="Cite at least one source for the probability.")
       return Allow()

   result = await forecaster.ask(question, Submit(Forecast, before=[cites_sources]))
   ```

   A review is a hook on the output tool, not a separate gate. A `gate=` parameter on `ask`, or a resolver on the declaration from output type to gate, would erase the answer's type and validate it again to get it back; a review method on the output model lacks the context a reviewer needs.
3. **A refusal answers the call.** Every validation error at once, or the hook's reason, goes back as the tool's answer (`Refused: …`, marked as an error), and the agent corrects its answer within the same turn, with its own context. No new prompt is sent. An accepted answer gets a receipt ("Your answer is accepted. End your turn."), and the last accepted call is the answer.
4. **The turn can't end without an accepted answer or a reported problem.** That's lup's own guard, decided by the turn's `Toolbox` (`sessions/submission.py`) the same way on every runtime: when the model tries to end its turn, the toolbox says to end, to keep going with a reason the model reads, or to give up. The reason is "Call the `submit` tool with your final answer, or `report` if it can't be answered: your turn can't end until one is accepted." Each adapter delivers it: a `Stop` hook on Claude, a continuation of the same thread on Codex.
5. **Bounded.** `layers.submission.attempts` (3 by default) counts rejected answers and refused endings together, checked when the model tries to end its turn. Once they're spent, the guard lets the turn end, and the ask raises `OutputMissingError` with every rejected attempt in full.
6. **An untyped ask** has no output tool; its answer is the final message's text. It still serves the speaking tools.

`rejected` on the result keeps the attempts refused before the accepted one, so a caller (and the trace) can see why an answer took three tries.

**One mechanism on both runtimes, and native structured output on neither.** Codex's native output is the shape of the final message, not a tool call, so nothing could refuse an answer inside the turn, and its strict-schema subset needs a carrier for any schema outside it. A tool keeps everything a tool has, hooks included, and a guard keeps the agent in its turn and its context where a re-sent correction would start over.

### The output tool's name

The tool is named `submit` **(leaning; issue #50)**. Each runtime shows it to the model its own way:
- **Claude:** `mcp__lup__submit`, a tool of lup's MCP server, which is named `lup` (`SERVER` and `TOOL_PREFIX` in `adapters/claude/runtime.py`). The speaking tools are `mcp__lup__report` and `mcp__lup__note`. Those three names are what the session pre-approves and what its tool check accepts.
- **Codex:** a dynamic tool of type `function` named `submit`, with no namespace (`DynamicTool` in `adapters/codex/runtime.py`, from the tool's spec); a call arrives as `item/tool/call` with `tool: "submit"`. On a code-mode model it's a nested tool of `exec`, called from JavaScript as `await tools.submit({...})`: the pinned app-server's own description of `exec` puts every nested tool on a global `tools` object, named as a JavaScript identifier, which `submit` already is.

The alternative, `lup_submit`, would repeat the server's name on Claude (`mcp__lup__lup_submit`). On Codex a bare name could collide with a project's own tool called `submit` once project tools exist; Codex's protocol has namespaced dynamic tools (`type: "namespace"`), which the tools slice can use for that.

## The speaking tools

Every ask serves `report` and `note` (`lup/tools/speaking.py`), typed or not. They act on nothing, so they're served even where an agent has no other tool (`DESIGN.md`, *The library*).
- **`report(problem)`** stops the turn without an answer and says what's wrong: the question can't be answered, something needed is missing, an instruction seems wrong. The ask raises `ProblemReportedError` with the agent's words and the notes it attached, so a caller tells "the agent says this can't be done" from a failure. It isn't retried: asking again gets the same problem. A report lets a typed turn end as an accepted answer does, and a turn that both answered and reported raises the report.
- **`note(remark)`** attaches an assumption, a doubt or a counterargument to the answer without ending the turn. The caller reads it in `TurnResult.notes`, or `ProblemReportedError.notes`; the trace keeps it.

## Tools

A lup tool is an async Python function taking one pydantic model and returning another, declared with `@lup_tool`. Its name is the function's, its description the docstring (required: it's what the model reads), its input schema the parameter's model. A function shaped otherwise raises `ToolError`.

```python
from lup.tools import lup_tool

@lup_tool
async def weather(query: Query) -> Weather:
    """Look up today's weather in a city."""
    ...
```

A tool can carry `before` hooks, typed on its input, which run on the validated input before the function. A validation error, with every error at once, or a hook's `Deny`, answers the call instead, so one answer tells the agent everything to fix. An accepted call answers with the function's output as JSON.

A tool runs in the caller's process. Each adapter serves a turn's tools (`Toolbox.specs`) and routes every call to `Toolbox.call`, which records it. The calls recorded are the one source of what the turn said: the answer, the rejections, the problem and the notes.
- **Claude:** through lup's own MCP server, built on `mcp`'s low-level `Server` and served in-process by the SDK. Every call reaches lup with its arguments as the model sent them, so lup validates, refuses, counts and records a malformed call like any other. The SDK's own helper, `create_sdk_mcp_server`, would check the arguments against the schema before the handler ran and answer the refusal itself, out of lup's sight.
- **Codex:** as the thread's dynamic tools, declared when the thread starts and fixed for its life. Codex sends each call to the client as an `item/tool/call` request, answered in-process (*The Codex adapter*).

In this slice the only tools are `submit` and the speaking tools. The construct is public (`lup.tools`: `lup_tool`, `Tool`, `Allow`, `Deny`, `Submit`, `Receipt`) for the tools slice to build on.

## The layers an ask runs in

`layers: SessionLayers` is one field on the declaration, applied around every ask, rather than flat fields on the declaration:

| Layer | Field | Default | What it does |
|---|---|---|---|
| Timeout | `timeout: timedelta \| None` | none | Bounds the whole ask, recovery and submission included. When it passes, the turn is interrupted and the ask raises `TurnTimeoutError` |
| Recovery | `recovery: Recovery` | `stop=stop_after_attempt(3)`, `wait=wait_exponential(multiplier=1, max=30)` | Retries `AgentUnavailableError`, each attempt a fresh turn, with tenacity's own strategies, which a caller combines (`stop_after_attempt(5) \| stop_after_delay(120)`). Both runtimes retry API errors themselves first, so this catches what they gave up on |
| Submission | `submission: Submission` | `attempts=3` | Bounds rejected answers and refused endings together |
| Trace | `trace: Path \| None` | none | Appends each ask's `CallRecord` to the file, as one JSON line |

Recovery is tenacity's, not a retry loop of lup's own.

## No tools but lup's own

The guarantee is about what can happen: an ask from code can't run commands, touch files, reach the network or start agents; it can only call lup's tools (`DESIGN.md`, *The library*). Each adapter configures its runtime for it, and checks it on every call where the runtime lets it.

- **Claude** (`adapters/claude/runtime.py`):
  - **Configuration.** No built-in tools (`tools=[]`, which the SDK passes as `--tools ""`); no MCP server but lup's own (`strict_mcp_config`); no skills or plugins (`skills=[]`, `plugins=[]`); lup's tools pre-approved (`allowed_tools`), and every other call denied (`permission_mode="dontAsk"`).
  - **No settings files** (`setting_sources=[]`), so the operator's and the project's hooks, `CLAUDE.md` and MCP servers don't load. Auto memory is read whatever the settings say, so `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` turns it off.
  - **No `@path` expansion.** Prompts are delivered verbatim (`verbatim_prompts`), so text from data can't make Claude Code read a local file: without it, `@/etc/hostname` in a prompt attached the file, even with no tools. Slash commands aren't dispatched either.
  - **Checked on every call.** The session's first message (`init`) lists the tools and MCP servers it loaded. A tool beyond lup's own, or a server other than lup's, interrupts the turn and raises `ToolsPresentError` before the model can use it. The message also lists skills, plugins, agents and slash commands, even when nothing can call them (no `Skill` or `Agent` tool is loaded, and a verbatim prompt dispatches no slash command), so only tools and servers are checked. A turn whose `init` never came raises `TurnError`, since its check never ran, rather than trusting the configuration **(leaning)**.
- **Codex** (`adapters/codex/runtime.py`):
  - **The thread** is ephemeral and has no environment (`environments: []`, from the app-server protocol, sent through the SDK's raw `request`), so no shell and no file tools, and Codex's own subagents are off (`agents.enabled=false` in its config). Approvals are never asked (`approvalPolicy: "never"`), and the sandbox is read-only.
  - **The launch.** Each app-server starts with these `--config` overrides (`LAUNCH`):
    - web search disabled (`web_search="disabled"`);
    - skills' instructions and bundled skills off (`skills.include_instructions`, `skills.bundled.enabled`);
    - the instructions describing the environment, permissions, apps and collaboration modes off (`include_environment_context`, `include_permissions_instructions`, `include_apps_instructions`, `include_collaboration_mode_instructions`);
    - the experimental user-input tool off (`tools.experimental_request_user_input.enabled`);
    - every built-in feature that brings a tool off: `features.` `goals`, `sleep_tool`, `image_generation`, `multi_agent`, `apps`, `plugins`, `remote_plugin`, `skill_search`, `tool_suggest`, `view_image`, `browser_use`, `computer_use`, `shell_tool`, `unified_exec`, `hooks`, `workspace_dependencies`;
    - credentials kept in a file (`cli_auth_credentials_store="file"`, *Out of the operator's history*).
  - **Code mode.** On models whose catalog entry says `tool_mode: code_mode_only` (the default `gpt-6.1-sol` among them), every tool, lup's included, is reached through a JavaScript `exec` tool, beside `wait` and `request_user_input_async`, and no setting removes them. An `exec` call trying each way out, against a local mock of the Responses endpoint, found a V8 isolate with no `fetch`, `require`, `process` or `WebAssembly`, every import refused, and for nested tools only lup's, a clock, and MCP's resource readers, which read nothing without an MCP server. `request_user_input_async` only queues a question, with no request to the client. So code mode can't reach a shell, files, the network or another agent, and code-mode models are accepted, as `DESIGN.md` (*Runtimes*) allows when that holds. The code-mode host stays on: turned off, `exec` answers "code-mode host is disabled", leaving lup's tools out of reach on those models.
  - **Isolation.** It runs in lup's own Codex home, so the operator's configuration, MCP servers, hooks and skills don't load. Nor does a project's `AGENTS.md`: checked from a checkout holding one.
  - **Nothing else answered.** A request from Codex to the client other than a call to lup's tools (an approval, an elicitation) fails the ask **(leaning)**. A question for the user is answered that no one can answer, pointing at `report`, so the agent carries on or says what's missing.
  - **A declared gap.** Codex has no API listing a session's tools, so nothing checks them on each call. A live check, run by hand whenever the pinned version changes, confirms the model's request carries only lup's tools (*Checks owed*); it joins the capability check when that exists.

## Out of the operator's history

Calls from code persist no session and load no user settings (`DESIGN.md`, *The library*).
- **Claude:**
  - no session persistence: `--no-session-persistence`, which has no SDK field, passed through `extra_args`. No transcript is written, so nothing reaches the operator's history or resume list;
  - no settings files, and no auto memory (*No tools but lup's own*);
  - the operator's own config home and CLI login. A home of lup's own would need a copy of the login, since Claude Code replaces its credentials file on a refresh, and the copy would go stale; with nothing loaded and nothing kept, the default home serves.
- **Codex:**
  - ephemeral threads, which persist nothing;
  - lup's own Codex home, `$XDG_STATE_HOME/lup/codex` (`~/.local/state/lup/codex` by default), so the operator's configuration, MCP servers, hooks, skills and history don't reach a call from code. Its `auth.json` is a symbolic link to the operator's login (`$CODEX_HOME/auth.json`, or `~/.codex/auth.json`). Codex rewrites that file in place, so a refresh writes through the link to the one real copy, and a logout from lup's home removes only the link. A link pointing elsewhere is replaced; an `auth.json` that is lup's home's own, a real file, is left alone;
  - credentials pinned to the file store **(leaning)**: under `keyring` or `auto`, a refresh deletes `auth.json`, which in lup's home is the link;
  - the login checked before the thread starts (`account/read`). Without one, the ask raises `AuthMissingError` naming both homes. A login kept in the system keyring can't be seen from lup's home, since the keyring's key derives from the home's path, so the error says to switch to the file store and log in again. A provider that needs no login goes ahead.

Sessions that are kept run under their own config home (`DESIGN.md`, *Calling agents from code*); on Claude that arrives with conversations (*Later slices*).

**Logins and terms.** The operator's CLI login is the default, which fits their own use. A product other people use declares an API key: Anthropic's terms reserve subscription logins for ordinary individual use, and Codex's docs say app-server authentication "has never been permitted for commercial or hosted services". How a declaration names one comes with the connection (*Later slices*).

## Errors

Every error lup raises descends from `LupError` (`lup/errors.py`), and every name ends in `Error` (`docs/conventions.md`, *Errors*). It's one root per package, not one per area, so a caller catches everything the library raises in one `except`. An ask's errors are classified from what the runtime reports in structured form, never from its message, so a caller branches on the type.

| Error | When | Retried by recovery |
|---|---|---|
| `TurnError` | The base of every error below but the last two; raised itself for any other failure the runtime reports, carrying what it said | No |
| `AgentUnavailableError` | The model is out of reach for a while: overload, a rate limit, a server error, a connection that failed or dropped | Yes |
| `UsageLimitReachedError` | The account's usage window is spent; `reset_at` says when it resets, where reported | No |
| `AuthMissingError` | No usable login, or the login refused | No |
| `OutputMissingError` | No answer accepted within `submission.attempts`; `rejected` holds every refused attempt in full | No |
| `ProblemReportedError` | The agent called `report`; `problem` and `notes` are its words | No |
| `ToolsPresentError` | The session loaded tools beyond lup's own; `tools` lists what it loaded | No |
| `TurnTimeoutError` | The timeout passed, and the turn was interrupted | No |
| `RuntimeMissingError` | An ask runs on a runtime whose extra isn't installed ("install `lup[codex]`"), or its runtime is missing | No |
| `RealCallInTestError` | A test reached a real agent (*Testing*) | No |

- `TurnTimeoutError` is also the built-in `TimeoutError` **(leaning)**, so code catching that catches it, and so does `except LupError`.
- Unclassified failures raise the base `TurnError` itself **(leaning)**, rather than a guess at a subclass a caller would act on wrongly.
- Outside an ask: `ToolError` (`lup.tools.tool`), a function that can't be a tool, and `UnscriptedAskError` (`lup.testing.fake`), an ask the fake has no script for.
- A spent budget has no error in this slice: budgets come later.

Each adapter's classification is in its section.

## The call record

Every ask, answered or failed, appends one `CallRecord` (`observability/trace.py`) to `layers.trace` when it's set. A record holds:
- the runtime and the model the declaration named, none where it left the choice to the runtime;
- the start time and the duration;
- the prompt and the system prompt, in full;
- the output in full (the model as JSON, or the text), or the error's type and message;
- the rejected attempts, on an answer and on `OutputMissingError`;
- the notes, on an answer and on `ProblemReportedError`;
- the token usage, with the cost where the runtime reports it, on an answer; none on a failure.

It's derived from the result, or the error, and the request, so the record and the result can't disagree. Claude reports cost; Codex reports tokens only. The dashboard reads the same records once events exist.

## Testing: the fake and the guard

**The fake replaces the adapter, not the agent.** A test's `Claude(...)` goes through the real `ask`: the layers, the output tool and its guard, the record. Only the turn is scripted, and a scripted answer, note or report goes through the real tools, so validation and `before` hooks run as they would on a real turn. It stands in at the seam (`sessions/contract.py`), a context variable holding what chooses each declaration's adapter. A fake `Agent` would skip the layers a test should exercise; monkeypatching would repeat the stub in every project.
- `fake_agents.answer(Output, value, notes=[...])` queues an accepted answer for the next ask of that output type, after the notes.
- `fake_agents.answer_text(text, notes=[...])` queues the answer to the next untyped ask.
- `fake_agents.reject_then(Output, invalid, value)` queues a refused submission before the accepted one: arguments that don't validate, or a value a `before` hook denies.
- `fake_agents.report(Output, problem, notes=[...])` queues a reported problem; `Output` is `None` for an untyped ask.
- `fake_agents.fail(Output, error)` makes the next ask raise `error`, as a runtime would.
- `fake_agents.calls` lists every ask, each a `FakeCall` with its declaration, prompt and output model.
- An ask with nothing scripted raises `UnscriptedAskError`, naming the output type and the prompt.

Scripts are matched by output type, the first queued first. A fake turn reports no usage and the session ids `fake-1`, `fake-2`, and so on.

**The guard is on in every test session of every project that installs lup,** through the pytest plugin `lup` declares (a `pytest11` entry point, `testing/plugin.py`), rather than opt-in per project:
- **Real turns:** outside `fake_agents`, the seam refuses every declaration's turns with `RealCallInTestError`, naming the fixture to use instead. A real adapter built directly in a test refuses too **(leaning)**: the plugin sets `guarded`, which each adapter's client factory checks before it starts its runtime, so nothing reaches a runtime around the seam. `RealCallInTestError` sits with the session errors **(leaning)**, so an adapter raises it without importing pytest.
- **Network:** connections are refused except to loopback (`127.0.0.1` and `::1`, unless the project names its own hosts) and Unix sockets, through `pytest-socket`, whose per-test `enable_socket` marker lifts it.
- **Missing extra:** without `lup[testing]`, the plugin stops the session and names the extra, rather than running unguarded.

## The Claude adapter

`adapters/claude/` holds the declaration (`__init__.py`) and `ClaudeAdapter` (`runtime.py`), the only module importing `claude_agent_sdk` and `mcp`. Each turn runs in a Claude Code process of its own, through the SDK's `ClaudeSDKClient`, the SDK's one client that can interrupt, with the options of *No tools but lup's own* and *Out of the operator's history*, lup's MCP server, and the `Stop` hook.

- **System prompt.** `system_prompt` becomes `--system-prompt`, which replaces Claude Code's whole prompt; none sends an empty one. Claude Code still adds an identity line of its own ("You are a Claude agent, built on Anthropic's Claude Agent SDK.", read in the bundled CLI).
- **The guard** is an in-process `Stop` hook asking the toolbox whether the turn may end. A refusal (`decision: block`) keeps the same turn going, and the model reads the reason. Claude Code honours 8 refusals in a row, a tool call resetting the count, so the submission attempts (3 by default) run out first; once they have, the hook lets the turn end and the ask raises `OutputMissingError`. `Stop` doesn't fire on an interrupt or an API error.
- **Errors.** `ClaudeSDKClient` raises nothing when a turn fails: the result's `is_error` says so. The adapter classifies the failure from the result's fields (`api_error_status`, `terminal_reason`) and the assistant messages' `error`, in this order:
  - `AuthMissingError`: an assistant message's `authentication_failed`, or an API status of 401. A missing login shows only in the assistant message, with no status;
  - `UsageLimitReachedError`: the turn failed and the last `RateLimitEvent` said `rejected`, with the window's reset (`resets_at`) where given. It's raised for the failed turn, not on the event **(leaning)**: a rejected window that still lets the turn finish (overage) isn't an error;
  - `AgentUnavailableError`: an API status of 429 or 5xx (an overloaded API is 529), an assistant message's `rate_limit` or `server_error`, or an API error (`terminal_reason` `api_error`) with no status, meaning no response arrived, which is how a dropped connection is taken;
  - `RuntimeMissingError`: the bundled CLI is missing (`CLINotFoundError`);
  - `TurnError` for anything else: a refused request (400), a crashed CLI, a turn with no result. A `ResultError` the SDK raises is classified the same way.
- **Cancellation.** A cancelled turn, as when the timeout passes, is interrupted before the cancellation goes on; the client is disconnected either way.
- **Usage** is the result's input, output, cache-read and cache-write tokens, with its `total_cost_usd`. The session id is Claude Code's.
- **Tests** drive it on a scripted client: the client factory is a field (`client`), defaulting to the SDK's own behind the guard **(leaning)**, so a test runs the real MCP server and hook without patching the SDK.

What it relies on, from claude-agent-sdk 0.2.165 and the Claude Code 2.1.294 it bundles, read in the SDK's source and checked against the bundled CLI with a scripted Messages API, is in `runtime.py`'s docstring and `docs/field-notes.md`.

## The Codex adapter

`adapters/codex/` holds the declaration (`__init__.py`); `CodexAdapter` (`runtime.py`), the only module importing `openai_codex`; lup's Codex home (`layout.py`); and the variables the adapter reads (`settings.py`: `CODEX_HOME`, `XDG_STATE_HOME`). The home and its variables live in the adapter, not in lup's own settings and layout **(leaning)**, since a runtime is named only in its adapter (`docs/conventions.md`, *Imports and boundaries*).

- **The client.** The adapter drives the SDK's lower `CodexClient` **(leaning)**: the documented `Codex` and `AsyncCodex` take no handler for Codex's requests to the client, which lup's tools need. Its raw `request` reaches what the SDK doesn't wrap (`account/read`, and `thread/start` with `environments`).
- **A process per ask (leaning).** Each ask starts a `codex app-server` of its own in lup's home: start, initialize, check the login, start the thread with lup's tools, take turns. The process is closed at the end, whatever happened.
- **System prompt.** `system_prompt` is the thread's `baseInstructions`, which replaces Codex's own prompt and arrives as the first developer message. None sends it empty, so no developer message at all **(leaning)**: left out, Codex would send its own coding agent's prompt, describing tools the session doesn't have.
- **Effort** goes on each `turn/start`; `thread/start` takes none.
- **lup's tools.** Codex's `item/tool/call` requests reach a handler on the SDK's one reader thread, which hands each call to the event loop the ask runs on and waits for the toolbox's answer (`contentItems` and `success`). The loop stays free for it because every blocking client call runs in a worker thread. A question for the user is answered with a refusal, and any other request fails the ask (*No tools but lup's own*).
- **The guard.** Codex's hooks are commands configured in files, not callbacks, so the end of a turn is guarded in the adapter: once a turn completes, the toolbox says whether it may end, and where it may not, the same thread takes another turn whose one message is the toolbox's reason. The thread keeps its history, so the prompt isn't sent again.
- **Errors** are classified from the `codexErrorInfo` of the last error Codex reported without retrying it (`willRetry: false`), or the turn's own error:
  - `AgentUnavailableError`: `serverOverloaded`, `internalServerError`, `rateLimitExceeded`, and a connection that failed or dropped (`httpConnectionFailed`, `responseStreamConnectionFailed`, `responseStreamDisconnected`, `responseTooManyFailedAttempts`) with no status, a 408, a 429 or a 5xx; also an app-server too busy to take the ask;
  - `UsageLimitReachedError`: `usageLimitExceeded`, with the reset from the last `account/rateLimits/updated`. That's the latest reset among the windows reported full, or the primary window's where none is **(leaning)**, so a spent weekly window resets when it does, not when the shorter one does;
  - `AuthMissingError`: `unauthorized`, a connection error with a 401, or no login before the thread starts;
  - `TurnError` for anything else: a connection error with another 4xx, which isn't retried since the request itself was refused **(leaning)**; a full context window, a bad request, a policy, a kind lup doesn't know; a turn Codex ended as interrupted without being asked; the app-server failing.
- **The reset arrives outside the turn.** Codex reports the rate limits that came with a usage limit before the error, outside any turn's stream (`next_notification`). A watcher thread per session keeps the last report; nothing synchronises it with the turn's stream, so a reset can in principle be missed (*Checks owed*).
- **Usage** is the thread's running total once its turns are done (`thread/tokenUsage/updated`'s `total`), since the per-request count is sent again on turns that made no request. The thread is the ask's own, so the total started at zero. Codex counts cached input among its input tokens; lup counts it apart, so `input_tokens` is the input not read from cache, as on Claude. Codex reports no cost. The session id is the thread's.
- **Cancellation** interrupts the turn (`turn/interrupt`) before the cancellation goes on; an interrupt that fails is noted on the cancellation.
- **Tests** drive it on a scripted client: the client factory is a field (`connect`) **(leaning)**, and Codex's requests go through the real handler, so tool calls reach the real toolbox.

What it relies on, from `openai-codex` 0.162.0 and the codex-cli 0.162.0 it pins, read in their source and checked against a local mock of the Responses endpoint, is in `runtime.py`'s docstring and `docs/field-notes.md`. No real model has run it yet (*Checks owed*).

## Modules

```
packages/lup/src/lup/
  __init__.py              the front door: the neutral names, Claude and Codex
  types.py                 Model, MutableModel and Settings, the bases every model starts from; JsonObject
  errors.py                LupError, the root of every error lup raises
  sessions/
    surface.py             Agent, the ABC code naming no runtime holds
    declaration.py         Declaration, the fields every declaration has; Asking, an ask inside its layers
    contract.py            Adapter, TurnRequest and RawTurn: what a runtime's adapter implements; the seam and `guarded`
    layers.py              SessionLayers, Recovery, Submission
    submission.py          Toolbox: one turn's tools, the calls made to them, and the guard
    results.py             TurnResult, Usage, Rejection
    errors.py              the errors an ask raises, RuntimeMissingError and RealCallInTestError; needs_extra
  tools/
    tool.py                @lup_tool, Tool, AgentTool and ToolSpec; Allow and Deny; ToolError
    submit.py              Submit, the output tool, and its Receipt
    speaking.py            report and note
  observability/
    trace.py               CallRecord, and appending it to the trace
  testing/
    fake.py                FakeAgents, FakeCall, UnscriptedAskError
    plugin.py              the pytest plugin: the guard, and the fake_agents fixture
  adapters/
    claude/__init__.py     Claude, the declaration
    claude/runtime.py      ClaudeAdapter: the options, lup's MCP server, the Stop hook, the init check, the errors
    codex/__init__.py      Codex, the declaration
    codex/runtime.py       CodexAdapter: the launch, the thread, dynamic tools, the continuation, the errors, usage
    codex/layout.py        CodexLayout: lup's own Codex home, and the operator's login it links to
    codex/settings.py      CodexSettings: CODEX_HOME and XDG_STATE_HOME
```

Runtime-neutral code lives under `sessions/` and `tools/`, one adapter per runtime under `adapters/`: named `adapters`, not `providers`, since a provider also means a model provider or a compatible endpoint, which the connection will name. An adapter imports its runtime's SDK inside `ask`, under `needs_extra`, which is how a missing extra becomes `RuntimeMissingError` naming the extra instead of an import error deep inside; the declaration, its effort levels (`Effort`, in the adapter's `__init__.py`) and its terminal compile never import it. Import contracts in the root `pyproject.toml` keep each SDK in its adapter (`claude_agent_sdk` in `lup.adapters.claude`, `openai_codex` in `lup.adapters.codex`), keep anything inside `lup` from importing its front door, and keep the library from importing the environment.

The tests are in `packages/lup/tests/`: `test_ask.py` (an ask through the real layers, on the fake), `test_tools.py` (tools and the toolbox's guard), `test_types.py` (the model bases), and `test_claude.py` and `test_codex.py` (each adapter on a scripted client: no process, no network). The docstrings' examples run as doctests.

## Repository layout and packages

One repository, a uv workspace sharing one lock file, whose packages are versioned and installed separately, rather than one distribution with extras:
- `packages/lup/`: the library, `lup`;
- `packages/lup-dev/`: the environment, `lup-dev` (imported as `lup_dev`);
- `packages/lup-dashboard/`: the dashboard, behind its typed protocol, once it starts.

Dependencies run one way: the dashboard, then `lup-dev`, then `lup`.

**Dependencies:** `pydantic`, `pydantic-settings`, `tenacity` for recovery, `mcp` for lup's own tool server, and `tomlkit` for the settings a runtime reads as TOML. **Extras:**
- `lup[claude]`: `claude-agent-sdk`;
- `lup[codex]`: `openai-codex`;
- `lup[testing]`: `pytest` and `pytest-socket`.

Each SDK ships its runtime's binary (about 240 MB and 360 MB installed), so a project installs only the side it uses. That's the one reason for an extra: every other library, even one a single runtime's adapter uses today, is a dependency of the package, so the split stays one rule rather than one per library. The SDKs drive the runtimes, rather than runtime clients of lup's own. lup's own development group installs all three extras, since every shared construct is tested on both runtimes.

**Pinned runtimes.** A runtime is the one its SDK bundles, not whatever is on `PATH`, so the lock file pins it: claude-agent-sdk 0.2.165 bundles Claude Code 2.1.294, and openai-codex 0.162.0 pins codex-cli 0.162.0.

**Python 3.14 or later**, for its lazily evaluated annotations. Python 3.12 would need `from __future__ import annotations` in every file, which turns annotations into strings; pydantic then fails on names imported only for type checking, and on models defined inside functions.

## Later slices

On the same declarations:
- **Conversations** (`DESIGN.md`, *Sessions (leaning)*): `async with agent.open(resume=None)` gives a fresh session, and `session.ask()` returns a lazy `Turn[T]`, awaited for its result or iterated for its content, with `live()` and `interrupt()`. History comes from the runtime's own record, with lup's writer keeping a scrubbed copy, and a refused resume raises. Sessions that are kept run under their own config home, on Claude too. On Codex a conversation declares its output types when it opens, since a thread's tools are fixed when it starts. Forking at a turn needs a turn id, which `TurnResult` doesn't carry yet.
- **Tools and events:** project tools, their groups and the declaration's `tools` field, each tool declaring where it runs (`runs="inside"` or `"outside"`); the neutral hooks on the runtime's own tools; a large result written to a file, the agent getting its path and a preview; keeping a tool server out of tool search; passing a third-party MCP server through; the result's messages, once a turn has something in it; the events anything long-running emits.
- **Checked model ids,** with portable tiers, and an effort a model can't take refused at declaration.
- **The usage-limit wait (leaning):** waiting for a spent window to reset, on by default and bounded by the timeout.
- **The connection:** an endpoint and an API key as one value, given when a client is created, for products other people use.
- **Rooms,** `spawn` and `launch`, with containers and mounts, Bash and the tools that write.
- **Runs** and the outcome loop; `SharedBudget`.
- **The gate listing each `enable_socket` marker,** like a suppression.
- **The capability check,** which takes in Codex's live tool check.

## Checks owed

- **Live runs beyond a typed answer.** One typed ask ran live on each runtime, with the operator's logins: Claude on `haiku` (lup's MCP server through the real CLI, the `init` check passing, the answer through `mcp__lup__submit`; no transcript written) and Codex on `gpt-6.1-sol` (code mode: `exec` calling `submit`; everything in lup's own home, nothing in the operator's). Still owed live:
  - on Claude, the `Stop` guard holding an unanswered turn, and the error classification;
  - on Codex, the dynamic tool called directly on a model without code mode, and the tool-free configuration, that the model's request carries only lup's tools. That last is the declared gap's check, owed again on each pinned version.
- **A subscription's spent window on Claude:** how a `RateLimitEvent` with status `rejected` surfaces under a subscription login. An API key's 429 emitted none.
- **A dropped connection on Claude:** what it reports; it's taken as an API error with no status.
- **The Codex reset time** arrives on a thread of its own, before the error and outside the turn's stream. Nothing synchronises the two, so a real run could miss it and report no reset; the deterministic alternative is asking `account/rateLimits/read` after the error.
- **Parallel startups.** Simultaneous Claude Code startups have corrupted `~/.claude.json` in earlier versions, and the adapter uses the default home, so a live check must show whether 2.1.294 still does. On Codex, parallel asks each start an app-server on lup's one home: that their startups don't conflict over its state.
