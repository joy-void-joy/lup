# Lup capability-composition overhaul

## Status and intent

This document is the implementation plan for the Lup harness, resolver, and
runtime overhaul. It records the settled architecture, migration, sequencing,
and acceptance decisions needed for implementation without requiring later
design choices.

The implementation has landed on the `refactor-sdk-2` branch. The
[Implementation completion review](#implementation-completion-review-2026-07-16)
at the end of this document is authoritative: Gates A through F pass within the
plan's evidence-backed capability model. Unsupported native behavior is absent
or rejected before input and is recorded explicitly; it is never emulated by a
silent compatibility fallback. The older review below it is retained as
historical defect provenance, not as a current punch list.

The design follows Tacocast's capability model:

- an abstract base class represents one cohesive capability with one to three
  independently useful operations;
- an implementation owns only that capability;
- concrete decorators and orchestrators obtain richer behavior by composing
  those implementations;
- native syntax and wire formats belong to native implementations, never to
  shared string-rewriting logic.

The work remains one linear program, but it has independently accepted
milestones for the neutral foundation, harness, resolver, runtime migration,
and linter modernization. The runtime public-API removal is still a clean
breaking release; unrelated milestones do not have to wait for that release.

## Goals

- Make every independently useful capability independently constructible,
  testable, and composable.
- Make every ABC express one coherent capability through one to three abstract
  methods, with no inherited behavior or optional methods that raise at
  runtime.
- Keep shared declarations and orchestration independent of native command
  names, prefixes, tool names, payloads, SDKs, and capability spellings.
- Preserve strong typing from validated configuration through factory
  construction, sessions, turns, results, errors, hooks, and `query()`.
- Preserve the complete existing harness behavior, add an equivalent second
  native implementation where the target supports it, and report genuine
  capability gaps rather than hiding them.
- Keep one typed Pydantic source for portable skills, agents, policies,
  resolver contracts, and acceptance fixtures while generating native
  artifacts through injected renderers.
- Keep generated plugins self-contained at hook runtime: installed artifacts
  must not import `lup-devtools`, an active checkout, or its virtual
  environment.
- Make generation deterministic, reviewable, safe around local configuration,
  and enforced against drift.
- Allow resolver work to follow its dependency DAG while isolating every
  implementation in an orchestrator-leased branch and worktree.

## Non-goals

- Do not redesign the prose or behavior of all existing skills during parity
  migration.
- Do not make native runtimes look identical by dropping unsupported behavior.
- Do not retain or recreate `Engine`, `Backend`, `Runtime`, `Client`,
  `ComposedClient`, an all-capabilities factory, or another service locator.
- Do not use a one-method class as a disguise for an incoherent service
  locator. Method count is necessary but not sufficient for cohesion.
- Do not place native names in a shared registry and call the registry neutral.
- Do not use generic `**kwargs`, reflective option-consumption tracking,
  anonymous positional tuple shapes, or silent unsupported-option dropping.
- Do not use structural `Protocol` types as Lup's architectural seams. Use
  Lup-owned ABCs for reusable capabilities and typed callables for small
  callbacks. Existing low-level interoperability protocols may remain when
  they do not define application architecture.
- Do not infer resolver implementation selection from environment variables.
- Do not merge resolver output directly into the user's working branch.
- Do not commit personal trust state, caches, credentials, active-run state,
  reconciliation proposals, or user-only settings.

## Architecture invariants

### ABCs represent one cohesive capability

Every Lup-owned capability ABC must satisfy all of the following unless a
deliberate exception is marked through the ordinary audited Lup-rule
suppression mechanism described below:

1. It has between one and three abstract behavior methods. Two or three methods
   are valid only when they are cohesive operations of the same independently
   useful capability.
2. It has no concrete methods, concrete properties, default implementations,
   convenience helpers, or methods that only raise an unsupported error.
3. It has no abstract properties. Metadata needed by an operation is immutable
   data owned by the concrete implementation.
4. It inherits only from `ABC` and typing-only generic bases. A capability ABC
   never inherits from another capability ABC.
5. Its operations are independently useful as one constructible capability.
   An unrelated operation cannot be added merely because the same native SDK
   supplies it.
6. A concrete implementation subclasses only the capability contract it
   implements. Cross-capability behavior uses composition, not implementation
   inheritance or multiple capability inheritance.

ABCs contain contracts only. There is no separate method-count allowlist: an
unsuppressed zero- or four-or-more-method ABC is invalid. A justified exception
uses the same typed, audited suppression as every other Lup rule rather than a
second architecture-specific exception system. A timeout, budget, retry,
serialization, tracing, display, persistence, policy chain, or other reusable
behavior is a concrete implementation that composes another capability
instance and implements the same capability ABC.

Small functions that are not independently useful architectural capabilities
remain typed callables inside a concrete composition. Examples include text
splitting, joining result fragments, logging callbacks, path formatting, and
state-reduction functions. A function graduates to an ABC only when
it becomes a reusable domain capability with its own implementations or
configuration.

### Automated enforcement

Add the typed architectural rule `abc-capability` to the current Lup checker
and retain its stable kebab-case identifier when the checker moves to AST
analysis. In the absence of a matching suppression, the rule must reject:

- zero or four-or-more abstract behavior methods;
- any concrete callable member on an ABC;
- abstract properties;
- one capability ABC inheriting from another;
- concrete capability implementations inheriting reusable behavior or more
  than one capability ABC.

Build a project-wide symbol index from the Python AST and resolved imports so
the rule recognizes Lup-owned ABCs and their concrete implementations across
modules. Docstrings, annotations, and immutable class declarations are not
callable members. Overloads on concrete construction helpers are not ABC
members.

The rule participates in the ordinary Lup suppression and audit machinery. A
deliberate exception uses an inline or file-level
`# lup: ignore[abc-capability]`, preferably with a concise reason. A bare
`# lup: ignore` continues to suppress the rule wherever the current checker
accepts a general ignore, but the suppression audit reports it as untyped and
the linter-modernization milestone migrates it to the narrow form. Missing,
untyped, and spurious suppressions are reported exactly as for other Lup rules;
there is no separate exception registry. Suppression waives the mechanical
shape check, not the cohesion review.

Complement the mechanical rule with a review checklist that rejects
small-method service locators whose input or output bundles unrelated
capabilities.

### Composition is explicit data flow

Data models may group independently supplied capabilities without acquiring
behavior. In particular:

```python
class SessionHandle(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    session: Session
    fork: ForkSession | None = None


class TurnHandle[T: BaseModel | None](BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    turn: Turn[T]
    events: EventStream | None = None
    interrupt: Interrupt | None = None
    steer: Steer | None = None
```

These are transparent typed values, not backend objects. Unsupported
capabilities are absent (`None`) instead of exposed as stubs. The contained
capability implementations are independently constructible and may be
decorated independently.

Add a field only for a genuinely portable capability consumed by neutral
callers. Native-only capabilities remain adapter-owned extensions rather than
turning these models into an open service locator. Capability diagnostics
inspect these values and adapter-owned evidence. They
never probe support by calling a method and catching an unsupported error.

### Shared code is native-neutral

Shared models and orchestration may describe semantic intent but must not
branch on or reconstruct:

- native invocation prefixes or command qualification;
- native tool names;
- native hook event names or payload dictionaries;
- SDK types, process flags, config-home environment variables, or profile
  spelling;
- plugin manifest paths or marketplace wire formats;
- native capability identifiers.

Familiar names such as `Edit`, `Write`, `Bash`, `Fetch`, and `Search` are
allowed as Lup's semantic lingua franca when they accurately name the domain
operation. Neutrality is a behavior and ownership boundary, not a ban on words
that originated in one runtime.

Native names are allowed only in concrete adapter packages, named composition
roots and CLI entry points, captured native fixtures, generated artifacts, and
the versioned capability evidence matrix.

Enforce this boundary with import tests and a narrow source audit. Neutral
packages may not import adapter packages, select an implementation by native
identifier, contain native invocation literals, or assemble native syntax from
prefix fragments. Evidence fixtures, adapter modules, concrete composition
roots, generated artifacts, and familiar semantic vocabulary are explicitly
outside the spelling audit.

## Public contracts and semantic models

### Harness and artifact contracts

```python
class ArtifactRenderer[S](ABC):
    @abstractmethod
    def render(self, source: S) -> ArtifactTree: ...


class ArtifactValidator(ABC):
    @abstractmethod
    def validate(self, tree: ArtifactTree) -> ValidationResult: ...


class SkillInvocationRenderer(ABC):
    @abstractmethod
    def render(self, invocation: SkillInvocation) -> str: ...


class CurrentTreeReader(ABC):
    @abstractmethod
    def read(self, root: Path) -> CurrentTree: ...


class Reconciler(ABC):
    @abstractmethod
    def propose(
        self, current: CurrentTree, desired: ArtifactTree
    ) -> ReconciliationProposal: ...


class Materializer(ABC):
    @abstractmethod
    def apply(self, proposal: ReconciliationProposal) -> MaterializationResult: ...


class CapabilityProbe[C](ABC):
    @abstractmethod
    def probe(self) -> CapabilityEvidence[C]: ...


class ProcessLauncher(ABC):
    @abstractmethod
    def launch(self, request: LaunchRequest) -> ExitStatus: ...
```

`ArtifactRenderer` is a rendering capability, not a compiler service locator.
Separate renderer instances own skill Markdown, agent configuration, settings,
manifests, hooks, guidance, and any other artifact family. A concrete tree
builder composes those renderers and `ArtifactValidator` implementations.
Likewise, each `CapabilityProbe[C]` probes one named capability contract; a
concrete diagnostic reporter composes their evidence instead of using one
provider-wide probe.

Portable prompts are Pydantic `PromptDocument` models containing ordered typed
parts:

```python
type PromptPart = TextPart | SkillInvocation | AskUser | Delegate | RequestApproval


class PromptDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    parts: list[PromptPart]
```

Ordinary prose stays in `TextPart`. `SkillInvocation` contains a semantic
plugin/skill reference and typed arguments, never pre-rendered invocation text.
A concrete `SkillInvocationRenderer` owns the entire native spelling,
including prefix, qualification, argument layout, escaping, and command
aliases. There are no prefix placeholders or shared command-name properties.
Converting `/lup:...` to `$lup:...` through regular expressions, string
replacement, or a post-render pass is forbidden.

### Native hook boundaries

```python
class NativeEventDecoder[N](ABC):
    @abstractmethod
    def decode(self, event: N) -> SemanticEvent: ...


class NativeDecisionRenderer[N](ABC):
    @abstractmethod
    def render(self, decision: Decision) -> N: ...
```

Input decoding and output rendering are separate capabilities. Each concrete
decoder privately owns native event names, tool names, matching behavior,
payload parsing, and malformed-input handling. There is no shared native-name
catalog.

The shared vocabulary uses familiar Lup-owned models with independent typed
meaning:

- `Edit` is represented by an `EditBatch` containing named `EditChange`
  values and may cover one or many files;
- `ShellCommand` represents a command execution request;
- `FetchUrl` represents retrieval of a known URL;
- `SearchWeb` represents a query and is not treated as `FetchUrl`;
- `UnknownTool` retains original identity for audit output and receives
  conservative policy handling.

The initial shared lifecycle vocabulary is `SessionStarted`, `InputSubmitted`,
`BeforeTool`, `ApprovalRequested`, `AfterTool`, `SubagentStarted`,
`SubagentStopped`, `CompletionRequested`, `BeforeCompaction`, and
`AfterCompaction`. Each is a dedicated typed model rather than one record with
many optional fields. Native-only lifecycle events remain adapter-owned typed
extensions and appear in capability evidence; they are not forced into the
shared vocabulary. A newly overlapping event becomes shared only after both
decoders have captured fixtures proving equivalent semantics.

`ToolIdentity` may retain opaque source evidence and the original native name
for diagnostics, but semantic dispatch uses the event model or `ToolKind`;
policies cannot branch on source identity or original name.

### Runtime execution contracts

```python
class SessionFactory(ABC):
    @abstractmethod
    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]: ...


class Session(ABC):
    @abstractmethod
    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]: ...


class Turn[T: BaseModel | None](ABC):
    @abstractmethod
    async def result(self) -> TurnResult[T]: ...


class EventStream(ABC):
    @abstractmethod
    def events(self) -> AsyncIterator[TurnEvent]: ...


class Interrupt(ABC):
    @abstractmethod
    async def interrupt(self) -> None: ...


class Steer(ABC):
    @abstractmethod
    async def steer(self, input: TurnInput) -> None: ...


class ForkSession(ABC):
    @abstractmethod
    def fork(
        self, at: TurnId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]: ...


class SubmittedOutputStore(ABC):
    @abstractmethod
    def write(self, value: BaseModel) -> None: ...

    @abstractmethod
    def read[T: BaseModel](self, output_type: type[T]) -> T | None: ...


type SubmissionGate[T: BaseModel] = Callable[
    [T], Awaitable[SubmissionDecision]
]


class TurnToolBinding[T: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    output_type: type[T]
    store: SubmittedOutputStore
    gate: SubmissionGate[T] | None = None


class TurnToolBinder(ABC):
    @abstractmethod
    async def bind[T: BaseModel](
        self, binding: TurnToolBinding[T] | None
    ) -> None: ...


class TurnRequest[T: BaseModel | None](BaseModel):
    model_config = ConfigDict(frozen=True)

    input: TurnInput
    output_type: type[T] | None = None


class TurnResult[T: BaseModel | None](BaseModel):
    model_config = ConfigDict(frozen=True)

    output: T
    messages: list[TurnMessage]
    blocks: list[TurnBlock]
    usage: Usage
    duration: timedelta
    identifiers: TurnIdentifiers
```

`write` is the deliberate type-erasure boundary: its value has already been
validated by the generic `TurnToolBinding[T]`, and a method-local `T` appearing
only once conveys no relationship and is rejected by pyright. `read` retains
the useful relationship between the requested model class and return value.

Concrete overloaded construction helpers preserve the type relationship:
omitting `output_type` constructs `TurnRequest[None]`; passing `type[T]`
constructs `TurnRequest[T]`. `TurnResult[None].output` is statically `None` and
callers read the transcript through `messages` or `blocks`.

Portable structured results use one mechanism: a turn-specific
`submit_output` MCP tool generated from `output_type.model_json_schema()`. Its
handler validates the submitted value with Pydantic, optionally checks a
composed reflection gate, writes through `SubmittedOutputStore`, and returns
actionable validation or gate failures to the model. Native structured-output
APIs are not part of the portable path and never run alongside this tool.

Before accepting a turn, the concrete `Session` implementation creates a fresh
turn-scoped store and `TurnToolBinding`, then composes a `TurnToolBinder` to
install the requested submission schema. Passing `None` removes the tool when
`output_type is None`. The binder owns native tool registration, refresh, and,
when refresh is unavailable, reconnect/resume behavior. It may cache an
unchanged native schema artifact, but it must attach the current turn's store
and gate before sending input; an `A -> A` transition cannot retain the prior
turn's submission state. It must fail before sending input if it cannot change
the schema while preserving the conversation, and it never exposes an old or
generic schema. This keeps native tool mechanics inside the concrete
implementation while sharing submission validation and reflection behavior.

Provider configuration is bound once into an immutable reusable
`SessionFactory`. Output selection remains per turn. Session resumption is an
explicit `open(resume=...)` input.

One Lup turn covers the complete application input through terminal completion,
including native model iterations, reasoning, tool calls/results, usage, and
correction cycles. A session is a stateful sequence of Lup turns.

A successful `TurnResult[T]` always contains the corresponding `output: T`,
one canonical ordered sequence of completed text, thinking, tool-call, and
tool-result blocks, derived message/tool views, usage, duration, and
identifiers. For
`TurnRequest[None]`, the corresponding output is `None`. For
`TurnRequest[T]`, missing or invalid submission never produces a successful
result. `TurnResult` represents success only. Provider failure, timeout,
budget exhaustion, interruption, session-exit abortion, and output failure
raise `ProviderTurnError`,
`TurnTimeoutError`, `BudgetExceededError`, `TurnInterruptedError`,
`TurnAbortedError`, or `StructuredOutputError` under the common `TurnError`
base, carrying all available partial blocks, usage, timing, identifiers, and
validation history.

Live events and completed replay remain distinct. `EventStream` exposes native
live events only. Every completed result can provide block replay as a result
view, but replay is not advertised as live streaming.

A session permits one active turn. `start()` awaits native acceptance and
returns only after the turn and its capability handles have valid native
identities. Startup, tool-binding, and resume failures surface directly from
`start()`. A second `start()` raises
`TurnAlreadyActiveError`. A concrete `SerializedSession` composes a `Session`
when callers explicitly want queued independent turns. Exiting with an
unfinished turn aborts it, requests interruption when an `Interrupt` capability
is present, always closes native resources, and makes `result()` raise
`TurnAbortedError`.

Submission validation, missing-submission correction, and transport retry are
separate concrete compositions rather than output ABCs. The application
template composes up to two bounded correction cycles to preserve current
behavior. Timeout, budget, usage, tracing, and recovery limits cover the whole
Lup turn without resetting between correction cycles. Reflection and output
persistence are optional independent dependencies of the submission handler;
the template enables them where its current recipe requires them.

### Configuration transformation, policy, and routing contracts

```python
class ConfigTransform[C](ABC):
    @abstractmethod
    def apply(self, config: C) -> C: ...


class ProfileResolver[C](ABC):
    @abstractmethod
    def resolve(self, name: str | None) -> ConfigTransform[C]: ...


class DecisionPolicy[E](ABC):
    @abstractmethod
    def decide(self, event: E) -> Decision: ...


class Observer[E](ABC):
    @abstractmethod
    def observe(self, event: E) -> None: ...


class ModelMatcher(ABC):
    @abstractmethod
    def matches(self, model: str) -> bool: ...
```

Profiles and compatible endpoints are concrete `ConfigTransform`
implementations. There are no `Profile` or endpoint capability hierarchies.
Profile lookup/storage implements the independent capability
`ProfileResolver` contract and produces a selected transform. Transforms apply
before factory construction and never inspect an assembled session object.

There is one `DecisionPolicy` contract and one `Observer` contract, parameterized
by typed event models. Approval, tool, edit, stop, directory, and other policies
are concrete implementations, not child ABCs. A concrete ordered policy chain
composes policies and implements `decide()` with conservative aggregation:

1. malformed or unclassifiable security-sensitive input asks;
2. any deny wins;
3. otherwise any ask wins;
4. only then allow.

Observers cannot grant permission. Observer failure is recorded and surfaced
without changing an already computed decision; configurable fail-fast
observation is a separate concrete decorator.

`ModelRouter` and `ModelRoute` are immutable data. Routes compose a
`ModelMatcher` and a recipe returning a configured `SessionFactory`. Explicit
recipe selection precedes model inference; first match wins; unknown models
raise. There is no empty-pattern fallback and no import-time mutable registry.
The application template may translate `AGENT_SDK` into an explicit named
factory recipe at its configuration boundary; neither the environment variable
nor its adapter ID enters library routing or session logic.

## Typed configuration ownership

Remove the monolithic `LupAgentOptions`, `ConsumeTracker`, `INTENT_KNOBS`, and
`refuse_unconsumed()`. Each concrete component owns a validated immutable model
containing only fields it consumes:

- each native session factory owns its SDK/process/model/tool/sandbox config;
- timeout, budget, recovery, tracing, display, persistence, and serialization
  wrappers own separate configs;
- profile stores own account-selection config;
- compatibility transforms own URL, authentication, naming, and model mapping;
- `TurnRequest[T]` owns per-turn input and the optional Pydantic output type;
- the submission handler owns reflection, validation, and persistence inputs;
- each native `TurnToolBinder` owns turn-tool registration and rebinding.

No public convenience API accepts generic `**kwargs`. Unsupported configuration
is rejected by the component's model or constructor, never discovered through
reflective field reads.

`query(factory, request)` is a small typed concrete function: open one session,
start one turn, await its result, and close the session. Text convenience
overloads may shorten construction of `TurnRequest[None]`; terminal prose stays
in `TurnResult.messages` and is not promoted to a second output mechanism.

### Repository conventions are implementation gates

All new structured records, handles, configuration, state, proposals, and
fixtures use concrete Pydantic `BaseModel` types; use `TypedDict` only at an
external dict-shaped boundary. Do not introduce dataclasses, named tuples,
anonymous tuple annotations, `Any`, bare `object`, broad string-keyed payload
dictionaries, or generic `BaseModel` annotations.

Structured input is decoded with its owning parser or SDK type. Native JSON,
TOML, paths, URLs, events, invocations, and model output are never interpreted
through regular expressions, separator splitting, stripping, replacement, or
string slicing. Native process work uses `sh`, file operations use `Path`,
configuration uses Pydantic settings, and CLIs use Typer.

Every function is fully typed. Internal packages import defining modules
directly, do not add barrel exports, and do not introduce private-prefix names.
Dispatch on typed variants uses `match`/`case`. Exceptions are handled,
recorded, or propagated; they are never silently swallowed. Tests exercise
behavior, invariants, state transitions, integration points, and failures
rather than Pydantic construction, default fields, or copied constants.

## Generated-source ownership and reconciliation

Reusable harness ABCs, Pydantic models, prompt parts, rendering composition,
reconciliation, ownership, and materialization live under `packages/lup/`.
They must be complete as-is and configurable through constructor arguments.
Project-specific canonical declarations, native catalogs, generated-artifact
inventory, and CLI composition roots live under
`src/lup_template/devtools/harness/`. The library never imports the template.

Use immutable validated `Harness`, `Plugin`, `Skill`, `Argument`, `Agent`,
`HookSet`, `ResolveSpec`, `PromptDocument`, artifact, diagnostic, ownership, and
proposal models. Do not create a subclass per workflow.

Shared prompt content is an ordered `PromptDocument` whose typed parts describe
semantic operations such as asking the user, delegating work, requesting
approval, invoking a skill, and reporting that user input is required. Native
renderers translate only those typed operations and preserve ordinary text.
Shared objects must not contain parallel native prompt fields, target-prefix
tokens, or embedded rendered invocations. If a shared operation is not
representable, rendering fails explicitly; it is never dropped.

Platform specialization uses shared and adapter-specific catalogs. An override
replaces the complete named declaration. Catalog assembly never recursively
merges fields. Duplicate effective names and overrides of nonexistent shared
keys fail validation unless the item is explicitly native-only.

Generated artifacts are committed deployable output. The ownership manifest
records schema version, generator version, canonical source digest, target
requirements, semantic object IDs, ownership categories, and per-file hashes.
Every path is one of:

- generated and owned;
- backpropagation candidate;
- local-only;
- sensitive local-only;
- unknown conflict;
- obsolete generated, removable only with prior ownership proof.

Render and validate the complete desired tree in memory before changing active
files. Materialize changed generator-owned files with adjacent temporary files
and atomic rename. Never recursively delete a native configuration directory.
Interrupted multi-file writes converge on the next deterministic run.

Typed importers may translate understood native/local changes into a
`ReconciliationProposal`. Reconciliation writes a local proposal under
`.lup/reconcile/<proposal-id>/` containing metadata, base digests, and a source
patch. It never edits canonical Python.

`lup-devtools harness apply-reconciliation <proposal-id>` is the only promotion
operation. It verifies base digests, displays the patch, requires explicit
confirmation, applies it, regenerates all affected targets, and removes the
proposal only after successful validation. Arbitrary Markdown, scripts, prompt
prose, and sensitive settings are never reverse-engineered into source patches.
Recognized frontmatter, arguments, and typed prompt operations may be imported;
all other edits remain explicit conflicts.

The complete public harness CLI is:

```text
lup-devtools harness claude
lup-devtools harness codex
lup-devtools harness resolve --adapter claude|codex
lup-devtools harness reconcile [claude|codex|all]
lup-devtools harness apply-reconciliation <proposal-id>
lup-devtools harness generate [claude|codex|all]
lup-devtools harness check [claude|codex|all]
lup-devtools harness doctor [claude|codex|all]
```

The two named launch commands are concrete composition roots. Generic harness
commands select an adapter explicitly at the application boundary; the adapter
ID is never passed into neutral rendering, policy, or resolver logic.

Interactive native launchers regenerate on every invocation. They render and
validate in memory, show the planned tracked diff, reconcile promotable or
unknown changes, atomically update only changed generator-owned files, verify
runtime readiness, and launch. Non-interactive launch fails on unresolved
promotable changes or unknown conflicts. Local-only and sensitive-local-only
values neither fail nor appear unredacted in diagnostics.

`generate` is deterministic and non-interactive. `check` is read-only. A local
pre-commit hook regenerates and stops when files change so the developer can
review the diff. CI performs read-only generation/drift checks and never pushes
bot commits.

## Linear implementation plan

### Milestone 1 — audited baseline and neutral foundation

Inventory and hash every tracked artifact in the current native harness. Record
behavioral golden fixtures for skills, agents, guidance, settings, manifests,
hooks, scripts, permissions, project tools, profiles, model overrides, optional
prompts, usage display, passthrough arguments, and the current native resolver.
Local settings and backup files are not baseline artifacts.

The audited migration input was the 45 files originally tracked under
`.claude/`. After the three legacy policy executables were intentionally
retired, the immutable native catalog locks the remaining 42:

- project guidance: `CLAUDE.md` and `PATTERNS.md`;
- plugin and marketplace manifests;
- 28 commands: `add-command`, `brainstorm`, `bump`, `clean-gone`, `close`,
  `commit`, `create-investigator`, `debug`, `fb-analyze`, `fb-implement`,
  `fb-investigate`, `fb-reflect`, `fb-status`, `feedback-loop`, `hooks`,
  `import`, `init`, `install`, `merge`, `meta`, `modify-command`, `principle`,
  `rebase`, `refactor`, `refactor-tools`, `resolve`, `review`, and `update`;
- five agents: `implementer`, `resolve-editor`, `trace-explorer`,
  `version-explorer`, and `version-reviewer`;
- hook configuration (the three legacy fetch, shell, and edit/write scripts are
  recorded as intentional removals and replaced by generated artifacts);
- file suggestion support and `TEMPLATE_CLAUDE.md`;
- project settings and the native resolver workflow.

`.claude/settings.local.json`, `.claude/CLAUDE.md.bak`, bytecode caches, and
other ignored local files are explicitly outside the tracked baseline. There is
no tracked `.codex/` or `.agents/` baseline; those trees are new generated
outputs and must be validated from their semantic declarations and native
fixtures rather than compared to invented golden files.

Capture representative native hook input/output fixtures and maintain a
versioned evidence matrix for the supported CLI, plugin, hook, SDK, and
app-server contracts. Runtime versions are evidence, not architectural
branches. Generation targets a declared minimum capability baseline and fails
clearly when the installed runtime is older; Lup never updates a user-installed
runtime automatically.

Land the exact ABCs and semantic models in this plan, the ABC AST rule, neutral
import/spelling boundaries, and contract tests before native rendering work.

Acceptance:

- every existing artifact and behavior has a golden entry or documented
  intentional exception;
- every capability claim is backed by a captured fixture, live probe, or
  primary documentation reference;
- all shared contracts pass the ABC and neutrality checks or carry a justified,
  typed suppression that passes the suppression audit;
- no `Engine`, backend aggregate, native-name catalog, or native prompt spelling
  exists in the neutral target architecture.

### Milestone 2 — semantic harness declarations and pure composition

Implement the validated canonical declarations, typed `PromptDocument` parts,
artifact models, ownership models, and reconciliation models. Build a concrete
tree generator by composing focused `ArtifactRenderer` implementations and
tree validators.

Validation includes:

- stable unique names and deterministic ordering;
- ordered valid argument definitions;
- no rendered invocation, prefix placeholder, or adapter branch in shared
  prompts;
- no unsupported shared operation for a selected target;
- no target path escape or duplicate artifact path;
- deterministic encoding, newline, and serialization rules;
- valid cross-skill invocation graphs and native resource paths;
- bounded always-loaded instruction and discovery-description budgets;
- no accepted field that the target ignores;
- no anonymous tuple-shaped record.

Implement `CurrentTreeReader`, `Reconciler`, `Materializer`, and patch-only
backpropagation as independent capabilities. Add convergent
materialization and stale-base proposal tests.

Acceptance:

- canonical declarations render deterministically through injected renderers;
- semantic invocations contain no native prefix;
- rendering an unsupported operation fails with the semantic object ID;
- launch reconciliation cannot edit source without the separate explicit apply
  command.

### Milestone 3 — concrete Claude harness adapter

Implement concrete Claude renderers, native hook decoders/renderers, tree
reader, capability probe, materializer wiring, and process launcher. Concrete
Claude modules own command syntax, tool names, hook payloads, plugin paths,
settings, profile/config-directory behavior, and process flags.

Regenerate the existing 28 commands, five portable agents, project guidance,
settings, permissions, plugin metadata, marketplace, hook scripts, generated
antipattern table, template, file suggestion support, project MCP wiring,
additional plugins, and a thin resolver entry artifact from canonical
declarations. The entry invokes the one Python resolver core; it does not own
resolver phases or state transitions.
Byte parity is preferred; behavior parity is required. Every intentional
formatting or provenance difference is recorded.

The public launcher is:

```text
lup-devtools harness claude
```

It regenerates/reconciles the managed tree, validates it, probes capabilities,
and launches with profile, model, optional prompt, usage behavior, project
tools, and passthrough arguments.

The adapter owns these generated locations:

```text
.claude/
  CLAUDE.md
  PATTERNS.md
  settings.json
  plugins/
    .claude-plugin/marketplace.json
    lup/
      .claude-plugin/plugin.json
      commands/*.md
      agents/*.md
      hooks/hooks.json
      hooks/scripts/*
      scripts/*
      TEMPLATE_CLAUDE.md
  workflows/commands/resolve.js
```

Acceptance:

- all baseline artifacts and policy outcomes are accounted for;
- generated hooks are hermetic and import only their bundled runtime;
- the generated resolver entry invokes the shared resolver with the concrete
  composition root and contains no duplicate orchestration;
- ordinary launch preserves local and sensitive settings;
- golden differences are reviewed and documented.

### Milestone 4 — concrete Codex harness adapter

Implement concrete Codex renderers, native hook decoders/renderers, tree reader,
capability probe, plugin installer/cache verifier, materializer wiring, and
process launcher. Concrete Codex modules own skill invocation syntax, native
tool names, hook payloads, project config, `CODEX_HOME`, named profile overlays,
plugin/marketplace layouts, trust checks, app-server messages, and process
flags.

Generate:

- a real plugin manifest and one same-named skill for every portable command;
- hermetic hook configuration, scripts, and bundled policy runtime;
- project custom-agent configuration from the canonical portable agents;
- project guidance at the documented repository guidance location;
- supported project configuration and project MCP resources;
- repository marketplace metadata and adapter-specific additional plugins.

The adapter owns these generated locations:

```text
.codex/
  config.toml
  agents/*.toml
  plugins/lup/
    .codex-plugin/plugin.json
    skills/*/SKILL.md
    hooks/hooks.json
    hooks/scripts/*
    hooks/runtime/*
    .mcp.json
    assets/*
.agents/plugins/marketplace.json
AGENTS.md
```

Only declared resources are emitted; optional `.mcp.json` and `assets/`
entries are absent when unused. The checked-in `.codex/plugins/lup/` tree is
the canonical compiled source package. The launcher verifies the separately
installed cached copy before execution. Project custom agents remain outside
the plugin because their native configuration is project-scoped.

The public launcher is:

```text
lup-devtools harness codex
```

It regenerates/reconciles, checks project and hook trust without writing
personal trust state, probes the external CLI separately from the pinned SDK
runtime, verifies the installed cached plugin digest, installs only when
missing/stale unless forced, and launches the exact verified copy. `CODEX_HOME`
and a named `--profile` remain distinct inputs. It never runs an automatic CLI
update.

Native invocation rendering is performed from `SkillInvocation`; there is no
`/lup:` to `$lup:` replacement. Native edit, shell, fetch/search, and hook names
are recognized only by the Codex decoder.

The generated resolver skill is a thin entry into the same Python resolver core
used by the other adapter. It supplies the concrete session, invocation,
question, launcher, and state-root capabilities but owns no scheduling logic.

Acceptance:

- every portable command and agent has a usable native artifact;
- plugin, marketplace, hooks, config, project tools, and launcher are exercised
  through captured fixtures and live tests where available;
- missing first-adapter-only behavior is reported as an evidence-backed gap;
- trust, plugin-only readiness, and full-project readiness are diagnosed
  separately;
- cache digest and passthrough behavior cover unknown/repeated flags, `--`, and
  launcher collisions.

### Milestone 5 — shared semantic policies and hermetic dispatchers

Make `lup.policy` the dependency-light canonical policy package. Migrate closure
factories to named concrete `DecisionPolicy` and `Observer` implementations.
Build concrete ordered chains by composition and compile one deterministic
dispatcher per native boundary instead of depending on native handler order.

Normalize edits to `EditBatch` before policy evaluation. A batch decision
applies conservatively to the entire batch. Native decoders must prove that a
multi-file patch cannot hide a violation beside a safe edit.

Preserve current fetch, shell, edit/write, protected-path, marker, large-write,
and antipattern outcomes at the parity gate. Native `ASK` rendering is
capability-aware: use native approval where it exists; otherwise fail closed
with an actionable denial and record the approximation. Never render a
fictional approval result that fails open.

Bundle a digest-tracked policy runtime snapshot under each plugin. Thin native
dispatchers decode input, call the composed semantic chain, and render the
native result without importing the checkout or installed project package.

The parity ledger must preserve these current semantic outcomes:

- URL-fetch policy normalizes origin/path, evaluates deny before allow, allows
  the currently declared documentation origins, and asks on unknown or
  malformed input;
- shell policy splits unquoted compound commands, evaluates every segment,
  never auto-allows substitutions, rejects interpreter or package-runner inline
  code except the declared temporary-script case, retains the curated read-only
  and development allowlist, and asks for dependency-changing operations;
- across shell segments, deny wins over ask/unknown and every segment must be
  allowed before the whole command is allowed;
- edit policy asks for protected harness paths, project configuration,
  environment files, temporary paths, new devtools modules, marker-count
  changes, and large/ordinary writes according to the golden rules;
- edit policy scans every added supported-language line for the canonical
  antipatterns; violations deny, typed ignores ask, and safe small edits,
  deletions, and safe identifier-wide replacements retain their golden
  outcomes;
- the resolver editor role retains its documented exceptions for large,
  protected, and new-devtools changes while marker/temp cases still ask and
  antipattern violations still deny.

Acceptance:

- equivalent native events decode to the same semantic model and policy result;
- deny/ask/allow aggregation and malformed-input behavior are deterministic;
- observer failures cannot weaken decisions;
- unsupported output effects fail during generation/setup;
- in-process and bundled policy forms pass the same canonical fixtures.

### Milestone 6 — one composed resolver core

Implement one Python resolver owning the complete algorithm. Keep one canonical
`ResolveSpec`, semantic phase model, typed concern/question/answer/manifest/state
schemas, portable merge behavior, and acceptance fixture suite. The resolver
core and its public semantic contracts live under `packages/lup/`; application
wiring and generated native entries live under `src/lup_template/`. The core
composes `SessionFactory` for worker and reviewer turns,
`SkillInvocationRenderer` for portable skill references, `ProcessLauncher` for
local process boundaries, and one question capability:

```python
class QuestionBroker(ABC):
    @abstractmethod
    async def ask(self, questions: QuestionBatch) -> AnswerBatch: ...
```

Git/worktree, lease, diff-validation, state-repository, and integration
services are concrete orchestrator components composed from those capabilities.
They are not duplicated per runtime and become ABCs only if an independently
replaceable implementation is actually required.

Persist gitignored state under:

```text
<injected-state-root>/<run-id>/
  state.json
  concerns.json
  questions.json
  answers.json
  leases.json
  bases.json
  agents/
  reviews/
  integration/
```

Each concrete composition root supplies its state root. The shared resolver
does not construct a path from, inspect, or persist an adapter identifier.
State is typed, schema-versioned, atomically written, and records the source
branch/commit, concern DAG, acceptance criteria, user decisions, brokered
questions, worktree leases, dependency bases, agent rounds, validated diffs,
orchestrator-created commits, verification, integration, failures, and cleanup.

Resolver phases are fixed:

1. inventory and organize concerns without editing;
2. ask the user only material questions through the broker and persist answers;
3. record per-concern eligibility and integration approval;
4. construct the dependency DAG and reject missing nodes/cycles;
5. create orchestrator-owned branches/worktrees and writable-root leases;
6. run workers without branch/commit authority, validate their diffs, and have
   the orchestrator create commits;
7. build each child's dependency base from its verified parents, using the
   semantic merge capability for multi-parent joins;
8. run review/revision rounds against persisted acceptance criteria;
9. integrate only verified, approved concerns into a dedicated review-master
   worktree through one merger agent using the portable merge skill;
10. run combined verification and an independent final review;
11. present the review branch for human acceptance and record cleanup/retained
    worktrees explicitly.

Workers communicate user questions through typed broker messages and resume
after persisted answers. They never invoke native skill spellings directly;
the orchestration uses `SkillInvocationRenderer`.

Every generated native resolver command is a thin entry artifact that calls
this Python resolver with its concrete capability implementations. It owns no
phase, lease, scheduling, review, or integration logic. Adapter selection for
scripting is an explicit CLI-boundary choice, never environment inference or a
branch inside the resolver.

Acceptance:

- root, single-parent, and multi-parent nodes receive complete dependency bases;
- transitive approval, lease enforcement, question/resume, and commit authority
  are correct;
- parallel nodes never share writable roots;
- multi-parent semantic joins and final review-master integration are tested;
- each concrete entry drives the same persisted state transitions and canonical
  acceptance fixtures;
- no resolver path writes or merges directly into the user's branch;
- retained branches/worktrees have actionable cleanup records.

### Milestone 7 — session, turn, and output runtime migration

Implement the neutral runtime contracts and adapter-owned validated configs.
Build independent Claude and Codex `SessionFactory`, `Session`, `Turn`, live
event, interruption, steering, and forking implementations only for capabilities
supported by each SDK/runtime. Each implementation also composes its
`TurnToolBinder` so `submit_output` is registered with the current turn's
Pydantic schema. Compose capabilities into frozen Pydantic `SessionHandle` and
`TurnHandle` values rather than one multi-capability implementation class.

The named adapter composition roots are:

```python
def create_claude_session_factory(
    config: ClaudeSessionConfig,
) -> SessionFactory: ...


def create_codex_session_factory(
    config: CodexSessionConfig,
) -> SessionFactory: ...
```

These functions live in their concrete adapter packages. Neutral callers
receive an already configured `SessionFactory` and never branch on the factory's
origin.

Move Codex execution from post-hoc completed replay to live app-server turns and
routed notifications where supported. Serialize structured config instead of
interpolating raw TOML. Keep optional SDK imports lazy so importing Lup does not
require every adapter dependency.

Compatibility endpoints are concrete `ConfigTransform` implementations applied
to the matching native config before ordinary factory construction. They do not
own sessions, profiles, background drivers, tools, or policy tables.

Acceptance:

- one-shot and persistent sessions use the same contracts;
- `Session.start()` awaits schema binding and native acknowledgement;
- `None -> A -> A -> B -> None` turn output types in one session bind, reuse,
  rebind, and remove the submission tool correctly, with a fresh store and
  reflection gate for both `A` turns;
- successful `TurnResult[T]` always contains the submitted and validated `T`,
  while `TurnResult[None].output` is exactly `None`;
- reflection-gated submission, cross-process persistence, malformed values,
  missing submission, and bounded correction cycles are tested identically
  through both implementations;
- no portable turn enables a native structured-output mechanism alongside
  `submit_output`;
- live events, interrupt, steer, and fork are tested against captured fixtures
  and marked live smoke tests;
- absent capabilities are `None`, not raising stubs;
- imports work without optional SDKs installed;
- errors identify the rejecting config or capability.

### Milestone 8 — concrete wrappers and cross-cutting behavior

Retain and type-strengthen timeout and budget as concrete decorators around the
factory/session/turn boundary they govern. Add recovery, tracing, usage,
display, persistence, and serialization decorators at their actual event
boundaries. Keep budget estimation separate from native usage translation.

Make wrapper order explicit in composition roots. Timeout, budget, usage, and
tracing cover the complete logical turn including recovery cycles. Completed
replay derives from `TurnResult.blocks` and does not implement `EventStream`.

Acceptance covers cancellation, timeout cleanup, exhausted budgets, resumption,
replay, live events, submission correction, validation history,
partial-error propagation, abort-on-close, one-active-turn enforcement, and
serialized queuing.

### Milestone 9 — profiles, background scheduling, tool identity, and routing

Profiles:

- implement adapter-specific profile selection as concrete config transforms;
- keep Claude config-directory, Codex account/config home, and Codex named
  overlay semantics distinct and typed in their adapter packages;
- apply transforms before factory construction;
- test active/default/explicit selection and missing profiles.

Background work:

- retain `BackgroundAgent` as a concrete queue/debounce/start/wake/stop
  scheduler;
- compose it with a configured `SessionFactory` and typed state-to-request
  callable;
- remove native background client reconstruction and blanket tool rejection;
- introduce another scheduling ABC only if a scheduler operation becomes an
  independently useful replaceable capability.

Tool identity and routing:

- retain semantic `ToolKind` and original identity only for audit output;
- decode native and dynamic MCP identities privately in each adapter;
- delete provider-wide builtin-tool tables and the shared native-name catalog;
- compose immutable routes from `ModelMatcher` and explicit factory recipes;
- reject unknown models and avoid optional-SDK construction at import time.

### Milestone 10 — caller migration and breaking release

Migrate this repository's callers, tests, examples, template, and devtools to
direct composition. Registered downstream repositories are explicitly outside
this release gate and are not inspected or modified. Remove in the same
breaking runtime release:

- `Engine` and every engine subclass;
- `Client` and `ComposedClient`;
- `LupAgentOptions`, `ConsumeTracker`, `INTENT_KNOBS`, and
  `refuse_unconsumed()`;
- compatibility-engine delegation;
- provider-specific background drivers that reconstruct clients;
- provider-wide builtin-tool registries;
- completed-replay implementations advertised as streams;
- unsupported-operation methods and stale capability assumptions.

Publish a version bump, changelog, and migration guide containing an exhaustive
old-to-new table:

| Old surface | Replacement |
|---|---|
| `Engine.client()` / `Client.session()` | adapter-owned `SessionFactory.open()` |
| `Client.query()` | concrete typed `query(factory, request)` |
| `Client.stream()` / replay stream | `TurnHandle.events` for live events; `TurnResult` replay view for completed output |
| `Session.send()` | await `Session.start(TurnRequest)` then await `Turn.result()` |
| `Session.interrupt()` | optional composed `TurnHandle.interrupt` capability |
| `LupResponse.output(Model)` | `TurnResult[Model].output` from validated `submit_output` |
| native `output_schema` / `output_format` options | `TurnRequest(output_type=Model)` and the turn-bound submission tool |
| template-created `submit_output` tool | session implementation binding the portable turn submission tool |
| `Engine.profiles()` / `Profile.select()` | adapter profile resolution plus `ConfigTransform.apply()` |
| `Engine.background()` / native background drivers | `BackgroundAgent(SessionFactory, state_to_request)` |
| `Engine.builtin_tools()` | adapter-owned `NativeEventDecoder` plus semantic events |
| compatibility engines | typed adapter-config transforms |
| broad `LupAgentOptions` | component-owned validated configs and `TurnRequest` |
| mutable/global routing | immutable routes and explicit factory recipes |
| `lup-devtools claude` | `lup-devtools harness claude` |

Keep the package-root front door deliberately small: `SessionFactory`, the
request/result and handle models, and `query`. Specialized capability ABCs are
imported from their defining modules; internal packages do not add barrel
exports. Inventory every exported symbol and in-repository consumer before
removal; extend this
table until no removed public symbol or option lacks a documented replacement.
There is no runtime legacy facade.

### Milestone 11 — independent Ruff and Lup AST modernization

The ABC architecture rule lands in Milestone 1. The broader linter migration is
independently accepted and is not a prerequisite for harness, resolver, or
runtime milestone acceptance.

1. enable only applicable, non-duplicated Ruff rules and fix genuine hits;
2. retain typed `# lup: ignore[rule-id]` as the sole Lup-rule suppression
   format, including missing, untyped, and spurious-ignore auditing;
3. implement `abc-capability` and migrate structural repository-specific checks
   to typed Lup AST rules while preserving stable kebab-case rule IDs;
4. run Ruff and the Lup checker independently against proposed edit content through the
   semantic policy;
5. migrate legitimate bare `# lup: ignore` markers to the narrow typed form and
   remove only spurious markers;
6. remove regex implementations only for rules whose concern is structural and
   has moved to AST/token analysis, after behavior-equivalent and adversarial
   tests pass. Keep a single hermetic generated checker snapshot for hook use.

Update `docs/dev-tooling-decisions.md` in the same milestone so it no longer
recommends the superseded `# noqa` migration or describes the regex table as
the intended final architecture.

Do not adopt `# noqa` for Lup rules: Ruff has no stable third-party rule API, so
renaming suppressions would not remove the Lup checker or its audit machinery.
Regular expressions remain valid only for concerns that are genuinely free-text
pattern matching. They are forbidden as substitutes for semantic invocation
rendering, native event decoding, structured parsing, or AST rules.

## Verification matrix

Required automated suites:

- AST success for cohesive one-, two-, and three-method ABCs, plus failures for
  unsuppressed zero or four-or-more abstract methods, concrete ABC members,
  abstract properties, capability inheritance, and concrete
  multiple-capability or implementation inheritance;
- `abc-capability` suppression tests for inline and file-level typed ignores,
  bare-ignore compatibility and untyped auditing, and missing or spurious rule
  identifiers;
- architectural import and native-spelling boundary tests;
- deterministic artifact generation, provenance, ownership, path safety,
  newline/encoding, and drift tests;
- semantic invocation fixtures proving that each renderer owns the complete
  native spelling and no prefix replacement occurs;
- native event fixtures proving equivalent edits decode to the same
  `EditBatch`, including multi-file edits and malformed inputs;
- unknown-tool tests proving conservative behavior without a shared mapping
  update;
- canonical policy fixtures against in-process and bundled runtimes;
- reconciliation tests for local/sensitive preservation, patch-only promotion,
  stale-base rejection, explicit apply, atomic replacement, and interrupted-run
  convergence;
- runtime capability preflight, trust, cache digest, profile, passthrough, and
  optional-SDK import tests;
- typed factory/config/session construction and static type tests;
- session, asynchronous turn startup, `None -> A -> A -> B -> None` tool-schema
  rebinding where the native boundary supports it, and fail-before-input
  evidence where it does not; submitted output, reflection, persistence, error,
  stream, replay, interrupt, steer, fork, resume, timeout, budget, correction,
  cleanup, and background tests;
- route precedence, unknown-model, custom recipe, and compatibility-transform
  tests;
- resolver DAG tests covering parallel roots, single-parent dependencies,
  multi-parent semantic joins, brokered user input, revision rounds, lease
  violations, final integration, and cleanup;
- live native smoke tests behind explicit markers;
- Ruff/Lup AST parity, suppression-audit, and adversarial edit tests in the
  independent linter milestone.

## Acceptance gates

### Gate A — neutral foundation

- every ABC passes the automated invariant or carries an audited, justified
  `abc-capability` suppression, and every ABC still passes cohesion review;
- neutral packages have no adapter imports or native wire spellings;
- semantic models and error contracts are typed and immutable;
- a third adapter can be added without modifying shared invocation or tool-name
  registries.

### Gate B — harness parity

- the Claude golden baseline is preserved apart from reviewed exceptions;
- the Codex harness provides every portable skill and agent within verified
  native capabilities;
- generated plugins are hermetic;
- generation, reconciliation, launch, trust, and drift behavior are tested;
- every capability gap is explicit and evidence-backed.

### Gate C — resolver safety

- dependency scheduling, approval, bases, joins, leases, questions, and commit
  authority are correct;
- only verified approved work enters the review master;
- final integration is independently verified and requires human acceptance;
- user branches are never mutated by resolver integration.

### Gate D — runtime composition

- no service-locator aggregate or monolithic options object remains;
- sessions and optional turn capabilities are composed from independent
  narrow-capability implementations;
- wrappers, transforms, policies, observers, background work, and routing
  compose independently;
- typed output and errors preserve their strict contracts;
- native live capabilities are implemented when supported and absent otherwise.

### Gate E — migration release

- every removed public symbol, option, import, and known consumer has a tested
  replacement and migration entry;
- every in-repository caller is migrated;
- version, changelog, examples, capability matrix, and architecture docs are
  updated;
- no legacy facade or silent option compatibility remains.

### Gate F — linter modernization

- Ruff owns standard built-in rules and the typed Lup AST checker owns
  repository-specific rules without duplicated diagnostics;
- `# lup: ignore[rule-id]` suppressions are typed and audited, and `# noqa`
  remains forbidden by repository policy;
- both native hook implementations invoke the same semantic checker behavior;
- legacy generated regex tables and generic ignores are removed.

## Documentation deliverables

- root and package READMEs plus `.claude/CLAUDE.md`, updated to remove the
  Engine/Client/options architecture, obsolete capability claims, and old
  launcher syntax;
- architecture guide explaining the one-to-three-method ABC rule, composition, typed
  capability handles, and callable boundary;
- harness authoring guide for declarations, renderers, generation,
  reconciliation proposals, and adapter-only components;
- contributor guide for regeneration-on-launch, pre-commit, CI drift, and
  generated artifact review;
- versioned native capability/hook evidence matrix with tested runtime versions;
- resolver lifecycle, state, recovery, lease, integration, and cleanup guide;
- runtime composition examples for factories, profiles, compatible endpoints,
  timeout, budget, policies, background work, typed turns, and `query()`;
- exhaustive migration guide from the removed engine/client/options surfaces;
- Ruff/Lup AST rule and typed-suppression guide;
- architecture decisions for committed generated artifacts, patch-only
  backpropagation, semantic hooks, one resolver core, plugin cache/trust,
  submitted output, and separate runtime capability contracts.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A small ABC recreates a service locator | Require independent constructibility plus cohesion review, not method count alone |
| Concrete implementations regain inheritance hierarchies | AST rule permits only direct implementation of one capability; use typed composition handles |
| Shared declarations become a lowest-common-denominator DSL | Keep adapter-only components explicit and fail unsupported shared operations |
| Native vocabulary leaks into common policy | Adapter-private decoders plus import/spelling boundary tests |
| Invocation conversion becomes fragile string manipulation | Typed `SkillInvocation` and adapter-owned full renderers |
| Generated files become noisy or stale | Deterministic renderers, ownership hashes, pre-commit regeneration, and CI drift checks |
| Launch regeneration destroys local settings | Typed ownership categories, in-memory validation, visible diff, and generator-owned atomic writes only |
| Reconciliation becomes a source-code editor | Persist a patch proposal and require a separate stale-base-checked apply command |
| Native features are assumed from obsolete behavior | Versioned evidence, captured payloads, live probes, and primary documentation |
| A changed per-turn output schema leaves a stale MCP tool or turn state | Bind before native turn acceptance, cache schema artifacts only, refresh the turn-local store/gate, reconnect/resume when required, and test `None -> A -> A -> B -> None` |
| Native structured output and submission diverge | Make `submit_output` the sole portable result path and prohibit both mechanisms on one turn |
| Hook order differs by runtime | One deterministic semantic dispatcher and conservative aggregation |
| Multi-file edits bypass policy | Decode the entire native operation to one `EditBatch` and decide over the batch |
| Installed plugins import checkout code | Bundle a digest-tracked dependency-light runtime inside each plugin |
| Resolver workers collide or commit unauthorized changes | Orchestrator-owned worktrees, writable-root leases, diff validation, and orchestrator commits |
| Parallel concerns pass alone but fail together | Dedicated review master, one semantic merger, combined tests, and independent final review |
| Typed portability regrows a giant options model | Component-owned configs and a deliberately small typed convenience API |
| Broad linter work blocks the architecture indefinitely | Land the ABC rule immediately and accept the full linter migration independently |
| `abc-capability` suppressions erode the composition boundary | Require narrow typed suppressions, audit missing/untyped/spurious ignores, record a reason, and retain mandatory cohesion review |

## Recommended execution order

1. Freeze the baseline and native evidence.
2. Land the neutral ABCs, models, composition handles, and architecture rules.
3. Land semantic declarations, focused renderers, ownership, materialization,
   and patch-only reconciliation.
4. Implement and accept Claude parity.
5. Implement and accept Codex parity within verified native capabilities.
6. Land and accept semantic policy dispatchers.
7. Land and accept the one Python resolver core and thin native entries.
8. Implement native session/turn capabilities and compatibility transforms in
   parallel after the contracts freeze.
9. Implement wrappers, profiles, background scheduling, tool decoding, and
   routing in parallel.
10. Integrate recipes and `query()`, migrate all callers, remove obsolete APIs,
    and publish the breaking runtime release.
11. Complete and independently accept the Ruff/Lup AST modernization.

## Capability ownership ledger

This table is exhaustive for the target architecture. Adding another ABC
requires updating this ledger and passing the cohesion review; implementation
may not invent an unrecorded capability seam.

`Owner` names the package that declares the shared contract. Concrete native
implementations remain in adapter packages and are injected by the named
composition roots described above.

| Capability ABC | Abstract operations | Owner | Concrete composition and absence behavior |
|---|---:|---|---|
| `ArtifactRenderer[S]` | 1: `render` | `packages/lup` harness | One implementation per artifact family; a target without that family omits the renderer, while an unsupported shared declaration is a render error |
| `ArtifactValidator` | 1: `validate` | `packages/lup` harness | Tree builders compose all validators required by a target; validation failure blocks materialization |
| `SkillInvocationRenderer` | 1: `render` | `packages/lup` harness | A concrete native renderer owns the full invocation spelling; every shipped target must provide one |
| `CurrentTreeReader` | 1: `read` | `packages/lup` harness | Concrete readers classify owned, local, sensitive, and unknown files; read failure blocks reconciliation |
| `Reconciler` | 1: `propose` | `packages/lup` harness | Composes current and desired trees into the sole `ReconciliationProposal` model |
| `Materializer` | 1: `apply` | `packages/lup` harness | Applies only a validated proposal to proven owned paths; no recursive target-directory deletion |
| `CapabilityProbe[C]` | 1: `probe` | `packages/lup` diagnostics | One instance proves one capability; reporters compose evidence and never probe by invoking unsupported behavior |
| `ProcessLauncher` | 1: `launch` | `packages/lup` process boundary | Native launchers own executable names, flags, and environment; failure returns/raises typed launch evidence |
| `NativeEventDecoder[N]` | 1: `decode` | `packages/lup` native boundary | Adapter implementations decode one native boundary to semantic models; malformed sensitive input becomes conservative evidence |
| `NativeDecisionRenderer[N]` | 1: `render` | `packages/lup` native boundary | Adapter implementations render semantic decisions to one native boundary; an unrepresentable effect fails closed |
| `SessionFactory` | 1: `open` | `packages/lup` runtime | Concrete composition roots return configured factories; unsupported implementations are absent rather than registered stubs |
| `Session` | 1: `start` | `packages/lup` runtime | Composes turn-tool binding and native startup; only one active turn unless explicitly decorated with serialization |
| `Turn[T]` | 1: `result` | `packages/lup` runtime | Resolves one acknowledged Lup turn; success and typed partial-error paths are disjoint |
| `EventStream` | 1: `events` | `packages/lup` runtime | Present only for live native events; completed replay stays a `TurnResult` view |
| `Interrupt` | 1: `interrupt` | `packages/lup` runtime | Optional `TurnHandle` field; verified absence is `None` |
| `Steer` | 1: `steer` | `packages/lup` runtime | Optional `TurnHandle` field; verified absence is `None` |
| `ForkSession` | 1: `fork` | `packages/lup` runtime | Optional `SessionHandle` field; verified absence is `None` |
| `TurnToolBinder` | 1: `bind` | `packages/lup` runtime | Adapter implementations own native tool refresh or reconnect/resume; schema artifacts may be cached but turn-local stores and gates may not |
| `SubmittedOutputStore` | 2: `write`, `read` | `packages/lup` runtime | In-memory and file-backed implementations support in-process and cross-process tools; missing required output is a turn error |
| `ConfigTransform[C]` | 1: `apply` | `packages/lup` runtime | Profiles and compatible endpoints are concrete transforms, not child ABCs |
| `ProfileResolver[C]` | 1: `resolve` | `packages/lup` runtime | Returns a selected transform; recipes without profiles omit profile resolution entirely |
| `DecisionPolicy[E]` | 1: `decide` | `packages/lup` policy | Ordered concrete chains aggregate deny, ask, and allow conservatively |
| `Observer[E]` | 1: `observe` | `packages/lup` policy | Composed after decisions and cannot grant permission; failures are recorded or surfaced by a decorator |
| `ModelMatcher` | 1: `matches` | `packages/lup` routing | Exact/prefix/purpose-built matchers compose immutable routes; no import-time mutable registry or empty fallback |
| `QuestionBroker` | 1: `ask` | `packages/lup` resolver | Native entries inject user-interaction delivery; unanswered material questions pause before worker execution |

Small text functions, callbacks, state reducers, and path formatters remain typed
callables. Worktree, lease, state-repository, diff-validation, and integration
components remain concrete compositions until a second independently useful
implementation justifies another ABC.

## Baseline and migration ledger

### Tracked native baseline

The complete locked 42-file tracked baseline is:

- `.claude/CLAUDE.md`, `.claude/PATTERNS.md`, and
  `.claude/settings.json`;
- `.claude/plugins/.claude-plugin/marketplace.json` and
  `.claude/plugins/lup/.claude-plugin/plugin.json`;
- the 28 command files named in Milestone 1 under
  `.claude/plugins/lup/commands/`;
- the five agent files named in Milestone 1 under
  `.claude/plugins/lup/agents/`;
- `.claude/plugins/lup/hooks/hooks.json`;
- `.claude/plugins/lup/scripts/file_suggest.sh` and
  `.claude/plugins/lup/TEMPLATE_CLAUDE.md`;
- `.claude/workflows/commands/resolve.js`.

Local-only `.claude/settings.local.json`, backup guidance, bytecode, caches,
credentials, trust state, active resolver state, and reconciliation proposals
are never generated or committed. There is no tracked baseline for `.codex/`,
`.agents/`, or root `AGENTS.md`; their first generated versions require schema,
fixture, and live capability evidence rather than invented byte parity.

The three legacy `auto_allow_*.py` scripts were removed after baseline capture.
The desired Claude tree replaces them with one generated dispatcher, one
hermetic semantic runtime, and a versioned evidence document; those are
canonical generated output rather than locked legacy input.

### Removed public families

The breaking release removes the package-root exports `Engine`, `Client`, the
old `Session`, `LupAgentOptions`, `create_client`, and `resolve_engine`, plus the
adapter-module families `Engine` and its implementations, `Client`,
`ComposedClient`, `Sessions`, replay/live `Stream` abstractions, `Profile`,
`BackgroundDriver`, provider background drivers, `ToolNames`,
`ConsumeTracker`, `INTENT_KNOBS`, and `refuse_unconsumed`. `query` remains but
takes a `SessionFactory` and typed request. Existing hooks, MCP helpers,
workspace/history models, telemetry, resilience, sandbox, scheduler, notes,
reflection, and tool-policy APIs remain unless their signatures directly name
a removed adapter type; such signatures are migrated without otherwise
redesigning those subsystems.

All references under `src/`, `packages/lup/src/`, `tests/`, both READMEs, and
the generated capability documentation are in-repository migration targets.
Registered downstream repositories are not release criteria.

## Resolver transition ledger

Each concern follows one persisted transition path:

```text
discovered -> waiting_for_answers -> eligible -> leased -> running
  -> validating -> reviewing <-> revising -> verified -> integrating
  -> integrated -> cleaned | retained
```

- A concern may move to `ineligible` only from `discovered` or
  `waiting_for_answers`, with a persisted user decision or failed prerequisite.
- A phase exception moves the concern to `failed` with partial evidence; retry
  resumes from the last atomically completed phase and never skips validation.
- A stale source/dependency base returns an otherwise eligible concern to
  `eligible` after rebuilding its base; it does not reuse old worker output.
- Lease loss stops the worker, marks its unvalidated diff rejected, and returns
  the concern to `eligible` only after cleanup.
- Review rejection moves `reviewing` to `revising` within the configured round
  limit; exhaustion moves it to `failed` and excludes it from integration.
- Only `verified` concerns with recorded integration approval enter
  `integrating`. Combined verification failure leaves the review-master branch
  retained and records no successful integration.
- Restart reconstructs state only from the injected state root and verifies
  branches, commits, worktrees, and leases before resuming. It never infers a
  run from another composition root or environment variable.

## Completeness checklist

Before implementation begins, verify this document and the baseline inventory
together account for:

- every ABC signature, owner, composition point, and absence behavior;
- every current generated artifact and local-only path;
- every native capability claim and evidence source;
- every command/skill, agent, hook, policy, project tool, profile, launcher,
  resolver entry, and generated guidance file;
- every resolver state transition, user decision, lease, dependency-base,
  integration, recovery, and cleanup outcome;
- every removed public API, option, import path, known caller, and replacement;
- every required unit, fixture, static typing, integration, live, drift, and
  migration test;
- every milestone's independent entry and exit criteria.

If the inventory finds an unlisted public surface or native artifact, extend
the relevant milestone, migration table, and acceptance fixture before its
implementation starts. No implementer may silently decide an unrecorded
fallback, compatibility behavior, precedence rule, or native approximation.

### Evidence closure and retained live checks

The required repository evidence is captured in `docs/native-capabilities.md`
and its fixtures. Claude reconnect/resume rebinding preserves conversation
identity; Codex 0.144.4 exposes dynamic tools only at `thread/start`, so an
incompatible persistent schema transition is rejected before input. Hook,
plugin-cache, custom-agent, generated-tree, live-event, fork, and app-server
schemas are pinned to the declared versions. The removal inventory and all
in-repository callers are covered by migration tests and scans.

Authenticated provider smoke tests remain opt-in integration tests because they
consume external accounts and model budget. They refresh evidence but are not a
substitute for the deterministic acceptance suite. Local-only files and
credentials remain intentionally outside completeness.

## Primary native references

Capability evidence must be refreshed against current primary documentation
rather than copied indefinitely from this plan:

- [Codex plugin structure](https://developers.openai.com/codex/plugins/build)
- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Codex app server](https://developers.openai.com/codex/app-server)
- [Codex structured output](https://learn.chatgpt.com/docs/non-interactive-mode#create-structured-outputs-with-a-schema)
- [Codex custom agents](https://developers.openai.com/codex/agent-configuration/subagents)
- [Codex project guidance](https://developers.openai.com/codex/agent-configuration/agents-md)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude structured output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Ruff custom-rule limitation](https://docs.astral.sh/ruff/faq/#can-i-write-my-own-linter-plugins-for-ruff)

When a contract changes, update the versioned evidence matrix, captured/live
tests, affected adapter, and this plan's concrete adapter section in the same
change. Shared semantic contracts change only when Lup's own intended semantics
change.

## Implementation completion review (2026-07-16)

This section is the authoritative disposition of the implementation. The
overhaul is complete within the evidence-backed native capability boundaries
defined by this plan. There is no legacy facade, duplicate resolver algorithm,
or silent native approximation left as release work.

### Final gate status

| Gate | Status | Completion evidence |
|---|---|---|
| A — neutral foundation | Pass | Narrow capability ABCs, immutable typed handles, AST cohesion enforcement, import/native-spelling boundary scans, and an injected third-recipe test. |
| B — harness parity | Pass | Locked 42-file Claude baseline, full portable Codex skill/agent bodies, immutable native catalog, hermetic generated policy runtimes, proposal/apply reconciliation, ownership-safe generation, cache/trust diagnostics, pre-commit and CI drift checks. |
| C — resolver safety | Pass | One Python core and thin native entries; exact persisted phase and concern transitions; inter-process lock; sibling worktree leases; worker Git-mutation denial plus branch/HEAD/diff/report validation; pairwise semantic joins; verified-only integration; combined verification; final review; human decision and cleanup. A real-git lifecycle test covers parallel roots, questions, rejection/revision, a multi-parent join, integration, and cleanup together. |
| D — runtime composition | Pass | The engine/client/options aggregate is removed. Claude and Codex factories compose typed sessions, turn capabilities, binders, strict output, errors, wrappers, routing, profiles, background work, observers, and native live events. Claude transcript fork and partial events are implemented; unsupported capabilities are absent. |
| E — migration release | Pass | Version 0.2.0, changelog, migration map, caller rewiring, runtime composition examples, trace/display/persistence, budgets, Codex MCP groups, subagents, persistent relay tools, sandbox cleanup, and explicit rejection of unsupported application settings are present. Legacy modules and the duplicate workspace output mechanism are removed. |
| F — linter modernization | Pass | Ruff owns standard rules; the typed Lup AST checker owns repository rules and suppression audits. Both generated hook runtimes use the same semantic fixture suite, generated canonical antipattern data, and shared AST refinements. The legacy regex hook executables and generator are removed. |

### Accepted native capability boundaries

- Codex CLI/app-server 0.144.4 accepts dynamic tools only on `thread/start`.
  One-shot typed turns and repeated same-schema turns work, but changing the
  schema inside one persistent thread cannot satisfy `None -> A -> A -> B ->
  None`. The adapter preserves identity and rejects an incompatible transition
  before input; it does not reconnect under a false continuity claim.
- Claude Agent SDK 0.2.89 supplies partial-message events, interruption,
  reconnect/resume, and latest-transcript forking, all of which are exposed.
  Steering is not claimed and `TurnHandle.steer` is `None`.
- Authenticated model smoke tests stay opt-in. Deterministic fixtures, native
  schema hashes, CLI probes, and plugin validation are the release gate.

These are completed absence behaviors under Gate D, not unfinished stubs.
`docs/native-capabilities.md` is the versioned evidence ledger.

### Blocking-finding disposition

| Finding | Disposition |
|---|---|
| BLK-1 | Fresh Claude sessions use a dashed UUID and adapter defaults/options have direct fixtures. |
| BLK-2 / BLK-3 | Shell parsing treats every punctuation run conservatively; substitutions and redirections ask, all segments are evaluated, and deny wins. |
| BLK-4 | The generated edit runtime scans canonical antipattern rows with full Python docstring/empty-collection context. |
| BLK-5 | Claude hooks, write confinement, default permission mode, thinking budget, add-dirs, and native subagents reach SDK options. Resolver workers receive a worktree-only permission composition. |
| BLK-6 | The Claude workflow and Codex skill are thin entries into `lup-devtools harness resolve`; scheduling exists only in `ResolverCore`. |
| BLK-7 | Dedicated `implementer` and `resolve-reviewer` declarations are generated and wired into `ResolveSpec`. |
| BLK-8 | Only verified outcomes populate dependency and integration commit maps. |

The five structural causes from the first review were removed at their entry
points: policy parity is pinned by one semantic fixture suite with generated
canonical scan data; adapter behavior has replacement tests; application
composition rejects or rewires every migrated setting; Codex artifacts compile
the complete portable prompts; reconciliation writes stale-base-checked patch
proposals and drift is enforced before review.

### Verification record

The 2026-07-16 completion run, refreshed after the post-completion fixes
below, produced the following release evidence:

- `ruff format --check` and `ruff check` pass;
- pyright reports zero errors and zero warnings;
- pytest reports 587 passed and 11 external integration tests deselected;
- the repository anti-pattern audit reports no findings and the native seam
  boundary audit passes;
- `lup-devtools harness check all` reports zero writes, deletes, conflicts, or
  ownership drift for both targets;
- `lup-devtools harness doctor all` validates Claude Code 2.1.211 and Codex CLI
  0.144.4, including Claude plugin validation and Codex app-server, plugin, and
  hook capability probes;
- `lup-devtools dev check` reports 6/7 checks passed. Its only failing check is
  the two pre-existing explicit review notes: the user-deferred history cleanup
  in `TODO.md` and the separate setup/dashboard product request in
  `agent/config.py`.

Those two notes are not part of this architecture plan and remain visible by
design; deleting them without resolving their separate concerns would violate
the repository's review-note policy.

### Post-completion fixes (2026-07-16)

An independent re-verification on a second machine found the original run's
"579 passed" evidence environment-dependent and two defects behind it. Both
are fixed and the record above reflects the refreshed run:

- `LocalProcessLauncher` captured child output through a pseudo-terminal, so
  git colorized and paginated under the host's `LESS`/`PAGER` configuration
  and resolver diff validation compared escape-polluted paths, failing every
  concern on such machines. Capture now uses pipes; a launcher contract test
  and a pager-hostile git fixture pin it.
- A run killed after the workers loop persisted `DEPENDENCY_BASES`, `REVIEW`,
  or early `INTEGRATION` could never resume: the re-entered batch loop
  persisted `phase=WORKERS` backward and every retry failed the phase guard.
  `ResolverCore.persist` now treats the phase as a monotonic high-water mark;
  a hard-kill/resume lifecycle test pins recovery through acceptance.

The same pass closed the remaining coverage debts recorded by the area
audits: direct `None -> A -> A -> B -> None` coverage through the real Claude
binder and options builder, Codex fail-before-input rebinding rejection and
`turn/steer` rendering fixtures, live-event joining and steer retargeting
across recovery attempts, and marker-count ask fixtures on both policy
engines including under resolve-editor autonomy.

## Historical implementation review (2026-07-16)

The remainder of this document section is the first post-implementation review
snapshot. It is retained to explain what the completion work corrected. Its
file/line references, failing-gate statements, and remediation list are
historical and are superseded by the completion review above.

**Provenance.** Findings come from six deep area reviews (runtime, adapters,
harness/generation, policy/codescan, resolver, migration/template) plus direct
verification. The four security/correctness criticals and the
inner-agent-confinement regression were confirmed by reading the code directly;
`resolve.js` being unchanged was confirmed by an empty `git diff`; the remaining
`file:line` references are as reported by the area reviews and should be
re-confirmed at fix time. Gate checks at review time: `pytest` 643 passed,
`pyright` clean, `ruff` clean, `lup-devtools dev check` 6/7 (two pre-existing
deferred `# lup:` markers).

### Overall assessment

The neutral capability-composition architecture is implemented faithfully and is
enforced by real boundary tests — ABCs, typing, ownership/materialization
safety, and the provider seams are as specified and are the strongest part of
the branch. The branch is **not shippable as one unit**: it carries two
confirmed security regressions in the live permission policy, a one-line bug
that breaks every fresh Claude session, a resolver whose Claude entry was never
migrated, and a template migration that silently dropped several 0.1 safety
behaviors. The failing set is small and localized, not diffuse.

What passes, and should be preserved as-is:

- neutral boundary is real (zero adapter imports in neutral packages; import and
  native-spelling AST scans enforce it);
- all 25 capability ABCs are plan-exact (1–3 abstract methods, no concrete
  members, no abstract properties, no ABC-inherits-ABC), enforced by the new
  `abc-capability` AST rule with typed-suppression auditing;
- typing is strong and pyright-clean (`TurnResult[None].output` statically
  `None`; `turn_request` overloads resolve correctly);
- materialization/ownership safety (in-memory render+validate before writes,
  atomic temp+rename, stale-base digests, symlink-escape rejection,
  ownership-proof deletes, deterministic output);
- the resolver state repository, `ConcernGraph` DAG, and Codex live app-server
  turn model;
- removals are complete with no legacy facade; the migration guide's old→new
  table covers every plan row with a real, verified replacement;
- tests that exist are behavioral, not construction tests.

### Structural root causes

Most findings collapse into five structural causes. Per this plan's own
"fix the workflow, not the symptom" principle, fixing these removes whole
classes of finding rather than individual symptoms.

1. **The canonical policy is dead code; the live policy is a hand-copied
   divergent string.** `lup.policy.rules` and `lup.policy.chain` have zero
   non-test importers. The hooks run only `BUNDLED_POLICY_SOURCE` in
   `policy/bundle.py`, a dependency-free reimplementation that has already
   drifted from the canonical policy. The two forms are cross-tested only for
   shell, and even that shares the `|&` bug. **Remedy: generate the bundle from
   the canonical policy (or cross-test both forms against one canonical fixture
   set); never hand-maintain two.** This is the root of findings SEC-2, SEC-3,
   SEC-4, POL-M1, POL-M2, POL-M3, POL-m2, HAR-2.

2. **The adapter layer lost its unit coverage.** ~20 adapter tests (including the
   585-line `test_sdk_interop.py`) were deleted as they tested removed surfaces —
   correct — but nothing replaced them. `ClaudeTurnToolBinder`,
   `build_claude_options`, `claude_usage`, `convert_claude_block`, and the Codex
   binder have no direct tests. This is how the one-line session-killer (BLK-1)
   shipped. The plan mandates `None→A→A→B→None` "tested identically through both
   implementations"; today it runs only against a fake binder.

3. **The template migration silently dropped 0.1 behaviors** without replacement
   or a migration-table row — several contradicting the plan non-goal "no silent
   unsupported-option dropping": inner-agent write confinement, trace logging,
   Codex MCP tools, native subagents, three Claude session defaults, and
   Claude-backend budget. See "Migration / template" below.

4. **Generated Codex artifacts are stubs, not migrated behavior.** Every skill is
   a one-line seed plus a boilerplate sentence; `AGENTS.md` is one paragraph.
   Gate B parity is met in name only.

5. **Reconciliation / backpropagation is half-built.** No code writes
   `.lup/reconcile/<id>/`; `harness reconcile` reports and exits. With
   `adopt_exact_backpropagation=False` for Claude, one manual edit to a baseline
   file wedges every generate/launch with a conflict whose only recovery
   (deleting the ownership manifest) is undocumented. No pre-commit/CI drift
   wiring exists, which the plan requires.

### Blocking issues

These must be fixed (or the milestone descoped) before the affected gate can be
claimed. `[confirmed]` marks findings verified by direct read.

| ID | Area | Location | Defect |
|---|---|---|---|
| BLK-1 | Adapters | `adapters/claude/runtime.py:83,102` | `[confirmed]` New sessions pass `session_id = uuid4().hex` (no dashes); the Claude CLI validates a dashed UUID and exits 1 — **every fresh Claude session dies on turn one**. Fix: `str(uuid4())`, then restore adapter unit coverage. |
| BLK-2 | Policy (security) | `policy/bundle.py:17-86` | `[confirmed]` Shell splitter treats only `; & && \| \|\| \n` as separators; the tokenizer groups punctuation runs, so `\|&` / `;&` become non-separator tokens and the RHS is swallowed into the safe LHS segment. `cat x \|& rm -rf ~` → allow. Present in the canonical `ShellPolicy` too. |
| BLK-3 | Policy (security) | `policy/bundle.py:35-47,60` | `[confirmed]` `echo` is read-only-allowlisted and `>` is not a separator, so `echo <payload> > <any path>` auto-allows — a generic file-write primitive bypassing the Edit/Write policy. |
| BLK-4 | Policy (security) | `policy/bundle.py:210-229` | `[confirmed]` Live bundled `decide_edit` has **no anti-pattern scan**; a ≤3-line edit adding `Any`, `# type: ignore`, or `dict[str, object]` returns allow (old hook denied). Canonical `EditPolicy` scans but is dead code. |
| BLK-5 | Migration (safety) | `adapters/claude/runtime.py:52-74,335-352`; `lup/hooks.py` | `[confirmed]` `ClaudeSessionConfig` has no `hooks` field; `build_claude_options` never sets `hooks=`/`can_use_tool`; `create_permission_hooks` has no production caller. With the old `bypassPermissions` default, the inner agent runs with **no directory write-confinement**. No migration row covers `LupAgentOptions.hooks`. |
| BLK-6 | Resolver | `.claude/workflows/commands/resolve.js` | `[confirmed]` Byte-identical to `HEAD`; still owns all phases/scheduling/prompts and grants workers branch/commit authority. Only the Codex skill points at the Python core, so the two adapters ship **two different resolver algorithms**. Violates Milestone 3/6 "thin entry, no duplicate orchestration". |
| BLK-7 | Resolver | `devtools/harness/catalog.py:264` | `[confirmed]` `ResolveSpec.worker_skill = SkillInvocation(skill="resolve")` — the worker is wired to re-invoke the resolver entry itself; no worker/implementer skill exists, so **no shipped composition can execute a real run**. |
| BLK-8 | Resolver | `resolver/core.py:257-262` | Concern commits enter the child/integration base map without a `verified` check (resume path filters correctly). A review-rejected parent leaks its changes into children and the review-master merge — violates Gate C "only verified approved work enters the review master". |

### Remaining work by area

Severity: **maj** = correctness/contract/parity defect; **min** = narrower defect
or divergence; **nit** = cosmetic/cleanup. Blocking items above are not repeated.

#### Runtime (`packages/lup/src/lup/runtime`)

- maj — `composition.py:207-210` (with `:169-170`): `finished()` unconditionally
  clears the active-turn slot, so a stale turn's `result()` clears a newer turn's
  reservation and a third `start()` is accepted (one-active-turn violation).
  Fix: `finished` must check it still owns the slot (lifecycle identity).
- maj — `composition.py:155-168`: the `except Exception → ProviderTurnError` path
  ignores `lifecycle.aborted`, so abort-during-completion (the normal
  concurrent-close path in both adapters) yields `ProviderTurnError` instead of
  `TurnAbortedError`. Recheck the aborted flag in the exception path.
- maj — `wrappers.py:352-357`: `SerializedTurn.result()`'s
  `finally: if lock.locked(): release()` releases whoever currently holds the
  lock; a second `result()` call silently releases a different turn's slot. Track
  whether *this* turn released.
- maj — `wrappers.py:339-342` vs `:526-531`: `ResilientTurn` discards
  `handle.events`/`handle.steer` on every retry/correction attempt, so with the
  template's default two correction cycles, live events stop after cycle 1 and
  `steer()` targets a dead native turn. Interrupt got `SwitchingInterrupt` for
  exactly this; events/steer need the same.
- maj — `wrappers.py:360-381,339`: non-`TurnError` exceptions escape `result()`
  (`PersistingTurn` I/O after a successful turn; retry-attempt `session.start()`
  failure), breaking the typed error surface and `TracingTurn`'s exactly-once
  contract.
- maj (test) — no test anywhere exercises `BudgetTurn`/`BudgetExceededError`
  (Milestone 8 acceptance names "exhausted budgets").
- maj (contract) — `models.py:141-147`: `TurnRequest` adds `gate` and switches to
  `FROZEN_ARBITRARY`, deviating from the plan's exact `{input, output_type}` with
  plain `frozen=True`; the `SubmissionGate` bound at `:138` is dropped as a
  cascade. Either rework (move the gate to the submission handler as the plan
  says) or amend the plan.
- min — `wrappers.py:172-177`: `TurnTimeoutError` carries no identifiers/failed-
  cycle evidence; `:169-171` a raising `interrupt()` masks the timeout.
- min — `wrappers.py:409-425`: `UsageTurn` reports nothing for failed logical
  turns (usage sink undercounts real spend).
- min — `wrappers.py:206-234,237-279`: `RecoveryTurn`/`CorrectionTurn` are dead
  code duplicating `ResilientTurn`; delete or wire.
- min — `contracts.py:91-96`: `SubmittedOutputStore.write` signature deviates
  from the plan's `write[T: BaseModel]`.
- min — `composition.py:240`: `bind_output` hard-codes
  `InMemorySubmittedOutputStore`; no seam to compose the file-backed store, so
  the cross-process persistence acceptance is unreachable via the session path.
- min — `output.py:89-90`: `record_attempt`'s `case _: return` silently drops
  validation history for any third-party `SubmittedOutputStore`.
- min — `routing.py:48-55`: `ModelRouter` is mutable where the plan says
  immutable data.
- min (test) — `test_capability_runtime.py:105-134`: the `None→A→A→B` sequence
  omits the trailing `→None` unbind assertion and passes no reflection gate on
  the A turns (plan mandates both).
- min (test) — untested: `TracingTurn` failure path, binder-failure-before-input,
  `BackgroundAgent` error/stop-mid-turn/wake-after-stop, `resume` pass-through,
  events/interrupt/steer pass-through in `DecoratingSession`/`SerializedSession`.
- nit — `models.py:112-127`: `TurnEvent` is one record with optional
  `block`/`delta` (the shape the plan bans for lifecycle events; use a union).
- nit — `models.py:171-172`: `turn_request(input, None, gate=g)` drops the gate at
  runtime (overloads guard only statically).
- nit — `wrappers.py:325` uses `assert` for control-flow narrowing; `:494` gates
  correction on `request.output_type is not None` instead of `is_output_model`.
- nit — Codex adapter tests live in the neutral runtime test module.

#### Adapters (`packages/lup/src/lup/adapters/{claude,codex}`)

- maj — `codex/app_server.py:195-217`: `read_messages` awaits a queue that process
  exit/EOF never feeds and nothing watches `sh.RunningCommand` for exit, so a
  dead codex process hangs `result()`/`interrupt()`/session-exit forever (masked
  only by an application `TimeoutConfig`).
- maj — turn errors drop partial blocks/usage on stream/decode failures
  (`claude/runtime.py:117-165`; `codex/runtime.py:130-137`), violating the
  `TurnError` "carries all available partial blocks, usage, timing" contract.
- maj — `codex/runtime.py:353-355`: the channel feeds every notification into the
  current turn and each `decode()` arm sets `self.turn_id` without a staleness
  check, so a late notification from a prior turn corrupts the new turn or
  completes its future early (`handle_server_request` checks staleness; `decode`
  doesn't).
- maj — `codex/runtime.py:325-327`: only `item/tool/call` approval requests are
  answered; `CodexSessionConfig` still accepts `approval_policy` values whose
  turns will then stall/fail. Reject unsupported approval configs at
  construction.
- maj — `packages/lup/pyproject.toml:19-31`: `sh` is imported at module level in
  the codex adapter/harness runtime but declared only at the workspace root, so
  `pip install lup[codex]` cannot import the adapter; the `codex` extra pins
  `openai-codex`, which nothing imports anymore.
- maj — `codex/native.py:168-173`: the `ask if supports_ask` branch returns
  `exit_code=0` (fail-open), the fictional-approval case Milestone 5 forbids;
  currently unreached but the ABC implementation itself violates the clause.
- min — `codex/runtime.py:267-273`: resume sends only `threadId`; model/cwd/
  sandbox/approval/instructions are silently dropped for resumed threads.
- min — `codex/runtime.py:202-215`: failed-turn branch discards the server's
  `turn.error.message`.
- min — `claude/runtime.py:87-91`: `disconnect()` nulls the client only after a
  successful `disconnect()`; a failing disconnect caches a dead client. Use
  try/finally.
- min — usage semantics diverge: Claude maps `input_tokens` (excludes cache),
  Codex maps `inputTokens` (includes cache); `per_mtok_usage_cost` then
  double-discounts Claude. Make portable `Usage.input_tokens` mean one thing.
- min — `codex/harness.py:206-213,249,254`: Codex hook artifacts use `$PLUGIN_ROOT`
  and tool names `Bash`/`web_fetch` that are unproven against the pinned binary
  (which has `CLAUDE_PLUGIN_ROOT`, `apply_patch`, `local_shell`); if wrong, hooks
  silently never fire. Capture native hook/app-server fixtures (Milestone 1
  evidence gap).
- min — `claude/native.py:150`, `codex/native.py:130`: `FetchUrl(AnyHttpUrl(url))`
  lets a malformed URL raise out of `decode()` instead of returning conservative
  evidence.
- min — Claude offers `events`/`steer`/`fork` as `None` although the SDK supports
  partial-message streaming and `fork_session`; either implement or record the
  gap as evidence (Gate D).
- min — `codex/app_server.py:145-174`: `close()` re-raises `terminate()` errors
  from the `open_session` finally, which can replace the in-flight turn error;
  collected stderr is never attached to any error.
- nit — `ClaudeDecisionRenderer` (`claude/native.py:179-186`) and
  `ModelRouter`/`ModelRoute`/matchers are unwired and untested (verification
  matrix requires route-precedence/unknown-model/custom-recipe tests).
- nit — `ClaudeTurnToolBinder` reconnects (full CLI restart + resume) on every
  turn including `None→None`.
- nit — harness renderers hardcode `.claude/plugins/lup/…` / `.codex/plugins/lup/…`
  paths while `Plugin.name` is data.
- nit — `tests/unit/codex_hooks_reference.py:9` stale docstring reference to a
  deleted module.

#### Harness / generation (`packages/lup/src/lup/harness`, `devtools/harness`)

- maj — Codex skills are stubs (`catalog.py:187-208`): one-line seed + boilerplate
  vs the full command workflows; `AGENTS.md` is one paragraph vs full CLAUDE.md.
- maj — `catalog.py:158-184`: `claude_parity_tree()` reads the live `.claude`
  files as the desired tree, so Claude generation is self-referential and the
  manifest `source_digest` (hash of `portable_harness()`) doesn't describe the
  bytes it owns. Milestone 3 "regenerate from canonical declarations" is a
  passthrough override.
- maj — no proposal writer exists: nothing writes `.lup/reconcile/<id>/`;
  `harness reconcile` (`devtools/harness/app.py:189-209`) reports and exits 1.
  With `adopt_exact_backpropagation=False`, any baseline-file edit wedges
  generate/launch with an undocumented-recovery conflict.
- maj — library-boundary violation: the fetch allowlist and protected roots are
  hardcoded in `packages/lup` (`adapters/claude/harness.py:206-225`,
  `codex/harness.py:210-215`) while `HookSet` carries only `policy_ids`;
  downstream cannot reconfigure without editing library source.
- maj — `harness/models.py:291-295`: a neutral package assembles native prefixes
  (`f"/{plugin.name}:"` / `f"${plugin.name}:"`), which the plan forbids and which
  (being dynamic) evades the static native-spelling audit.
- maj — `__pycache__` poisons the Codex plugin digest: `directory_digest`
  (`codex/harness_runtime.py:42-56`) hashes every file under the source root, so
  bytecode created by running the hook churns the digest → forced reinstall / a
  possible digest-mismatch `RuntimeError`. Exclude bytecode/caches.
- min — launchers swallow native exit codes (`app.py:384-385,442-443` exit 0 on
  `sh.ErrorReturnCode`).
- min — `app.py:423,437`: Codex launcher clobbers an exported `CODEX_HOME` when
  `--codex-home` is omitted.
- min — interactive launch never reconciles promotable/unknown changes; it fails
  identically to non-interactive and the "planned tracked diff" is path names
  only (`app.py:105-119,137-151`).
- min — `harness/process.py:31`: `LocalProcessLauncher` `_env=request.environment
  or None` replaces the whole child environment for any non-empty env (PATH-loss
  trap); it also can't serve interactive launches, so the CLI bypasses
  `ProcessLauncher` with raw `sh`.
- min — `ReconciliationMetadata.source_patch` actually stores the patch SHA-256
  (`app.py:230-232` vs `models.py:485-490`) — misnamed contract.
- min — `generation.py:20-58`: `RenderJob`/`ArtifactComposer` are dead code.
- min — `bundle.py:221`: bundled marker gate counts casefolded substring `"lup:"`
  anywhere vs the comment-aware `marker_count`; false asks on strings mentioning
  `lup:`.
- min — `reconciliation.py:155-173`: `FilesystemCurrentTreeReader.read` decodes
  managed files as UTF-8 with no error handling — one stray byte crashes
  generation with a traceback instead of a typed conflict.
- min — `reconciliation.py:53-77`: `source_patch_preimages` hand-parses patch
  fragments (`--- /dev/null` false-match on a `-- /dev/null` content line;
  `new_candidate` never reset) — fragile.
- min — executable-bit drift is invisible: ownership compares content only, while
  the parity tree declares hook scripts executable though they are 0644 on disk,
  so modes flip on the next rewrite (`catalog.py:177-179`,
  `materialization.py:66`).
- min — bundled fetch ignores port (`bundle.py:195-207`) while canonical
  `FetchPolicy` compares scheme+host+port+path — the two disagree.
- min — the generated tree is internally incoherent: CLAUDE.md § Permission Hooks
  still documents `auto_allow_*.py` as active, and those unwired,
  pydantic-importing (non-hermetic) scripts still ship next to the dispatcher.
- min — no pre-commit or CI drift wiring exists anywhere, and no test asserts the
  repo is drift-clean; the plan requires both.
- min — `app.py:277-280`: `ConsoleQuestionBroker` raises `IndexError` for a
  question with no choices and no recommendation.
- min — `catalog.py:168-171`: `claude_parity_tree` raises a bare
  `FileNotFoundError` during `check` when a baseline file is missing (a traceback
  for downstream repos that pruned commands).
- nit — proposal computed twice per generate (`app.py:107` + `generate.py:189`);
  double-dot semantic ids (`claude-baseline..claude/CLAUDE.md`);
  `generator_version` hardcoded `"0.2.0"` (`generate.py:197`); Codex agent TOML
  assembled by string concatenation (`codex/harness.py:104-113`); `argument_text`
  duplicated per adapter; dict-as-set literals in `bundle.py:115,135`;
  `Skill.native_only`/`Agent.native_only` never consumed; the "every intentional
  difference is recorded" ledger exists only as prose in `docs/harness.md`.

#### Policy / codescan (`packages/lup/src/lup/policy`, `codescan`)

- maj — POL-M1: resolve-editor role autonomy is gone from the live policy; the
  generated dispatchers (`.claude/…/scripts/policy.py:12-37`) never read
  `agent_type` and the bundled `decide_edit` has no resolve-editor branch. Breaks
  the `/lup:resolve` worker; new-devtools-module detection is likewise dropped.
- maj — POL-M2: curated shell allowlist entries dropped — `gh (pr|issue) …` and
  `uv run <x> --help` now `ask` (parity regression, read-only friction).
- maj — POL-M3: canonical vs bundled fetch diverge (canonical compares
  scheme+host+port+path; bundled checks host+scheme only) and are never
  cross-tested; only the canonical form is tested.
- min — POL-m1: `capabilities.py:188-203,299`: `abc-capability` counts each
  `@overload` stub, so an abstract method with two overloads + the definition
  counts as 3 and can falsely trip the 4-method rule. Dedupe by name before
  counting. (Latent — no repo ABC uses overloaded abstract methods.)
- min — POL-m2: marker-count method diverges (`markers.py` regex requiring a
  comment prefix vs bundled bare-substring `count("lup:")`).
- min — POL-m3: canonical `EditPolicy` scans anti-patterns per isolated line
  (`rules.py:349-352`), discarding `PythonContext`, so a line inside a
  triple-quoted string could false-deny (latent — path unwired).
- nit — `rules.py:115` dead/typo substitution marker; `CodexDecisionRenderer`
  fail-open `ask` branch (unreached); `OrderedPolicyChain.decide`
  (`chain.py:18-32`) has no guard against a member policy raising (the
  "exception cannot fail open" guarantee rests on each boundary's try/except).

#### Resolver (`packages/lup/src/lup/resolver`)

- maj — `core.py:96-127`: `resume()` sets `self.state` only via `persist()`, so a
  hard-killed run at phase LEASES/WORKERS/DEPENDENCY_BASES/REVIEW reaches the
  batch loop with `state is None` and double-faults in `persist_failure`. Only
  FAILED-marked states resume; the "retry resumes from the last atomic phase"
  ledger guarantee is unachievable for the crash scenarios resume exists for.
- maj — `orchestrator.py:168-187`, `core.py:570-581`: multi-way merges use a
  single octopus `git merge`, which aborts on any conflict, so the semantic
  merger can never run for ≥2 conflicting concerns — exactly the "parallel
  concerns pass alone but fail together" case the plan mitigates.
- maj — lease/scope enforcement is prompt-deep: `WritableRootLeases.assert_path`
  has no production caller; all worker/merge sessions are built once with
  `cwd=project_root()` (`app.py:306-310`), so parallel workers share the user's
  checkout as their writable area; `validate_and_commit` runs only
  `git diff --check` and never cross-checks `files_changed`/`swept_beyond_scope`;
  nothing structurally prevents a worker committing. Gate C's "parallel nodes
  never share writable roots", "workers can't commit", "diffs validated" are
  unenforced.
- maj — no per-concern persisted state machine: there is no per-concern status
  field, so the ledger transitions (`discovered → … → cleaned|retained`) are
  unrepresented; stale-base rebuild, lease-loss handling, and restart
  verification of branches/commits/worktrees/leases are absent (`release()` is
  dead code; leases are never released). `docs/resolver.md:10-11` overclaims this
  verification exists.
- maj — `core.py:685`: `record_human_acceptance` has no caller; the only CLI
  prints the manifest and exits, so phase 11 (human acceptance, cleanup/retained
  records) is unreachable and `CLEANUP` is never assigned.
- maj — no inter-process exclusivity: leases/state are plain JSON with no
  O_EXCL/lockfile, so two `resume()` calls on the same run-id both run workers
  concurrently in the same worktrees.
- maj — `app.py:270-284` vs `core.py:537-541`: `ConsoleQuestionBroker` accepts
  free text but `ask` raises `ResolverInvariantError` for any answer not in
  `question.choices`, so a typo kills the run (and the prompt blocks the event
  loop, stalling parallel workers).
- maj — `catalog.py:265`: `review_skill` renders the `review` skill ("Review a
  session trace for workflow quality") but the resolver uses it to judge a
  concern diff against acceptance criteria — wrong capability.
- maj — `dag.py:73-99`: `approved()` raises when an approved concern has an
  unapproved ancestor; the ledger prescribes marking the child `ineligible`, not
  aborting the whole run.
- min — `core.py:188-192,562`, `app.py:318`: concern ids `integration`/`review`
  collide with reserved lease/branch names (`KeyError`/worktree-add failure); not
  validated.
- min — `app.py:319`: `verification_commands=[]` in the only composition root, so
  combined verification (phase 10) is vacuously green.
- min — `core.py:308-338`, `orchestrator.py:189-215`: semantic join is not
  idempotent on resume (re-running yields "Already up to date" then an empty-
  commit `RuntimeError`).
- min — `orchestrator.py:118-129`: a no-change worker round fails `git commit` →
  invalid diff → guaranteed revision exhaustion; legitimate "no change needed"
  concerns can never verify.
- min — `core.py:274`: only `failures[0]` from a parallel batch is persisted;
  sibling failures dropped.
- min — `core.py:737-746`: the manifest reports `config.integration_branch`, not
  the persisted `IntegrationRecord.branch`; `resume()` never checks config
  consistency against the persisted run.
- min — `state.py:17,64-78`: phase guard is monotonic-only, so forward jumps
  (INVENTORY → ACCEPTANCE) are accepted — "never skips validation" is not
  schema-enforced; the `integration/` projection dir is never written; the join
  commit skips even `git diff --check`.
- min — lease worktrees are nested under the checkout (`.lup/…/agents/<id>`)
  rather than siblings (contra CLAUDE.md), sharing `agents/` with round JSON.
- min — `.codex/…/skills/resolve/SKILL.md` names no concrete command; an agent
  must guess the `harness resolve` invocation.
- nit — `AnswerBatch` permits duplicate `question_id`s; `Concern.id` has no
  min-length (empty id → invalid branch/lease root); one half-construction test.

#### Migration / template (`packages/lup/src/lup/__init__.py`, `src/lup_template`, docs)

- maj — three Claude session defaults silently changed: unset `permission_mode`
  no longer resolves to `bypassPermissions`, unset `max_thinking_tokens` no
  longer maps to the API max, and the `claude_code` preset harness prompt is
  gone; `agent/config.py:166-176,188-195` still document the old semantics.
- maj — `agent/core.py:224-233`: `AGENT_MAX_BUDGET_USD` now raises on the Claude
  backend (demands Codex pricing vars) though CLAUDE.md/.env still advertise it;
  `cost_usd` is `None` on Claude runs, emptying feedback cost rollups.
- maj — Codex sessions lost every MCP tool except `submit_output` (no
  review/sandbox/reflection); not listed under the doc's "explicit release gaps".
- maj — persistent mode is inverted from its own help text: realtime tools are
  wired only in the claude-only branch, so a codex/openai persistent session has
  no sleep/reply tools; `run_persistent_agent` also doesn't pass the file-backed
  gate to `run_relay_session`.
- maj — subagents are orphaned: `get_subagent_specs()` feeds only
  `inspect_agent`; `create_run_subagent_tool` has no production caller though
  `agent/subagents.py` claims the application injects a recipe. No migration row
  for `LupAgentOptions.subagents`.
- maj — trace logging is unwired: no `TracingConfig`/`DisplayConfig`/
  `PersistenceConfig` is passed, so `lup run` writes nothing under
  `notes/traces/…`, `trace list/show` is empty for all 0.2 sessions, and live
  block display is gone — the feedback loop is starved. README/CLAUDE.md still
  state every session writes traces.
- maj — silent unsupported-option dropping at the app boundary
  (`core.py:152-178`): on `AGENT_SDK=codex`, `permission_mode`/`max_turns`/
  `max_thinking_tokens` are silently ignored though `.env` documents they raise —
  violates the plan non-goal.
- maj — false evidence citation: `docs/native-capabilities.md:14` cites Claude
  SDK message fixtures in tests that contain none; `convert_claude_block`,
  `claude_usage`, `per_mtok_usage_cost` are untested (deleted `test_type_conversion.py`
  / `test_usage.py` coverage did not move). The Codex side is genuinely covered.
- min — `TEMPLATE_CLAUDE.md:375,722` still instructs downstream repos to use the
  removed `lup-devtools claude` launcher (this file is copied by `/lup:init`).
- min — `.claude/CLAUDE.md:18` keeps the stale security-envelope claim and refers
  to a "README § Backend support" heading that no longer exists.
- min — dead references: `devtools/usage/__init__.py`, `devtools/agent/__init__.py`,
  `agent/toolsets.py:12-13,30-33` (`core.build_session_options`, Codex serve-tools),
  `tests/unit/test_toolsets.py:9`, `agent/tools/reflect.py:20-27`.
- min — `lup/workspace/output.py:1-35` docstring describes the removed engine
  `output_format`/`output_schema` path and calls itself "the single finalization
  mechanism"; two `submit_output` implementations now coexist, one dead.
- min — deterministic sandbox cleanup lost: `core.py:441-454` never stops the
  `Sandbox`, leaving containers to a future run's orphan sweep.
- min — `core.py:136`: notes dirs dropped from `add_dirs` (only
  `settings.extra_dirs`), so with `AGENT_NOTES_PATH` outside cwd the agent loses
  read access to its own workspace.
- min — `build_session_sandbox` (`core.py:441`) has no return type annotation;
  the serve-tools / `SessionContext` env-relay machinery is production-dead.
- nit — `EngineCapabilities` (`devtools/agent/capabilities.py:20`) echoes banned
  vocabulary; the `capabilities` table renders without column separation; Codex
  `effort` is passed unvalidated; `src/lup_template/devtools/claude/` lingers as
  an empty stale-bytecode dir.

### Recommended remediation sequence

Ordered by risk and dependency. Steps 1–5 are the gate-blockers; 6–7 are the
quality/consistency tail.

1. **Security (Gate F/B):** fix BLK-2/BLK-3/BLK-4 in the policy and make the
   bundled runtime a *generated artifact of the canonical policy*, cross-tested
   against one canonical fixture set (root cause 1). Restore resolve-editor
   autonomy (POL-M1) and the dropped allowlist entries (POL-M2) in the canonical
   source so the fix propagates.
2. **Inner-agent confinement (Gate E, safety):** restore BLK-5 — add a `hooks`
   seam to `ClaudeSessionConfig`/`build_claude_options` and wire
   `create_permission_hooks`; re-confirm the default permission mode.
3. **The one-liner + adapter tests (Gate D):** fix BLK-1 (`str(uuid4())`) and
   restore adapter unit coverage (root cause 2) so it — and the partial-evidence
   contract violations — cannot recur; add the `None→A→A→B→None` and
   exhausted-budget tests the plan mandates.
4. **Resolver (Gate C):** either finish migrating the Claude entry to the Python
   core (BLK-6), fix the worker-skill wiring (BLK-7) and the unverified-commit
   leak (BLK-8), and make lease/commit-authority structural rather than
   prompt-deep — or explicitly descope the resolver milestone from this release
   with a recorded decision.
5. **Migration honesty (Gate E):** re-wire trace logging, Codex tools, budget,
   and subagents, or add explicit "release gap" entries; the plan forbids silent
   drops (root cause 3).
6. **Codex parity (Gate B):** generate real skill/agent bodies (root cause 4), or
   mark Codex parity evidence-backed-incomplete.
7. **Reconciliation + drift (Gate B):** implement the proposal writer and the
   pre-commit/CI drift wiring (root cause 5); then work the per-area min/nit
   tails and remove the dead code (`RecoveryTurn`/`CorrectionTurn`, `RenderJob`,
   unwired renderers/routers, stale docstrings).
