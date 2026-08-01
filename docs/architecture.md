# Capability-composition architecture

Lup uses one independently constructible capability per ABC. A capability has
one to three cohesive abstract behavior methods, no concrete behavior or
properties, inherits only `ABC` plus typing generics, and is never combined
with another capability through multiple inheritance. Small callbacks remain
typed callables. `lup.codescan.capabilities` enforces the mechanical shape
across resolved project imports with the audited `abc-capability` rule.

An entry point is not a capability. `SessionFactory` is a concrete class over
one typed `SessionOpener` callable: opening a session is a callback, and the
class holding it is the surface applications construct and pass around, so
adapters, wrappers, and tests build `SessionFactory(opener)` rather than derive
from an ABC. Shared behavior then lives where every caller reaches it —
`SessionFactory.query(request)` runs one turn on one session, and the free
`lup.query(factory, request)` alias spells the same operation where a
composition root reads better with the factory as an argument. `ModelRouter`
is the same shape over the `ModelMatcher` capability.

Rich behavior is explicit data flow. `SessionHandle` contains a `Session` and
an optional `ForkSession`; `TurnHandle[T]` contains a `Turn[T]` and optional
live events, interrupt, and steer capabilities. These frozen Pydantic values
do not implement behavior or hide a provider. Unsupported behavior is absent.

The runtime sequence is:

1. an application builds a validated Claude or Codex config;
2. immutable profile/endpoint transforms run before factory construction,
   applied directly or through a resolver's `session_factory()`;
3. `SessionFactory.open()` owns provider resources;
4. `Session.start()` creates a fresh output store, finishes tool binding, and
   waits for native turn acknowledgement;
5. `Turn.result()` returns one strict `TurnResult[T]` or raises a typed error
   carrying all available blocks, usage, duration, identifiers, and validation
   history.

Timeout, budget, recovery, correction, serialization, observation, and
persistence are concrete decorators around these boundaries. Completed replay
is derived from `TurnResult.blocks`; only a native feed implements
`EventStream`.

Shared runtime, harness, policy, and resolver packages never import concrete
adapters or assemble provider wire names. Native config, hook payloads, command
spellings, manifests, and schemas remain inside adapter packages and concrete
CLI composition roots. A third adapter can implement the contracts without
editing a shared registry.

The same boundary applies to generation. Shared inspection and materialization
consume an injected immutable recipe; adapter selection is confined to the CLI
composition root. The generic path never compares a target name or provider
value.

## Library mechanism, application data

The library/application split runs the other way too: `packages/lup` owns
mechanism, and the application supplies the data it operates on. A library may
declare a value only when it could not have chosen otherwise — when a second
implementer with the same intent would have written the same thing, because a
language, a tool, a grammar, or one of this library's own closed enums dictates
it. A value that is a judgement is application data, and reaches the library as
an **overridable default**: shipping a default is not the defect, shipping a
choice with no parameter to replace it is. `HookSet` is the shape — a pydantic
surface the template fills with fetch scopes, protected roots, and shell-rule
extensions.

Half of this is mechanical. The audited `library-default` rule in
`lup.codescan.boundaries` requires every multi-entry data table declared under
`packages/lup/src/lup` (outside `lup/adapters`, where provider spellings are
canonical by definition) to be reachable somewhere in the library as a
caller-replaceable default — a parameter default, a pydantic field default or
factory, or the sentinel a mutable default is written as. Reachability is
computed across the whole library, so a table defaulted by a distant consumer
still passes.

The other half is not checkable and is not meant to be: whether a value is
dictated from outside the repository is a fact about curl's flags or Python's
suffixes, not about the syntax. Canonicity is therefore declared at the site
with `# lup: ignore[library-default]` and a reason naming what fixes the value.
`docs/library-boundary.md` carries the criterion in full, the classification of
every library table against it, the reverse-direction audit, and the target
layout the relocation work executes against.

Structured output has one mechanism. Each typed turn binds `submit_output` to
its Pydantic schema and fresh store; native structured-output modes remain off.
Validation and an optional reflection gate run before persistence. A missing
submission cannot be represented as a successful typed result.

Applications choose factories explicitly. Immutable `ModelRoute` values may
select configured recipes, but model names never trigger optional SDK imports
at module import time and unknown models fail closed.

## Harness generation flow

`lup-devtools harness generate|check|claude|codex` walks one pipeline from
typed Python to launched native plugins:

1. **Typed declarations** — `devtools/harness/content/` holds skill, agent,
   and guidance declarations; `devtools/harness/catalog.py` composes them
   with the application-owned `HookSet` into one canonical
   `lup.harness.models.Harness`.
2. **Renderers** — `lup.adapters.claude.harness` and
   `lup.adapters.codex.harness` implement the `ArtifactRenderer` seams from
   `lup.harness.contracts`; the compilation roots in `lup.adapters.harness`
   compose them into a complete `ArtifactTree`.
3. **Validation** — `lup.harness.validation` checks the whole rendered tree
   (path uniqueness, ordering, identifiers, normalized text) and generation
   refuses to continue on any issue.
4. **Reconciliation** — `lup.harness.ownership` records which on-disk files
   the generator owns; `lup.harness.reconciliation` classifies the current
   tree under that proof and proposes writes, proven deletions, and explicit
   conflicts. Local edits worth carrying back to canonical sources are
   persisted as reviewable patches by `lup.harness.proposals`, never applied.
5. **Materialization** — `lup.harness.materialization` re-verifies every
   preimage and applies a conflict-free proposal atomically, then the
   ownership manifest is saved.
6. **Launch** — `lup.adapters.*.harness_runtime` probes native CLI
   capabilities, and `lup.harness.process` launches the native CLI with the
   non-interactive defaults from `lup.harness.environment`.

## Permission policy flow

The generated plugins enforce permissions without importing lup, yet decide
identically to the library:

1. **Canonical sources** — the `HookSet` in `devtools/harness/catalog.py`
   (protected edit roots, allowed fetch scopes, policy ids, and the shell
   vocabulary declared in `content/shell_vocabulary.py`) plus the anti-pattern
   rule set in `lup.codescan.antipatterns`. The library supplies the shape a
   vocabulary takes (`lup.policy.shell_rules`), never the words.
2. **Library layer** — `lup.policy.rules` validates those inputs as pydantic
   surfaces and erases them into primitive rows; `lup.policy.kernel` — the
   hermetic, stdlib-only decision core — interprets those rows to reach every
   shell, fetch, and edit verdict; `lup.policy.chain` composes policies
   deny-before-ask; the
   adapters' `native` modules decode wire payloads into
   `lup.policy.models` events and render decisions back.
3. **Assembly** — `lup.policy.bundle` reads the kernel source verbatim and
   renders the erased rows as data files; `lup.policy.dispatcher` compiles
   `hooks/scripts/policy.py` from `lup.policy.assets.host` — the host-side
   half every runtime answers identically — plus one adapter-owned half and
   the `DispatcherDeclaration` whose axes it proves that half keeps; the
   adapter hook renderers emit `hooks/hooks.json` and
   `hooks/runtime/{kernel.py,policy_data.py}` under `.claude/plugins/lup/`
   and `.codex/plugins/lup/`.
4. **Equivalence** — the shared fixture suite runs the same cases through
   the library policies and the assembled runtime and requires identical
   verdicts.
