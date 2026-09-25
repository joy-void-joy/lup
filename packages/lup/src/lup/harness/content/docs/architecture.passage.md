# Capability-composition architecture

Lup uses one independently constructible capability per ABC. A capability has
one to three cohesive abstract behavior methods, no concrete behavior or
properties, inherits only `ABC` plus typing generics, and is never combined
with another capability through multiple inheritance. Small callbacks remain
typed callables. `lup.harness.codescan.capabilities` enforces the mechanical shape
across resolved project imports with the audited `abc-capability` rule.

Rich behavior is explicit composition. Each provider's session and turn are
plain classes holding exactly what that provider supports: `CodexTurn` has
`steer`, and `ClaudeTurn` has no such method rather than one set to `None`.
A `ClaudeSession` or `CodexSession` is composed over a `SessionEngine`, a
`ConversationRecord`, and a `ForkSession`, and its turns start themselves
through the engine. Code naming no provider holds the structural `Agent`,
`Conversation`, and `Turn` protocols of `lup.sessions.surface`, which ask
only for what both providers answer.

The runtime sequence is:

1. an application declares a `Claude` or `Codex` agent, a frozen and
   validated model whose construction loads no SDK;
2. immutable profile and endpoint transforms rewrite that declaration;
3. `agent.open()` loads the adapter's runtime, owns its resources, and wraps the
   session in the agent's declared `SessionLayers`;
4. `session.ask(prompt, Model)` returns a turn that has not started; the first
   await, iteration, `events()`, `live()`, or `interrupt()` starts it once,
   which creates a fresh output store, finishes tool binding, and waits for
   native turn acknowledgement;
5. awaiting the turn returns one strict `TurnResult[T]` or raises a typed
   error carrying all available blocks, usage, duration, identifiers, and
   validation history.

`agent.ask(prompt, Model)` is steps 3 to 5 at once: open, one turn, and close
however that turn ended.

Timeout, budget, recovery, correction, serialization, observation, and
persistence are concrete decorators around these boundaries, declared on the
agent as its `layers` rather than stacked around it by hand. Completed replay
is derived from `TurnResult.blocks`; only a native feed implements
`EventStream`.

## The adapter seam

Shared runtime, harness, policy, and resolver packages never import concrete
adapters or assemble provider wire names. Native config, hook payloads, command
spellings, manifests, and schemas remain inside adapter packages and concrete
CLI composition roots. A third adapter can implement the contracts without
editing a shared registry.

The same boundary applies to generation. Shared inspection and materialization
consume an injected immutable recipe; adapter selection is confined to the CLI
composition root. The generic path never compares a target name or provider
value. [harness.md](harness.md) walks that pipeline, and
[platform-differentiation.md](platform-differentiation.md) records every
difference the seam admits.

## Structured output has one mechanism

Each typed turn binds `submit_output` to its Pydantic schema and a fresh
store; native structured-output modes remain off. Validation and an optional
reflection gate run before persistence. A missing submission cannot be
represented as a successful typed result.

## Agents are chosen, never inferred

Applications name the agent they declare, `Claude(...)` or `Codex(...)`, and
its `model` takes that runtime's catalog of names, a portable tier such as
`strongest`, or a `CustomModel(id=...)` that leaves the catalog on purpose, so
a misspelt id fails where it is written. Immutable `ModelRoute` values may
select configured recipes, but model names never trigger optional SDK imports
at module import time and unknown models fail closed.

## Where each component sits

The capability rules above are what let the three components stay separable:
[library.md](library.md) describes the contracts and their implementations,
[template.md](template.md) describes the application that composes them, and
[permissions.md](permissions.md) describes the one decision path that has to
hold identically inside the library and inside a generated plugin that cannot
import it.
