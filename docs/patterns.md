<!-- Generated from lup_template.devtools.harness.content.docs.patterns by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Design Patterns

The recurring *code* shapes in this repository: what each one is for, where to
read a worked instance, and the reasoning that makes it the default. How work
is delegated across *agents* is a different subject and lives in
[docs/orchestration.md](orchestration.md).

Each shape below exists to close a gap by construction rather than to remind
someone to keep two places in step. That is the thread running through all of
them, and it is stated outright in § Compiling Is Stronger Than Emitting.

---

## Declaration Plus Renderer

A declaration says *what is meant*; a renderer says *how one runtime spells
it*. Keeping them apart is what lets one document serve several runtimes.

`SkillInvocation` (`packages/lup/src/lup/harness/models.py`) names a plugin and
a skill and nothing else — no slash, no prefix, no punctuation belonging to any
runtime. `SkillInvocationRenderer` (`packages/lup/src/lup/harness/contracts.py`)
turns it into the words one runtime reads. Prose that reaches a native tree
therefore contains no platform vocabulary at any point where a human authored
it, and the `portable-content` rule enforces exactly that.

Reach for this whenever content has to exist in more than one dialect. The
alternative — writing the dialect inline and translating later — puts the
translation where nothing checks it.

## Closed By Construction

When adding a variant *must* force an update elsewhere, arrange for the
compiler to be the one that says so.

`NativeSpellings` (`packages/lup/src/lup/harness/contracts.py`) declares one
abstract method per native word a prompt can reach. A new kind of prompt part
adds an abstract method, and no runtime can be constructed without answering
it. The seam is closed by construction rather than by a reminder to edit two
renderers — which is the same reasoning as § Never Dispatch On Our Own Models
in the agent guidance, seen from the other side: there, a declining base answer
makes omission *safe*; here, an abstract member makes omission *impossible*.
Choose by whether a silent default is a correct answer.

## Typed Matcher Plus First-Match Router

To pick a behaviour from a value, route through typed matchers to an ABC and
call it — do not grow a chain of conditionals, and do not reach for a regex
where a named capability will do.

`ModelRoute` pairs a `ModelMatcher` with a factory recipe, and
`ModelRouter.resolve` takes the first route that matches
(`packages/lup/src/lup/runtime/routing.py`). `ExactModelMatcher` and
`PrefixModelMatcher` are each a few lines, and each *says what it means* —
where a regex would have encoded the same intent in punctuation that no
reader, and no type checker, can check. A new matching strategy is a new
class, not an edit to the router.

---

## Compiling Is Stronger Than Emitting

Constructing output from a typed declaration closes divergence **by
construction**. Transporting checked source and hoping a checker complains
only lets something *warn* about divergence after it exists.

The distinction decides where a guarantee lives. When one canonical
declaration is compiled into every artifact that depends on it, the artifacts
cannot disagree — there is no state in which they differ, because there is
only one statement of the fact. When each artifact is written separately and a
test compares them, they can and eventually do disagree; the test only reports
it, and only where someone remembered to look.

This is the same reasoning as the guidance that the durable fix is a
capability, not a rule. A rule coexists peacefully with the failure it warns
about. A capability removes the state the failure needs in order to exist.

Apply it when you catch yourself adding a check that two things still match:
ask instead whether one of them can be *derived* from the other. A generated
artifact, a compiled dispatcher, and a rendered document are all this move.
Where derivation genuinely is not possible, say so where the duplication is —
and then the check is the right fallback rather than the first idea.

## A Constant Should Probably Be An Overridable Default

The defect is never that a value is a constant, nor how many constants there
are. It is assuming a **non-canonical** choice with no way to state a
different one.

Sort a value by asking whether anyone could reasonably want another:

- **Canonical** — a native tool's actual name, a wire protocol's field, a
  vendor's documented event. There is one right answer and it is not ours.
  Hardcode it; a parameter here is noise that implies a choice nobody has.
- **Non-canonical** — an allowlist of shell builtins, a size ceiling, a
  retry count, a palette. These are *our* judgement, reasonable people differ,
  and a project building on this one will have its own. Make them a default
  that a caller can override, not a constant it must fork the module to change.

The tell is a downstream reader who agrees with the mechanism and disagrees
with the number. If that reader has to edit library source, the value was
declared at the wrong level. `GUIDANCE_BYTE_BUDGET`
(`packages/lup/src/lup/harness/models.py`) is a worked example of the fix: it
mirrors a real vendor default, so the number is not arbitrary — but *which*
number a given project wants is still its own call, so it is a parameter with
that default rather than a constant.
