 Only the application package directory (`src/<project>/`) carries the project name; all framework vocabulary (`lup_tool`, `LupMcpTool`, `lup-devtools`, the `lup` library, the `lup` CLI entry point) stays as `lup`.

### Important Context

**[Add domain-specific context here. Examples:]**

- What outcomes matter and how they're measured
- What data sources are available
- What constraints or limitations exist

### The Bitter Lesson

The single most important principle for improving this agent: **give it more tools and capabilities, not more rules.**

| Do This                                               | Not This                                           |
| ----------------------------------------------------- | -------------------------------------------------- |
| Add tools that provide data                           | Add prompt rules that constrain behavior           |
| Apply general principles                              | Apply specific pattern patches                     |
| Communicate principles and the _why_                  | Prescribe rigid mechanical procedures              |
| Provide state/context via tools                       | Use f-string prompt engineering                    |
| Ask for the `strongest` tier and a high `effort`      | Compensate for weak reasoning with complex prompts |
| See what went wrong from first principles             | Make small edits to patch one mistake              |
| Create subagents for specialized work                 | Build complex pipelines in main agent              |

**Tools are the primary scaffold.** When the agent struggles, the answer is almost always a missing tool — not a missing prompt paragraph. A tool that returns the right data at the right time is worth more than any amount of prompt engineering.

**The test:** Does this change add a capability, or just a rule? Would it still help if the domain changed completely? If not, it's over-fitted.

### Tool Design Philosophy

Tools are the interface between the agent and its environment. They outlast any particular prompt revision, and they compose — each new tool multiplies the agent's options rather than constraining them.

**Prompts rot; tools don't.** Tool names and sets change as the agent evolves. If the prompt lists them, every addition or rename means updating two places that can drift apart. Letting the agent discover tools through their descriptions keeps the prompt focused on _what to do_ and _how to reason_ — things that stay stable.

**The tool description is the contract.** It's the only documentation the agent sees for a tool. When the agent misuses a tool or ignores one it should use, the description is usually the problem. A good description answers:

1. **What** — What does this tool do? (concrete behavior, not vague summary)
2. **When** — When should the agent reach for this tool? (triggers, conditions)
3. **Why** — Why does this tool exist? (what problem it solves, what gap it fills)

Compare: `"Search the web for information"` vs. `"Search the web using keyword queries. Use this when the agent needs current information not available in local data, or when verifying claims against external sources. Exists because the agent has no built-in knowledge of events after its training cutoff. Returns a list of {title, url, snippet} results ordered by relevance."`

The first leaves the agent guessing about when and why. The second makes the tool self-selecting — the agent can match its situation to the description without prompt-level instructions.

### Persistent Agent Pattern

For agents that exist over time — maintaining conversations, monitoring systems, playing games, running autonomous workflows — the architecture inverts: the agent is a **persistent presence** that controls its own attention, not a processor steered by an event queue.

| Do This                                                     | Not This                                    |
| ----------------------------------------------------------- | ------------------------------------------- |
| Agent sleeps when it chooses, wakes on events               | Event queue drives agent responses          |
| All timing is tools (sleep, debounce, remind, schedule)     | Hardcode delays or polling in orchestration |
| Stop hook prevents turn from ending — only sleep yields     | Request-response per event                  |
| Pull-based state reading (agent calls `context` when ready) | Push state changes as SDK user turns        |
| Agent parks thoughts (ideas, reminders) for later           | Drop context between interactions           |
| Expose environment state as tool-readable data              | Hide activity from the agent                |

**The core loop:** The agent never ends its turn. Instead it cycles: wake → read context → think → act → meta-assess → sleep. The only way to yield control is `sleep()`, so the agent decides when to engage, when to wait, and when to come back — it can debounce bursts, schedule actions, set reminders, and park thoughts, where a queue would force a reaction to every event.

### Reflection Pattern

Agents produce better output when forced to self-assess before committing. A reflection tool records confidence, uncertainties, and a tool audit, and runs an independent nested reviewer whose verdict opens or holds a gate; the gate rides inside submission, so a gated turn is rejected with a retriable message until the reviewer passes. The tool and its input model are the domain-specific half — add the fields your domain is actually judged on — while the gate is domain-neutral.

[docs/orchestration.md](docs/orchestration.md) carries both patterns in full: the scheduler and relay wirings, which backend inverts the loop and why, the gate's escape hatch after repeated failures, and where each piece lives.

---

<!-- section: Getting Started -->
# Getting Started

## Reference Files

Which file holds what is reference material — consulted once, when you already
know you need it — so it lives in the generated pages rather than here:
[docs/template.md](docs/template.md) for the application you customize, and
[docs/library.md](docs/library.md) for the `lup` package beneath it. Both are
generated from the same declarations this guidance is, so neither can fall
behind the tree it describes.

The three you will open first: `agent/prompts.py` for what the agent is told,
`agent/toolsets.py` for the tool-group registry — the one place a group is
added — and `agent/core.py` for how a session is composed.

**Versioning:**

- **pyproject.toml `[tool.lup] agent_version`**: The agent version — bump on behavior changes with `uv run lup-devtools version bump` (or `{{ bump_skill }}`)

**Environment:**

- **src/<project>/environment/cli/\_\_main\_\_.py**: Typer CLI — the `lup` entry point with `run` and `loop` (batch + auto-commit) commands

## Commands

```bash
uv sync                                  # install; `uv add <pkg>` to add, never edit pyproject.toml
uv run lup-devtools dev check            # the pre-flight bar: ruff, pyright, tests
uv run lup run "your task here"          # one session; --session-id names it
uv run lup loop "task1" "task2"          # several, auto-committing each
uv run lup-devtools setup                # keys, integrations, env vars (`dashboard` for the web UI)
```

`AGENT_SDK` and `AGENT_MODEL` pick the runtime and the model a session opens
against. `uv run lup --help` and `uv run lup-devtools --help` are the full
trees; [docs/contributing.md](docs/contributing.md) is the tour.

## Testing

`uv run pytest`, narrowed with `-k "<pattern>"` or a path when you want one
case. `tests/unit/` mocks external APIs; `tests/integration/` needs real keys
and is marked `@pytest.mark.integration`.

## Test Principles

**Test behavior, not construction.** Never test that a constructor sets attributes — that's testing the framework (Pydantic, dataclasses), not your code. If a class is a pure data container with no methods, computed properties, or custom validation, it doesn't need tests.

**Every test should answer: "what could go wrong?"** If nothing can go wrong (e.g., `assert artifact.name == "solution.py"` after setting `name="solution.py"`), the test is worthless. Good tests exercise:

- **State transitions** — does adding then removing leave the system clean?
- **Edge cases** — empty inputs, missing files, duplicate names, boundary values
- **Invariants** — properties that must hold across operations (e.g., cleanup stops all sandboxes)
- **Integration points** — does the code read from disk correctly? Does it compose with its dependencies?

**The test for a test:** Remove it. Does the remaining suite still catch real bugs? If yes, the test was dead weight.

| Write Tests For                           | Don't Write Tests For                        |
| ----------------------------------------- | -------------------------------------------- |
| Computed properties that read from disk   | Pydantic model construction                  |
| Registry CRUD with state verification     | Attribute access after `__init__`            |
| Error paths and graceful degradation      | Default field values                         |
| Multi-step workflows (add → use → remove) | Constants (`assert "Bash" in BUILTIN_TOOLS`) |
| Concurrency and timing behavior           | Sorted output of deterministic functions     |

## Debugging

**Do not hypothesize -- trace.** When debugging errors, find the actual logs and read the exact exception. Do not list "likely causes" or suggest the user check things. Open the log files yourself, grep for the error, read the traceback, and report what actually happened. If the logs don't contain enough information, say exactly what logging to add and where, so the error is captured next time.

Use `{{ debug_skill }} <error message>` to trace an error through the logs automatically.

## Feedback Loop Scripts

```bash
# Collect feedback from sessions
uv run lup-devtools feedback collect --all-time

# Status: version, data, analysis state, aggregate stats
uv run lup-devtools feedback status

# Analyze traces
uv run lup-devtools trace list
uv run lup-devtools trace show <session_id>
```

---

# Customization Guide

### Step 1: Run {{ init_skill }}

The `{{ init_skill }}` command walks you through customizing the template for your domain. It asks about:

- What your agent does
- How outcomes/ground truth are measured
- What metrics matter

### Step 2: Customize Models

Edit `src/<project>/agent/models.py`:

- `AgentOutput`: Your agent's structured output format
- `Factor`: Reasoning factors that influence outputs
- `SessionResult`: Complete session data for feedback analysis

### Step 3: Define Subagents

Edit `src/<project>/agent/subagents.py`:

- Create specialized subagents for focused tasks
- Define which tools each subagent can use
- Choose a model tier per subagent (strongest by default — see Model Selection; cheaper only with an explicit reason)

### Step 4: Configure Tools

Edit `src/<project>/agent/toolsets.py` and `src/<project>/agent/tool_policy.py`:

- Register tool groups once in `toolsets.py` — the single source every backend builds its servers from
- Tag tools that need credentials (`lup_tool(..., tags=["requires:<service>"])`)
- Map missing settings to excluded tags in `ToolPolicy`; `filter_tools()` drops tagged tools before server registration
- Add MCP server configurations
- Availability is enforced at runtime by an allowlist PreToolUse hook (`create_tool_allowlist_hook`) — the SDK's `allowed_tools` option is ignored under `bypassPermissions`

### Step 5: Configure Reflection

Edit `src/<project>/agent/tools/reflect.py`:

- Customize `ReflectInput` fields for your domain (e.g., factor analysis for forecasting)
- Customize the reviewer system prompt for your domain's failure modes
- Decide whether the nested reviewer agent adds value (adds latency but catches errors)
- The gate in `core.py` is already wired — reflection is enforced by default

### Step 6: Set Agent Version

The agent version lives in `pyproject.toml` under `[tool.lup]`:

```toml
[tool.lup]
agent_version = "0.1.0"
```

- Set the initial version during init
- Bump on behavior changes (prompts, tools, subagents) with `uv run lup-devtools version bump <level>` or `{{ bump_skill }}`

### Step 7: Enable Persistent Agent Mode (Optional)

For agents that exist over time (conversations, monitoring, games), use the persistent agent pattern:

- Wire `Scheduler` from `lup.orchestration.realtime.scheduler` into your session
- Add Stop hook to prevent turn ending (`create_stop_guard`)
- Implement sleep/context/reply tools from `agent/tools/realtime.py`
- Replace the request-response `run_agent()` in `core.py` with a sleep/wake loop
- The reflection gate also works here — gate `sleep` instead of `submit_output`

### Step 8: Update Feedback Collection

Edit `src/<project>/devtools/feedback/`:

- Implement `load_outcomes()` for your domain (`state.py`)
- Customize `compute_metrics()` for your metrics (`metrics.py`)
- Add domain-specific summary output (`reports.py`)

## Scaffolding Is a Menu, Not a Mandate

Everything lup ships belongs to a **module** — one subject as one value, carrying its skills, its agents, its page under `docs/`, its paragraph in this document, its command tree and its tool group. A module is taken or declined whole, so declining is a name in `DECLINED` rather than files to hunt down, and there is no keeping a subject's skills while deleting its page. `dev modules` prints the roster with what each contributes and what its prose costs; a module left unnamed keeps its own default, including the ones lup grows after that line was last edited.

Declining is a **first-class outcome, not a failure**: a module this domain has no subject for spends guidance budget and session context every session and earns nothing. The goal is the smallest roster that fits, not the fullest. Three ship off by default and are the ones most worth a deliberate answer:

| Module | Take it when… | Decline it when… |
| --- | --- | --- |
| **`reflection`** | the agent commits a consequential, judgment-bearing output where self-critique improves calibration (a forecast, a diagnosis, a scored decision) | the task is mechanical, trivial or high-volume, or there is no discrete final output to reflect on — then the gated `review` tool is dead weight |
| **`realtime`** | the agent is a presence over time — a conversation, a monitor, a long game — that controls its own attention | the agent is one-shot request→output, which is most domains; the relay and the Scheduler are pure cost |
| **`feedback-loop`** | ground truth or a feedback signal resolves over time to drive iteration | there is no ground truth and the agent is not iterated against outcomes — `load_outcomes` stays an empty stub |

One pattern here is not a module, because it is this template's own wiring rather than a subject lup ships: the **commit loop** (`environment/cli` auto-commit) is kept when each run yields a data artifact worth versioning per session, and dropped when the agent is interactive or produces no per-session artifact worth a checkpoint.

The same logic governs native subagents (harness-dispatched roles sharing the main session), background agents, and nested agents (tool-subagents opened inside a tool handler via `query()`): wire them only where the domain needs that shape.