# Backend ABC Refactor — Architecture Design

**Status:** Design proposal for user review. **No source has been changed.**
**Scope:** The `backend-abc` concern from `tmp/resolve-plan.json` (~30 notes, the dominant theme).
**Base commit:** `64602af`.

The single complaint behind every note in this concern: **backend (claude / codex / openai) concerns leak out of `lup`'s adapter layer instead of living behind a clean ABC.** Callers (`core.py`, `common.query()`, `background.py`, even template tool files like `reflect.py`) branch on the backend with `match`, and per-backend option construction lives in the template instead of the library. This document proposes how to confine all backend dispatch behind the adapter ABC and pass a single unified options object through the boundary.

The good news: the foundation already exists and the user has explicitly approved it. `lup/types.py` (the unified `Lup*` vocabulary) is approved verbatim (`types.py:17`), and `common.py` already defines `AgentAdapter` / `Conversation` / `AdapterCapabilities` ABCs. The refactor is **not** a rewrite — it is (a) deleting the `match`-on-backend dispatch sites by routing through a registry/polymorphism, (b) moving per-backend option construction out of `core.py` into each adapter, and (c) folding the Claude three-file split into one subpackage that visibly implements the ABC.

---

## 1. Problem statement

### 1.1 Every backend-dispatch (`match`) site

Confirmed by `rg 'match\s+(backend|sdk|settings\.agent_sdk|model_backend|server_group)'`:

| # | Site | What it dispatches on | Note |
|---|------|----------------------|------|
| 1 | `packages/lup/src/lup/adapters/common.py:299` | `match backend:` in `query()` → `claude_query` / `CodexAdapter` / `OpenAICompatibleAdapter` | `common.py:299,300` — "No. THis is the wrong way to do it. Right way is there's an ABC for calling run/query"; "Never match on backend this way, it just doesn't scale" |
| 2 | `packages/lup/src/lup/background.py:153` | `match sdk:` in `create_background_agent()` → `ClaudeBackgroundAgent` / `CodexBackgroundAgent` | `background.py:153` — "Please don't, this is really not the right way to make a scalable architecture" |
| 3 | `src/lup_template/agent/core.py:413` | `match settings.agent_sdk:` in `build_codex_realtime_adapter()` → openai vs codex | `core.py:414` — "no. Do not match backend in core" |
| 4 | `src/lup_template/agent/core.py:524` | `match settings.agent_sdk:` in `build_adapter()` → claude / codex / openai | `core.py:519,523,548` — tuple smell, "why is this in core", "how is openai different from codex" |
| 5 | `src/lup_template/agent/tools/reflect.py:186` | `match model_backend(model):` inside the reviewer tool → anthropic vs other | `reflect.py:187` — "NO. … Backend concerns should only appear in the designated lib sections, all the rest should be unified." |
| 6 | `src/lup_template/devtools/agent/serve.py:105` | `match server_group:` (string cases) | `serve.py:113,114,115` + `antipattern-direction` — "extremely hard-coded", "type str is wrong, should be Literal", "serve should reuse the same server from core" |

Sites 1–5 are *backend* dispatch and belong to this concern. Site 6 is *tool-group* dispatch — adjacent (`serve.py` is in this concern's file list because it also rebuilds the server core already builds); the `match str` → `Literal` policy question is owned by `antipattern-direction`, but the dedup ("reuse core's server") is resolved here (§3.7).

There is also a **soft** dispatch worth noting: `common.query()` (lines 274–297) hand-maintains a `claude_only` dict of options and raises if any are set on a non-anthropic backend. This is the same leak in a different shape — the knowledge "which options are Claude-only" lives in the dispatcher instead of in `AdapterCapabilities` / each adapter. `core.check_settings_supported()` (`core.py:242`, **user-approved** at `core.py:243`) already does the capability-driven version of this correctly — `query()` should converge on that pattern.

### 1.2 Per-backend option construction living in the template

`core.py` is the worst offender. It contains *five* backend-specific builders plus two budget/cleanup helpers, none unified:

- `build_options()` (`core.py:106`) — builds `ClaudeAgentOptions`. Hand-sets Claude-only knobs: `max_thinking_tokens` (`:221`), `extra_args={"no-session-persistence": None}` (`:223`), `effort=cast("EffortLevel|None", ...)` (`:238`, cast smell). Note `core.py:111` — "should return a generic option … passed to something like build_claude"; `core.py:220` — "have build_claude … construct max_thinking_tokens itself".
- `build_codex_session()` (`core.py:270`) — returns `tuple[str, dict[str, str], list[Path]]`. Note `core.py:277,278,279,280` — tuple smell, unreadable return type, "Why do we need both build_claude_options and build_codex_session", "This is really not unified".
- `codex_budget_options()` (`core.py:325`) — returns `tuple[float|None, UsageCost|None]`. Note `core.py:326` — "patchy".
- `build_codex_adapter()` (`core.py:355`), `build_codex_realtime_adapter()` (`core.py:386`, contains `match`), `build_openai_adapter()` (`core.py:455`). Notes `core.py:359,399,458` — "build_codex shouldn't be so fragmented, and this shouldn't be in core".
- `build_adapter()` (`core.py:509`) — the `match settings.agent_sdk` entry point, returns `tuple[AgentAdapter, ctx, NotesConfig]`.
- `run_persistent_agent()` (`core.py:610`) — separate entry point returning a bare `int` (`core.py:616` — "Why a separate function? Why does it return an int — did you forget to type alias?").

The deeper problem: **`core.py` knows the shape of every backend's native options.** It imports `ClaudeAgentOptions`, `EffortLevel`, `UsageCost`; it knows Codex needs `(system_prompt, mcp_env, writable_roots)`; it knows openai needs `base_url`/`api_key`/`model_provider`. That knowledge is exactly what should live behind the ABC.

### 1.3 The Claude three-file split has no stated contract

`claude.py`, `claude_client.py`, `claude_background.py` divide Claude support three ways with no ABC binding them and overlapping responsibilities:

- `claude.py` (`:1,2`) — "very unclear why we need this file, claude_client.py and claude_background.py. Seems like a flawed dichotomy"; "if you really need several files … put them in a claude subfolder". Contains converters (`claude_block_to_lup`, `claude_message_to_lup`, `spec_to_claude`, hook converters), `collect_lup_response`, `ClaudeConversation`, `ClaudeAdapter`. `claude.py:220` — "this really seems like we're lacking an abstraction, ABC … See how we do it in tacocast".
- `claude_client.py` (`:1,2`) — "This really screams 'we're implementing an ABC', but there's no ABC to be seen. This seems dangerous"; "query and collector should be interfaces already specified". Contains a **second** `query()` (the rich `ResponseCollector` one), `build_client()`, `prepare_output_format()`, and `claude_query()` (the lup-typed one that `common.query()` calls).
- `claude_background.py` (`:24`) — "unclear what this is and how it differs with claude.py". `claude_background.py:65` — `message_generator` yields `dict[str, object]` (anti-pattern the edit hook missed; "yield well-typed pydantic objects").

The split is real duplication: there are **two** `query()` functions (`common.query` lup-typed dispatcher, `claude_client.query` Claude-only rich collector) and **two** response collectors (`collect_lup_response` in `claude.py`, `ResponseCollector` in `claude_client.py`) doing nearly the same message-draining loop.

The `openai_compat` duplication is also flagged: `core.py:548` — "how is openai different from codex? Why does this exist?". (`OpenAICompatibleAdapter` *subclasses* `CodexAdapter`, adding only a custom-provider config block — it is the same engine with one extra override. There is also a `# claude:` note at `openai_compat.py:6` arguing GLM should route through Claude scaffolding, not Codex — that is a separate routing-policy question, surfaced in §7.)

---

## 2. Target architecture

### 2.1 Principle (to be documented in CLAUDE.md + PATTERNS.md)

> **Backend management appears ONLY in `lup`'s designated adapter layer (`lup/adapters/<engine>/`).** Every consumer — `core.py`, tools, devtools, `query()` — passes a single backend-agnostic options object through the ABC and never names a backend. Adding a backend means adding one `adapters/<engine>/` package that fulfills the spec and registering it; it must touch no consumer. "One engine, one package, fulfilling the abstract spec" (the tacocast style the user cited).

The placement test (already in CLAUDE.md) decides every move: *does this module import from `lup_template`?* If no, and it is fundamental to running an agent → `lup`. The whole point is that after this refactor, **a `match` on a backend name anywhere outside `lup/adapters/` is a bug** (and §5 proposes making it a detectable one).

### 2.2 The adapter interface (mostly already exists)

`AgentAdapter` / `Conversation` / `AdapterCapabilities` in `common.py` are the right ABCs and stay. The refactor **strengthens** them so callers never need to branch:

```python
class AgentAdapter(ABC):
    @abstractmethod
    def conversation(self) -> AbstractAsyncContextManager[Conversation]: ...

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    async def run(self, prompt, *, trace_logger=None, prefix="") -> LupResponse: ...
    async def run_streamed(self, prompt, ...) -> AsyncGenerator[LupEvent, None]: ...
```

This is sufficient for the multi-turn / one-shot / streaming paths — they already route through it. What is missing is **construction**: today an adapter is built by `core.py` reaching for native option types. We add a construction contract (§2.4) so each adapter builds its own native options from the unified object.

`AdapterCapabilities` (`common.py:28–76`) is the existing, user-approved "parity contract as data." It already has the fields needed to retire the `claude_only` guard in `query()`: `max_turns`, `max_thinking_tokens`, `permission_modes`, etc. **No new ABC is needed for capabilities** — `query()` just needs to consult them the way `check_settings_supported` already does.

### 2.3 The unified options object — `LupAgentOptions`

A new backend-agnostic Pydantic model in `lup/types.py` (joining the approved `Lup*` vocabulary) or a new `lup/options.py`. It carries everything an adapter needs to construct a session, in backend-neutral terms:

```python
class LupAgentOptions(BaseModel):
    """Backend-agnostic session options. Each adapter's `build()` translates
    this into its native option object. The ONLY thing that crosses the
    template→lib boundary for session construction."""
    model_config = {"arbitrary_types_allowed": True}

    model: str
    system_prompt: str
    tool_servers: dict[str, LupMcpServerConfig | RawMcpServerConfig] = {}
    subagents: list[SubagentSpec] = []
    hooks: LupHooksConfig = {}
    allowed_tools: list[str] = []
    add_dirs: list[Path] = []

    # Backend-neutral knobs (each adapter maps or ignores per capabilities)
    permission_mode: PermissionMode | None = None
    max_turns: int | None = None
    max_thinking_tokens: int | None = None
    reasoning_effort: str | None = None     # generic; normalize_effort() maps it
    max_budget_usd: float | None = None
    turn_timeout_seconds: float | None = None
    usage_cost: UsageCost | None = None      # rates for token→USD (codex/openai)
    sandbox: SandboxConfig | None = None     # neutral; see §3 / open Q
    persist_session: bool = False            # replaces the no-session-persistence knob
    realtime: bool = False                   # persistent (sleep/wake) mode
```

Key points:
- `reasoning_effort` is **generic** (`str`), not `EffortLevel`. The Claude adapter calls `normalize_effort(opts.reasoning_effort, "anthropic")` (already in `types.py:365`) and casts *inside the adapter* where `EffortLevel` is in scope — **deleting the `cast` from `core.py:238`** (the cast smell the user flagged).
- `max_thinking_tokens` is carried generically; the Claude adapter decides whether to emit `max_thinking_tokens` vs `ThinkingConfigEnabled` and whether to **auto-switch for models newer than 4.6** (`core.py:219` — "we probably should auto switch for models newer than 4.6 since this is disallowed; verify with the doc"). That model-version logic lives in the Claude adapter, not the template.
- `persist_session` replaces the hand-set `extra_args={"no-session-persistence": None}` (`core.py:223`, `claude_client.py:289`, `claude_background.py:111`). The Claude adapter owns the `extra_args` wire detail; consumers just say "don't persist." (This is also the hook point for the inkwell session-cache feature in `feature-ports` — deferred, but the seam lands here.)
- `tool_servers` values are the `LupMcpServerConfig | RawMcpServerConfig` union — which **eliminates `tool_policy.ServerConfig = Any`** (`tool_policy.py:37`). Defining the union properly in `lup.mcp` (where both halves already live) lets pyright narrow by `isinstance`, so no `Any` and no `cast` (see §3.5).

### 2.4 The construction contract — `build()` per adapter

Two viable shapes; **recommendation: B** (factory function), with A as the fallback if the user prefers a method.

**Option A — abstract classmethod on the adapter:**
```python
class AgentAdapter(ABC):
    @classmethod
    @abstractmethod
    def build(cls, opts: LupAgentOptions) -> "AgentAdapter": ...
```
Then `ClaudeAdapter.build(opts)` constructs `ClaudeAgentOptions` internally (the `build_claude` the user keeps asking for), `CodexAdapter.build(opts)` constructs config-overrides + budget, etc. Clean, but classmethods on an ABC are slightly awkward and each engine's `build` needs different auxiliary state (sandbox lifecycle, realtime mailbox).

**Option B — a per-engine builder module + a registry (recommended).** Each `adapters/<engine>/` exposes a single `build_adapter(opts: LupAgentOptions) -> BuiltAdapter`, where `BuiltAdapter` bundles the three things `core.build_adapter` returns today:
```python
class BuiltAdapter(BaseModel):
    adapter: AgentAdapter
    lifecycle: AbstractContextManager[object]   # sandbox / cleanup; nullcontext default
    mailbox: RealtimeMailbox | None = None       # only for realtime subprocess backends
    model_config = {"arbitrary_types_allowed": True}
```
A registry maps the backend id to the builder:
```python
# lup/adapters/registry.py
BACKEND_BUILDERS: dict[Backend, Callable[[LupAgentOptions], BuiltAdapter]] = {
    "anthropic": build_claude_adapter,        # from adapters/claude/
    "openai":     build_codex_adapter,         # from adapters/codex/
    "openai-compatible": build_openai_adapter, # from adapters/codex/
}

def build_adapter(backend: Backend, opts: LupAgentOptions) -> BuiltAdapter:
    return BACKEND_BUILDERS[backend](opts)
```
`core.build_adapter` (`core.py:509`) collapses to: build the neutral `LupAgentOptions`, resolve `backend = backend_for_settings()`, call `lup.adapters.build_adapter(backend, opts)`. **The `match settings.agent_sdk` is gone**; the tuple return is gone (replaced by the typed `BuiltAdapter`, killing the tuple smell at `core.py:512,519`).

This collapses sites #3 and #4 (§1.1) into a registry lookup, and the three fragmented codex builders (`build_codex_session` / `build_codex_adapter` / `build_codex_realtime_adapter` / `build_openai_adapter`) into one `adapters/codex/build.py` that constructs from `LupAgentOptions` (realtime vs not is `opts.realtime`, openai vs codex is which builder the registry picked).

> **Registry vs `match`:** A dict registry is not just a `match` in disguise — it is open for extension (downstream projects register a backend without editing lib), it lives *inside* the adapter layer (the one place backend knowledge is allowed), and it has exactly one entry per engine package. The notes object to `match backend` *in consumer code that should be backend-blind*; a registry *in the adapter layer* is the sanctioned replacement.

### 2.5 `query()` (one-shot) on the same ABC

`common.query()` (`common.py:242`) keeps its **signature stable** (it is public API; PATTERNS.md documents it; `reflect.py` calls it) but its body stops matching:

```python
async def query(prompt, *, model=None, backend=None, ..., output_type=None) -> LupResponse:
    effective_model = model or DEFAULT_MODEL
    backend = backend or model_backend(effective_model)
    opts = LupAgentOptions(model=effective_model, system_prompt=system_prompt or "",
                           max_turns=max_turns, max_thinking_tokens=max_thinking_tokens,
                           permission_mode=permission_mode, ...)
    built = lup.adapters.build_adapter(backend, opts)        # registry, no match
    # capability-gate instead of the hand-maintained claude_only dict:
    reject_unsupported(opts, built.adapter.capabilities)     # mirrors check_settings_supported
    async with built.lifecycle:
        return await built.adapter.run(prompt, trace_logger=trace_logger, prefix=prefix)
```

The `claude_only` guard (`common.py:274–297`) becomes `reject_unsupported()`, driven by `AdapterCapabilities` — the same approved mechanism as `core.check_settings_supported`. This deletes sites #1 and removes the option-knowledge duplication. (The two raising messages about `max_budget_usd` on one-shot codex stay — but as a capability/validation check, not a backend `match`.)

`claude_client.query` / `ResponseCollector` are the *rich* Claude-native one-shot path (used by devtools `chat`/`repl` and nested-agent examples). They stop being a free-floating "implements-an-unstated-ABC" file: `ResponseCollector` and `collect_lup_response` are **unified** (one collector — see §3.8) and live in `adapters/claude/`, and the lup-typed `claude_query` is just `ClaudeAdapter(...).run(...)` (one-shot through the same adapter). The doc-note "query and collector should be interfaces already specified" is answered: they implement `Conversation.send` / the collector contract, in the Claude package, visibly under the ABC.

### 2.6 Background / persistent on the same ABC

- **Background** (`background.py`): `BaseBackgroundAgent` ABC stays. `create_background_agent` (`:153`, `match sdk`) becomes a registry keyed by backend, parallel to §2.4:
  ```python
  BACKGROUND_BUILDERS: dict[Backend, Callable[..., BaseBackgroundAgent]] = {
      "anthropic": build_claude_background, "openai": build_codex_background, ...}
  ```
  The "codex can't use tools / needs explicit model" validation moves into the codex background builder (it is a property of that engine), not the dispatcher. The Claude `message_generator` stops yielding `dict[str, object]` — define a small `LupUserTurn` model (or reuse an existing message type) so it yields a typed object (`claude_background.py:65`).
- **Persistent / realtime** (`run_persistent_agent`, `core.py:610`): unify under the same `build_adapter` path. `LupAgentOptions.realtime=True` makes the codex builder return a `BuiltAdapter` *with* a `mailbox`; the Claude builder returns one configured for in-process sleep/wake (Stop hook) — see open question §7 on whether Claude persistent stays in-process-only. The bare `int` return becomes a named type (`type TurnCount = int` at minimum, or a small result model). Whether `run_persistent_agent` stays a *separate* `core` entry point or merges into `run_agent` with a `persistent: bool` is an open question (§7); the mechanism (one `build_adapter`, capability-driven loop selection like the existing `adapter.capabilities.stop_event` branch at `core.py:584`) is the same either way.

### 2.7 Proposed file/folder reorg

```
packages/lup/src/lup/adapters/
├── __init__.py            # exports build_adapter, BuiltAdapter, the registry (public seam)
├── common.py              # AgentAdapter, Conversation, AdapterCapabilities, query(), reject_unsupported()
├── registry.py            # BACKEND_BUILDERS, build_adapter(backend, opts)  [or fold into __init__]
├── claude/
│   ├── __init__.py
│   ├── adapter.py         # ClaudeAdapter, ClaudeConversation, capabilities
│   ├── options.py         # build_claude_adapter(opts)  ← the "build_claude" the user wants
│   ├── client.py          # build_client(), ResponseCollector (the ONE collector), rich query()
│   ├── converters.py      # claude_block_to_lup, claude_message_to_lup, spec_to_claude, hook + server converters
│   └── background.py      # ClaudeBackgroundAgent, build_claude_background
├── codex/
│   ├── __init__.py
│   ├── adapter.py         # CodexAdapter, OpenAICompatibleAdapter, CodexConversation, capabilities
│   ├── options.py         # build_codex_adapter(opts), build_openai_adapter(opts), config-override builders, budget
│   ├── converters.py      # codex_items_to_lup, codex_usage_to_lup, per_mtok_usage_cost
│   ├── background.py      # CodexBackgroundAgent, build_codex_background
│   └── hooks.py           # codex_hooks.py (quarantined; stays, clearly marked)
```

This is the "claude subfolder" the user asked for (`claude.py:2`), applied symmetrically to codex. Each subpackage is "one engine fulfilling the spec." `openai_compat` is **not** its own engine folder — it is `OpenAICompatibleAdapter` in `codex/adapter.py` (it is a `CodexAdapter` subclass; same engine, one config override), which directly answers `core.py:548` "how is openai different from codex".

> Per the CLAUDE.md "no barrel files" rule, these subpackage `__init__.py` files stay docstring-only and consumers import from the defining module (`from lup.adapters.claude.adapter import ClaudeAdapter`). The **one** sanctioned export surface is `lup.adapters.__init__` exposing `build_adapter` — the public seam — consistent with the "standalone package root may declare a public API" exception.

---

## 3. What moves from template → lib

Applying the placement test (no `lup_template` import; usable as-is elsewhere) to each item the concern names:

| Item | Current location | Decision | Why |
|------|-----------------|----------|-----|
| `extract_sources` | `core.py:45` | **Stays in template** (or moves to `lup` only if generalized) | It hardcodes `"WebSearch"/"WebFetch"` and reads `block.input["url"]/["query"]` — that is a *domain* decision about what counts as a "source". Not backend logic. The note (`core.py:44` "unclear why this is there") is an **altitude/clarity** issue (owned by `template-altitude-docs`), not a placement one. **Recommend: keep in template, clarify its docstring.** |
| `build_result` | `core.py:61` | **Stays in template** | It builds `AgentSessionResult` from `AgentOutput` — both are `lup_template.agent.models` types. It *is* the domain's result assembly. The note (`core.py:60` "doesn't feel like it belongs in core; missing part in the library?") is right that its *ingredients* are library-provided (`read_output`, `read_metrics_summary`, `response.result`) — but the assembly is domain. **Recommend: keep; the library already provides every piece it composes.** |
| `subprocess_sandbox_cleanup` | `core.py:488` | **Move to `lup`** (`lup.sandbox` or the codex builder) | Pure library mechanism: "remove the session's docker container on exit, no-op without the docker extra." Zero domain content. It belongs next to `sandbox_cleanup` (which it wraps) or folded into `build_codex_adapter`'s `BuiltAdapter.lifecycle`. Notes `core.py:497,498` ("badly named", "should be at the beginning of the section, then called") resolve naturally once it is library code returned as `BuiltAdapter.lifecycle`. |
| `ToolPolicy` | `tool_policy.py:96` | **Split.** The *construct* (filter-by-tag, compute allowlist, MCP-server assembly) → **`lup`**; the *domain policy instance* (which keys map to which excluded tags) → stays template. | `tool_policy.py:97` — "Are you sure this should be in template? Seems like the construct itself should be universal and go in lib?" The mechanism (tags, `filter_tools`, `get_allowed_tools`, `group_enabled`) is 100% generic and identical across projects. Propose a `lup.tool_policy.ToolPolicy` base owning the mechanism; the template subclasses (or configures) it with domain exclusions. The `requires:example-api` mapping and TODO stay in the template subclass. |
| `CLAUDE_BUILTIN_TOOLS` | `tool_policy.py:49` | **Move to `lup`** (the Claude adapter package) | `tool_policy.py:48` — "feels fundamental enough that I don't understand why this is in template". It is the Claude SDK's built-in tool-name set — a *Claude backend fact*, not a domain fact. It belongs in `adapters/claude/` (the only place that consumes it) and is exposed for the allowlist computation. `FRAMEWORK_TOOLS = {"StructuredOutput"}` (`tool_policy.py:70`) likewise → Claude package (it is the SDK's structured-output tool). |
| `ServerConfig = Any` | `tool_policy.py:37` | **Delete; replace with a real union in `lup.mcp`** | `tool_policy.py:36` — "Why do you type alias any? Seems like something that should stay purely in the backend?" The union is `LupMcpServerConfig | <raw SDK McpServerConfig>`. Both already live in `lup.mcp` / the Claude adapter. Define `type McpServerEntry = LupMcpServerConfig | RawMcpServerConfig` there; `isinstance(server, LupMcpServerConfig)` narrows it (replacing the `hasattr(server, "server")` runtime narrowing at `core.py:201`). **This `Any` disappears into the backend — exactly as the note demands** — and its two `# claude: ignore` markers (`tool_policy.py:24,37`) clear. |
| `serve-tools` server build | `serve.py:50,72,113` | **Reuse the unified builder; stop rebuilding** | `serve.py:50` — "duplicate the creation of the server in core. serve should just reuse the same server from core". Both `core.build_options` and `serve.collect_tools_by_server` call `build_session_toolset` (`toolsets.py`) already — the *toolset* is shared. What is NOT shared is the **MCP-server-from-tools** construction and the `glob+ast` dynamic-name discovery (`serve.py:54–84`). Move the stdio-server-from-`LupMcpTool`s assembly into `lup.mcp` as a reusable `serve_tool_groups()` and have serve call it; the `glob+ast` walk is then unnecessary (the toolset already enumerates tools) — see §3.7. |

### 3.5 Killing `ServerConfig = Any` concretely

Today (`tool_policy.py`):
```python
type ServerConfig = Any  # claude: ignore — runtime-narrowed union
def get_mcp_servers(...) -> dict[str, ServerConfig]: ...
# core.py:201 narrows with: lup_server_to_claude(server) if hasattr(server, "server") else server
```
After — define the union where both members live (`lup.mcp`):
```python
type McpServerEntry = LupMcpServerConfig | RawMcpServerConfig
def get_mcp_servers(...) -> dict[str, McpServerEntry]: ...
# the Claude adapter narrows by type, not hasattr:
def to_claude(entry: McpServerEntry) -> McpSdkServerConfig | RawMcpServerConfig:
    match entry:
        case LupMcpServerConfig(): return lup_server_to_claude(entry)
        case _:                    return entry
```
`Any` gone, `cast` gone, pyright narrows cleanly, and the conversion lives in the Claude adapter (backend code) instead of being smeared across template `core.py`.

### 3.7 De-duplicating `serve-tools`

`serve.py` rebuilds what `core` builds, three ways:
1. `collect_tools_by_server` (`serve.py:14`) re-derives groups — but it already delegates to `build_session_toolset`, so this part is fine; just have it return `toolset["groups"]` (it does, `serve.py:51`).
2. `collect_dynamic_tool_names` (`serve.py:54`) uses **`glob` + `ast.walk`** to discover `@lup_tool`-decorated names (`serve.py:72` — "is that necessary? a bit wtf"). This is needed only for `inspect`/listing without a session context. Replace by enumerating the toolset (or a static `collect_tools_by_server(None)` that returns the real `LupMcpTool` objects) — the names come from `tool.name`, no AST parsing.
3. `serve_tools` (`serve.py:95`) hand-rolls an `mcp.server.Server` from the tools and `match server_group` (string cases, `serve.py:113`). **Move the "build an MCP stdio server from `list[LupMcpTool]`" into `lup.mcp`** (e.g. `serve_tool_groups(groups, selector)`), so serve calls the *same* construction `core`/`create_mcp_server` use. The `server_group` selector becomes a typed value (`Literal` or an enum) — resolving the `antipattern-direction` "type str should be Literal" note — and the group→tools selection logic lives once.

Net: serve becomes a thin CLI entry that loads the session context, asks `lup.mcp` to serve the selected groups, and exits. No glob, no ast, no rebuilt server, no `match` on a bare string.

### 3.8 Unifying the two Claude collectors

`collect_lup_response` (`claude.py:311`) and `ResponseCollector` (`claude_client.py:118`) drain `client.receive_response()` with near-identical `match message` loops, differing mainly in output type (`LupResponse` vs accumulated SDK blocks + `.text`/`.output`). Unify into **one** collector in `adapters/claude/client.py` that accumulates once and exposes both the lup-typed `LupResponse` and the convenience accessors. `ClaudeConversation.send`, `claude_query`, and the rich `query` all collect through it. This removes the "two ways to do the same thing" the three-file split created, and gives the `claude_client.py:1` note ("implementing an ABC with no ABC in sight") its answer: the collector is a single, named, documented type in the Claude package, feeding the `Conversation` contract.

---

## 4. Eliminating the leaks — before → after

**Site #1 — `common.query()` `match backend` (`common.py:299`):**
- *Before:* `match backend: case "anthropic": claude_query(...) ; case "openai": CodexAdapter(...).run() ; case _: OpenAICompatibleAdapter(...).run()` + a hand-maintained `claude_only` guard.
- *After:* `built = adapters.build_adapter(backend, opts); reject_unsupported(opts, built.adapter.capabilities); return await built.adapter.run(...)`. Dispatch via registry; option-support via capabilities.

**Site #2 — `create_background_agent` `match sdk` (`background.py:153`):**
- *Before:* `match sdk: case "claude": ClaudeBackgroundAgent(...) ; case "codex": <validate> CodexBackgroundAgent(...) ; case _: raise`.
- *After:* `return BACKGROUND_BUILDERS[backend](name=..., ...)`. The codex builder owns the "no tools / explicit model" validation (engine property, not dispatcher concern).

**Site #3 — `build_codex_realtime_adapter` `match settings.agent_sdk` (`core.py:413`):**
- *Before:* template `match` choosing `OpenAICompatibleAdapter` vs `CodexAdapter`, each with a ~12-arg constructor duplicated.
- *After:* deleted entirely. `core` sets `opts.realtime=True` and calls `adapters.build_adapter(backend, opts)`; the codex builder constructs the right subclass and the mailbox, returning `BuiltAdapter(adapter=..., lifecycle=cleanup, mailbox=...)`.

**Site #4 — `build_adapter` `match settings.agent_sdk` (`core.py:524`):**
- *Before:* template `match` over claude/codex/openai, each branch importing the adapter and assembling native options + lifecycle, returning a 3-tuple.
- *After:* `opts = build_agent_options(notes, settings); built = adapters.build_adapter(backend_for(settings), opts); return built`. No `match`, no tuple, no native-option imports in `core`.

**Site #5 — `reflect.run_reviewer` `match model_backend(model)` (`reflect.py:186`):**
- *Before:* template tool branches on `model_backend(model)` to decide whether to pass Claude-only options (`tools`, `max_turns`, `max_thinking_tokens`, `permission_mode`) to `query()`.
- *After:* the tool **never inspects the backend**. It always calls `query(prompt, model=model, system_prompt=..., tools=[...], max_turns=5, ...)`. `query()` now **gracefully drops or rejects** unsupported options via `reject_unsupported`/capabilities instead of raising — meaning the *template* expresses intent ("I'd like file tools and calibration") and the *adapter layer* decides what the backend can honor. The `outputs_dir` "N/A on this backend" wording becomes a capability-driven message inside the library, not a `match` in a domain tool. This is the literal demand of note `reflect.py:187`: "Backend concerns should only appear in the designated lib sections, all the rest should be unified."
  - One design decision this forces (open Q §7): should over-asking options on a weak backend **raise** (current behavior) or **silently degrade**? For `reflect` the user clearly wants degrade ("unified"); the cleanest rule is *one-shot `query()` degrades with a logged note; explicitly-set session settings raise* — matching the existing `check_settings_supported` split between defaulted and `model_fields_set`.

**Site #6 — `serve.serve_tools` `match server_group` (`serve.py:105`):** see §3.7 — replaced by a typed selector over a shared `lup.mcp` server builder; not backend dispatch but resolved alongside.

**The `cast` and `tuple[]` smells:**
- `cast("EffortLevel|None", settings.reasoning_effort)` (`core.py:238`) — deleted; the Claude adapter maps generic effort → `EffortLevel` internally (§2.3).
- `cast("JsonObject|None", self.output_schema)` (`codex.py:453`) — stays inside the codex adapter (legitimate SDK boundary; it is already in backend code and carries no template coupling). If the user wants it gone too, narrow `output_schema`'s type at the adapter boundary; lower priority.
- Every `tuple[...]` return in `core.py` (`build_codex_session`, `codex_budget_options`, `build_codex_realtime_adapter`, `build_adapter`) — deleted by moving construction into adapters that return typed models (`BuiltAdapter`, internal config objects). This is what makes the `tuple[`/`cast(` additions to the edit hook (owned by `edit-hook-antipatterns`) **pass** on `core.py` afterward.

---

## 5. The `# claude: ignore` / anti-pattern angle

The user framed this as **two complementary workstreams**, not a fork: (a) build the *harness* (audit + single-source anti-pattern set), and (b) *fix everything* (resolve the underlying types so the ignores come out). This refactor is the largest single contributor to (b).

### 5.1 Current `# claude: ignore` inventory (repo-wide grep)

Backend-coupled — **resolved by this refactor:**

| Marker | Resolves how |
|--------|-------------|
| `tool_policy.py:24` `from typing import ... Any  # claude: ignore — for the ServerConfig alias` | Deleted with the `ServerConfig` alias (§3.5) |
| `tool_policy.py:37` `type ServerConfig = Any  # claude: ignore` | Replaced by `McpServerEntry` union (§3.5) |
| `claude.py:18` `from typing import Any, cast  # claude: ignore` | `Any`/`cast` removed once converters use the typed union + internal effort mapping; if any `cast` remains it is a narrow SDK-boundary one, re-justified in the Claude package |
| `claude.py:289` `-> list[SdkMcpTool[dict[str, Any]]]  # claude: ignore` | SDK generic boundary; **may persist** — `SdkMcpTool` is generic over the tool's arg dict. Candidate to type as `SdkMcpTool[Mapping[str, object]]` if the SDK allows; otherwise a *legitimate* surviving ignore (SDK boundary), kept but isolated in the Claude package |
| `claude_client.py:106` `JsonSchema = dict[str, object]  # claude: ignore — JSON Schema is an open document` | Legitimate (JSON Schema genuinely is open). Survives, but moves into the Claude package; arguably should reuse a single `lup`-level `JsonSchema` alias (dedupe with `codex.py`'s `dict[str,object]` schema params) |
| `codex.py:1` file-level `# claude: ignore` | Re-scope: after the codex split, most of `codex.py` is typed; the file-level blanket should shrink to inline ignores only at the genuine `openai_codex` untyped-SDK boundaries (the import-time `from openai_codex...` and the generated-model `match`). Goal: **remove the file-level blanket**, keep a handful of justified inline ones. |
| `openai_compat.py:1` file-level `# claude: ignore` | Same: shrink the blanket; the provider-config logic is plain strings and typed. |
| `codex_background.py:80` `except Exception  # claude: ignore — task supervisor` | Legitimate supervisor boundary (CLAUDE.md sanctions it). Survives. |

Standalone (not backend-coupled; **owned by other concerns or kept as legitimate**):
- `types.py:241` `tool_input: dict[str, object]  # claude: ignore` — SDK-agnostic hook input boundary; legitimate, the user approved `types.py`.
- `markers.py:1` file-level — the markers module is itself meta-tooling; note `markers.py:2` asks for *typed* ignores (`# claude: ignore[regex]`) and a `# claude` → `# lup` rename — that is the `antipattern-direction` policy question, not this refactor.
- `mcp.py:76,288,315`, `metrics.py:165`, `sandbox.py:169,331`, `realtime_relay.py:325`, `history.py:72`, `environment/cli/__main__.py:217`, `py.py:54`, `branches.py:445,447`, `feedback/state.py:439`, `init.py:69,169`, `inspect_agent.py:94,97,138`, `utils.py:75`, `serve.py:157` —各 genuine boundaries (atomic rename / `/proc` parse / MCP arg dict / NUL framing / heterogeneous JSON). These belong to the **cleanup workstream (b)** and the **harness audit**, *not* to this refactor — except `serve.py:157` (MCP arg dict) which is touched incidentally when serve is rewritten (§3.7) and can be typed via the shared server builder.
- `trace/traces.py:74` `# claude: ignore` — the user says this one was applied where it **shouldn't** have been (`traces.py:75` + `antipattern-direction`); owned by `traces-regex-refactor`/`antipattern-direction`, not here.

**Takeaway for the user:** this refactor cleanly retires ~6–8 backend-coupled ignores (the `ServerConfig`/`Any`/`cast`/`effort` cluster) and *shrinks* the two codex file-level blankets to a few justified inline ones. The rest are pre-existing legitimate boundaries handled by the separate cleanup pass.

### 5.2 The harness — single source of truth + `dev check` audit

**The problem the user named:** the anti-pattern list lives in `.claude/plugins/lup/hooks/scripts/auto_allow_edits.py` (`ANTI_PATTERNS`, `auto_allow_edits.py:81`), which is a **hook script, not an importable package** — so nothing else (a `dev check` auditor, a test, the docs) can consume the same list. The hook even *inlines* a copy of `markers.py`'s regexes (`auto_allow_edits.py:58–64`) precisely because it cannot import on the per-edit hot path. There are already two sources of truth (hook copy vs `lup.markers`) and the user wants one.

**Proposal — formalize the anti-pattern set in `lup`, consume it from both the hook and a new auditor:**
1. Move the anti-pattern table to an importable module: `lup.antipatterns` (a standalone-importable list of `(pattern, message)` plus the TS table). It imports nothing heavy, so the hook can `sys.path`-bolt-import it, *or* keep the hot-path inline copy but add a test asserting the inline copy equals `lup.antipatterns` (single logical source, enforced by CI/pytest). Recommendation: make `lup.antipatterns` authoritative; the hook imports it (hook latency is dominated by the model call, not a small import) — eliminating the drift the user fears.
2. Add `lup-devtools dev check --antipatterns` (or a standalone `dev audit-ignores`) that walks all tracked `.py`/TS files and reports two failure classes the user specified:
   - **Missing marker:** a line matches an anti-pattern but carries no inline `# claude: ignore` and the file has no file-level ignore → it *should* have been denied by the hook but slipped in (e.g. via a tool that bypassed the hook, or a pre-existing line). This is the `claude_background.py:65` `dict[str, object]` case the hook "missed" — the audit catches it after the fact.
   - **Spurious marker:** an inline `# claude: ignore` on a line that matches **no** anti-pattern (the ignore is dead / was applied where it shouldn't be, e.g. `traces.py:74`). Report it for removal.
   This mirrors `dev check`'s existing structure (`check.py` already aggregates ruff/pyright/pytest/`scan_feedback` into pass/fail rows — add an "antipatterns" row). The user explicitly asked for this at `utils.py:76`: "in the devtool check, we probably want something that rechecks the whole codebase and verifies if there should be claude: ignore when there isn't any."
3. Formalize the set: the additions `edit-hook-antipatterns` makes (`Mapping[str, object]`, bare `import dataclasses`, `tuple[`, `cast(`, sharpened structured-data messages) land in this single `lup.antipatterns` source, so the hook *and* the auditor *and* the docs all see them at once.

**Interlock with this refactor:** land `lup.antipatterns` + the `tuple[`/`cast(` patterns (workstream a) **first** as their own shippable step; then this refactor (which removes the offending `cast`/`tuple`/`Any` sites) can be verified by running `dev check --antipatterns` and watching the backend-coupled ignores go to zero. The auditor becomes the regression test that the leak stays fixed: after the refactor, *any* new `match`-on-backend or `ServerConfig = Any` regression shows up. (A stretch goal the user floated at `auto_allow_edits.py:80` — "can we do this with a linter / custom ruff rule?" — is a real option for the regex-able subset; recommend it as a *follow-up* to the importable list, not a prerequisite, since `match`-on-backend detection is more naturally an AST check in the auditor than a ruff rule.)

> Note: whether to *rename* `# claude:` → `# lup:` and add *typed* ignores (`# claude: ignore[regex]`) — `markers.py:2,3` — and whether to **strip all ignores vs formalize the library** — `CLAUDE.md:1–2` — are genuine **policy** decisions owned by `antipattern-direction` (needs_user). This refactor proceeds either way: it removes the *backend-coupled* ignores regardless of the naming/policy outcome.

---

## 6. Migration plan (ordered, each step independently shippable + testable)

Each step ends green on `uv run ruff check . && uv run pyright && uv run pytest`. Steps are ordered so the public seams (`common.query` signature, `AgentAdapter` ABC) stay stable throughout and the big risky move (folder reorg) happens behind already-introduced indirection.

**Step 0 — Anti-pattern source of truth (independent; unblocks verification).**
Create `lup.antipatterns`; point the edit hook at it (or add the equality test); add `tuple[`/`cast(`/`Mapping[str, object]`/`import dataclasses` patterns there (the `edit-hook-antipatterns` additions). Add `dev check --antipatterns` auditor (missing/spurious ignore detection). *Ship.* (This is workstream-a; it makes every later step's ignore-reduction measurable.) *Risk: low.*

**Step 1 — Introduce `LupAgentOptions` + `BuiltAdapter` + registry, no behavior change.**
Add the new types in `lup/types.py`/`lup/options.py` and `lup/adapters/registry.py` with `build_adapter(backend, opts)`. Implement the three builders **by delegating to the existing `core.py` construction temporarily** (or by reading from a shim) so nothing moves yet. Add `reject_unsupported()` next to `check_settings_supported`'s logic in `common`. *Risk: low — purely additive.*

**Step 2 — Define `McpServerEntry` union; delete `ServerConfig = Any`.**
Add the union in `lup.mcp`; change `ToolPolicy.get_mcp_servers` return type and the Claude conversion at `core.py:201` to narrow by `isinstance`/`match` instead of `hasattr`. Remove the two `tool_policy.py` `# claude: ignore`s. *Risk: low — pyright proves it; `riskiest sub-point` is the runtime narrowing equivalence, covered by existing adapter tests.*

**Step 3 — Route `common.query()` through the registry (keep signature).**
Replace the `match backend` body with `build_adapter` + `reject_unsupported`. **Signature unchanged** → `reflect.py` and PATTERNS.md examples keep working. This de-risks by swapping internals only. Verify with the existing nested-agent/query tests. *Risk: medium — this is the "keep `common.query()`'s signature stable while swapping its internals" the prompt calls out. De-risk: do it before any folder move, with the old adapters still in place.*

**Step 4 — `reflect.py`: delete `match model_backend`.**
Make `run_reviewer` always call `query()` with the full option set; rely on Step 3's `reject_unsupported`/degrade. Decide the degrade-vs-raise rule (open Q) — implement "one-shot degrades, logs". Remove the backend `match` from the template tool. *Risk: low once Step 3 lands; covered by a reviewer-on-codex test.*

**Step 5 — `background.py`: registry instead of `match sdk`; typed yield.**
Introduce `BACKGROUND_BUILDERS`; move codex validation into its builder; replace `message_generator`'s `dict[str, object]` with a typed turn model. *Risk: low.*

**Step 6 — Fold Claude into `adapters/claude/` and unify the collector.**
Create the subpackage; move converters/client/adapter/background; **unify `collect_lup_response` + `ResponseCollector` into one collector** (§3.8); move `CLAUDE_BUILTIN_TOOLS`/`FRAMEWORK_TOOLS` here. Have `build_claude_adapter(opts)` own `ClaudeAgentOptions` construction (effort mapping, `persist_session`→`extra_args`, thinking-token model-version logic) — **deleting `core.build_options` and its `cast`**. Update the registry builder to call it. *Risk: medium-high — most code motion. De-risk: pure moves first (one commit), then the `build_claude_adapter` extraction (second commit), keeping `core.build_options` callable until the registry points at the new builder; rename-symbol for identifier moves; rely on pyright + the full adapter test suite. This is the step to land alone.*

**Step 7 — Fold Codex/OpenAI into `adapters/codex/`; unify the builders.**
Move codex/openai/codex_hooks; collapse `build_codex_session`/`build_codex_adapter`/`build_codex_realtime_adapter`/`build_openai_adapter` into `adapters/codex/options.py` constructing from `LupAgentOptions` (realtime = `opts.realtime`); move `subprocess_sandbox_cleanup` into the codex lifecycle / `lup.sandbox`. Registry builders now call these. **Delete the corresponding `core.py` functions and their `tuple[]` returns.** *Risk: medium-high. De-risk: same pattern — moves first, then builder unification; keep openai as a `CodexAdapter` subclass (no behavior change), verify the codex/openai integration markers.*

**Step 8 — Collapse `core.build_adapter` + `run_persistent_agent`.**
`core.build_adapter` becomes "build `LupAgentOptions` → `adapters.build_adapter(backend, opts)`"; the `match settings.agent_sdk` is deleted. Decide persistent-entrypoint shape (open Q): either keep `run_persistent_agent` (typed return) routing through the same `build_adapter` with `opts.realtime=True`, or merge into `run_agent`. *Risk: medium — the last `match` removal; covered by run_agent tests across backends.*

**Step 9 — `serve-tools` reuse + typed selector.**
Move the stdio-server-from-tools builder into `lup.mcp`; serve calls it; replace `glob+ast` discovery and `match server_group: case "...": ` (string) with a typed selector over the shared builder. *Risk: low-medium; serve has thin test coverage — add a test that served group names match the toolset.*

**Step 10 — Split the `ToolPolicy` construct into `lup`.**
Introduce `lup.tool_policy.ToolPolicy` base (mechanism); template subclasses with domain exclusions. *Risk: medium — touches both Claude and codex paths; do last so the adapter layer is already stable. Could be deferred to a follow-up PR if scope is too large.*

**Step 11 — Docs + audit close-out.**
Document the principle (§2.1) in CLAUDE.md and PATTERNS.md; update the directory-structure block; run `dev check --antipatterns` and confirm the backend-coupled ignores are gone; shrink the codex file-level blankets to justified inline ignores.

**Riskiest steps:** 6 and 7 (bulk code motion) and 3/8 (the public/`core` dispatch swaps). De-risking throughout: (a) keep `common.query()` and `AgentAdapter` signatures frozen; (b) every code move is a separate commit from every behavior change; (c) the Step-0 auditor + the existing adapter/parity test suite (`canonical_capability_matrix`, `capability_matrix_markdown` regression) prove no capability regressed; (d) land 6, 7, 10 as standalone PRs.

---

## 7. Open questions for the user

1. **Folder names / shape.** Confirm `adapters/claude/` + `adapters/codex/` subpackages (with `openai_compat` as a `CodexAdapter` subclass inside `codex/`, *not* its own folder). Acceptable? Or do you want a flat `adapters/` with longer filenames?
2. **Construction contract: registry builder (Option B) vs abstract `classmethod build` (Option A)?** Recommendation is B (`build_adapter(opts) -> BuiltAdapter` per engine + a registry dict), because lifecycle/mailbox state varies per engine and a registry is open for downstream extension. Confirm.
3. **`query()` over-asking: degrade vs raise.** When a tool (e.g. `reflect`) passes Claude-only options to a one-shot `query()` on a weak backend, should the adapter **silently degrade + log** (what "unified" implies for `reflect.py:187`) or **raise** (today's behavior)? Recommendation: *one-shot `query()` degrades-and-logs; explicitly-set session settings still raise* (mirrors `check_settings_supported`'s `model_fields_set` split). Confirm the rule.
4. **Persistent/realtime entrypoint.** Keep `run_persistent_agent` as a separate `core` function (with a typed return instead of bare `int`), or merge into `run_agent(..., persistent=True)`? And: should Claude persistent stay **in-process-only** (Stop-hook sleep/wake) while codex/openai use the relay, with that difference expressed purely via `AdapterCapabilities.realtime` (`"in_process"` vs `"relay"`) — i.e. the template never branches, the builder picks the loop? (Recommendation: yes, capability-driven; confirm.)
5. **How far to push `ToolPolicy` into lib (Step 10).** Move the *whole mechanism* to `lup.tool_policy.ToolPolicy` (template subclasses for domain exclusions), or keep `ToolPolicy` in the template but extract only the allowlist/tag *functions* to `lup`? Trade-off: full move maximizes reuse but adds a base/override seam every project inherits.
6. **`openai_compat` routing note (`openai_compat.py:6`).** A standing `# claude:` note argues GLM/open-source models should route through *Claude* scaffolding (Anthropic-compatible gateway), not the Codex runtime ("see the aio3 folder"). That changes which engine `model_backend("glm-...")` maps to. In scope for this refactor (it touches the registry mapping), or a separate decision? Recommendation: separate — this refactor preserves current routing; revisit after.
7. **Anti-pattern harness ownership.** Confirm `lup.antipatterns` as the single source (hook imports it / test-enforced equality) and `dev check --antipatterns` as the auditor — vs the `antipattern-direction` concern's alternative of a custom ruff/lint rule. Recommendation: importable list + AST auditor now; ruff rule as optional follow-up for the regex-able subset. (The `# claude:`→`# lup:` rename and typed `ignore[...]` are left to `antipattern-direction`.)
