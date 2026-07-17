# Typed content and policy-kernel consolidation plan

## Status and intent

This is a follow-up plan to `plan.md`. The 0.2 capability-composition overhaul
is complete and its completion review stands; nothing here reopens it. This
plan removes the two places where the repository's "one typed source, generated
everywhere" story is still false, closes the untested native seams that
produced every real shipped failure on the 0.2 branch, and brings the
documentation up to the standard `plan.md` itself set. Written on 2026-07-16
against baseline commit `16aa618` and implemented across 2026-07-16 and
2026-07-17. The implementation explicitly accepts
reviewed renderer-output changes instead of preserving provider-byte parity;
deterministic regeneration and clean ownership drift are the maintained gates.

The four motivating findings below describe that baseline, not the completed
tree:

1. **The canonical prose store is unauthorable.** The 28 commands, five
   agents, and guidance documents live as base64 blobs in
   `src/lup_template/devtools/harness/native_catalog.py` (4,522 lines). No
   command regenerates that file. The only backpropagation importer accepts
   description-only frontmatter changes with byte-identical bodies
   (`devtools/harness/importer.py`); every body edit is an explicit conflict.
   New prose enters through a name-keyed `if seed.name == ...` chain in
   `devtools/harness/catalog.py` `skill()`. The typed prompt pipeline the
   architecture intended (`PromptDocument` parts rendered per adapter) exists
   and works — it currently feeds only the Codex tree, while the Claude tree
   is reproduced from locked bytes.
2. **The policy control flow exists twice.** The canonical policies in
   `lup/policy/rules.py` are Pydantic-typed and cannot be imported by the
   hermetic hook runtime, so `lup/policy/bundle.py` carries a ~350-line
   hand-written parallel (`BUNDLED_POLICY_SOURCE`). Its data tables are
   compiled from canonical objects and two context functions are embedded via
   `inspect.getsource`, but the shell/fetch/edit logic is written twice and
   kept aligned only by the shared fixture suite. The 0.2 security blockers
   (BLK-2/3/4) were exactly this divergence class.
3. **The native boundary is undertested and asymmetric.** The deterministic
   suite never executes the real `claude` or `codex` binaries. All three real
   failures shipped on the 0.2 branch lived in that gap: the fresh-session
   UUID format, the pseudo-TTY pager capture, and the Codex config-hook
   discovery that quarantined the generated inner-agent hook layer
   (`tests/unit/codex_hooks_reference.py`). The live lane (11 opt-in tests)
   has no schedule, and the behavior of a blocked `apply_patch` hook under the
   Codex CLI plugin is pinned by no test at all.
4. **Documentation is accurate but far below the plan's own deliverables
   bar.** ~300 lines across `docs/` for a system this size; no adopter guide,
   no runnable examples, no rule reference, summary bullets instead of
   decision records.

## Completion record

| Workstream | Result | Maintained evidence |
|---|---|---|
| K — policy kernel | Complete | Canonical and assembled fixture batteries, isolated-interpreter execution, import boundaries, and generated-tree drift |
| T — typed content | Complete | Declaration inventory, both renderers, native compilation, source/base64 audit, and the one-time renderer migration audit |
| N — native boundary | Complete in the tree | Full scheduled integration lane, strict version drift, and four real-CLI smokes; a release still requires two consecutive green `native` jobs |
| D — documentation | Complete | Adopter walkthroughs, runnable examples, generated rule reference, contributor guide, evidence ledger, and decision records |

The external two-run release observation is deliberately not claimed by a
source commit. A skipped credentials-gated job does not count as a green run;
release evidence consists of two consecutive scheduled workflow runs whose
`native` job completed successfully with no evidence drift.

## Goals

- One typed Python declaration per skill, agent, and guidance document,
  readable as prose, rendered to every native tree through the existing
  renderer seams. Zero base64 in source.
- One policy control-flow implementation executed three ways: canonical
  Pydantic policies, Claude plugin runtime, Codex plugin runtime.
- A scheduled live lane that exercises each historical native-failure class
  against the real binaries, plus a versioned trigger for evidence re-probes.
- Documentation matching the deliverables list in `plan.md`.
- Deterministic generated behavior throughout: every step leaves
  `lup-devtools harness check all` clean after committing reviewed renderer
  output changes.

## Non-goals and invariants

- **No backend matching, anywhere.** Neither content declarations nor the
  policy kernel may branch on an engine identifier. Engine differences are
  expressed as semantic typed parts rendered by whichever adapter renderer is
  supplied, and as semantic primitives computed by whichever dispatcher
  decoded them. Dispatch on typed variants is fine; dispatch on a backend name
  is forbidden. The kernel and the content package join the existing
  native-spelling audit scope.
- **No new capability ABCs.** Everything composes existing seams
  (`ArtifactRenderer`, `SkillInvocationRenderer`, `DecisionPolicy`, tree
  validators). The capability ledger in `plan.md` stays closed.
- No breaking release: version stays 0.2.x; public runtime contracts, the
  resolver, adapters, and workspace/telemetry subsystems are untouched.
- Registered downstream repositories are out of scope.
- The two user-deferred review notes (`TODO.md`, `agent/config.py`) stay.

## Workstream K — one policy kernel

Target: delete `BUNDLED_POLICY_SOURCE`; the hook runtime becomes a verbatim
copy of a canonical module.

1. **Create `packages/lup/src/lup/policy/kernel.py`** — the bottom of the
   dependency graph. Imports restricted to a pinned stdlib allowlist
   (`ast`, `shlex`, `re`, `tokenize`, `io`, `urllib.parse`, `posixpath`). No
   pydantic, no other `lup` modules. Contents:
   - `KernelDecision`: a plain effect/reason class. This is a deliberate
     type-erasure boundary (the same argument `plan.md` accepts for
     `SubmittedOutputStore.write`); it carries a typed suppression with a
     reason, and `rules.py` wraps it back into the Pydantic `Decision`.
   - Shell: the punctuation-run tokenizer and `decide_shell`, including the
     curated allowlist conditions — logic lives here once.
   - Fetch: `decide_fetch(url, allowed, denied)` over primitive scope rows
     (scheme, host, port, path prefix). The kernel owns matching; callers own
     configuration.
   - Edit: `decide_edit` plus the context primitives — `docstring_lines`,
     new `string_literal_lines` (tokenize-based),
     `empty_collection_exempt_lines`, and comment-token marker counting.
     String-literal context and token-aware markers are what let Workstream T
     store prose containing anti-pattern examples and marker examples inside
     Python strings without tripping either gate, on both engines, from one
     implementation.
   - **Role autonomy arrives as a boolean.** The `RESOLVE_EDITOR_AGENTS`
     native-name set moves out of shared policy; each generated dispatcher
     maps its own payload's agent identity to `autonomous=True/False` before
     calling the kernel. Native spellings stay at the native boundary.
2. **Rewire the canonical layer.** `FetchPolicy`/`ShellPolicy`/`EditPolicy`
   keep their Pydantic configs and the `DecisionPolicy` contract; bodies
   become model-to-primitive conversion, kernel call, `Decision` wrap.
   `codescan.markers.marker_count` and `codescan.antipatterns.audit_text`
   delegate to the same kernel primitives so canonical scanning and hook
   scanning share one matcher. The Pydantic anti-pattern rules compile once to
   primitive rows (today's `bundled_antipattern_rows`, relocated).
3. **Make the bundle an assembler.** The generated runtime tree becomes two
   digest-tracked files per plugin: `hooks/runtime/kernel.py` — a verbatim
   file copy of the canonical kernel (file copy over `getsource` to preserve
   line numbers in hook tracebacks) — and `hooks/runtime/policy_data.py` —
   generated rows plus the `HookSet`-injected fetch scopes, protected roots,
   and autonomous-agent identities. Dispatcher generation keeps its current
   per-adapter ownership and templates; only the imports change.
4. **Enforce hermeticity twice.** Statically: a `kernel-imports` rule in
   `lup.codescan.boundaries` pins the import allowlist, and the kernel joins
   the native-spelling audit (no engine identifiers, tool names, or agent
   strings). Dynamically: a test copies the runtime files to a temporary
   directory and runs the policy fixture battery under `python3 -I -S` in a
   subprocess, pinning the declared interpreter floor for hooks.
5. **Keep the fixture suite as the regression net.** The shared tables in
   `tests/unit/test_semantic_policy.py` continue to run against canonical and
   assembled forms — after this change they catch assembler and data
   regressions rather than logic divergence. Engine byte-identity and repo
   drift tests in `tests/unit/test_harness_compilation.py` are unchanged.
6. **Delete at the end:** the `BUNDLED_POLICY_SOURCE` literal, the duplicated
   runtime decision functions, the dead `SHELL_SEPARATORS` constant, and the
   agent-name set from shared code.

Acceptance: all existing policy fixtures pass unchanged on both forms; the
bare-interpreter subprocess test passes; `harness check all` is clean; a
demonstration rule change (made once on a scratch branch) touches exactly one
implementation file plus fixtures.

## Workstream T — typed canonical content

Target: each command, agent, and guidance document is one readable typed
declaration; both native trees render from it; the base64 catalog and the
parity shim are deleted.

1. **Add exactly one prompt part: `ArgumentsRef`.** A semantic marker for
   "the invocation's arguments belong here". The Claude renderer spells it
   `$ARGUMENTS`; the Codex renderer spells its current phrase. This replaces
   the lossy rewrite in `portable_prompt` (which today turns `$ARGUMENTS`
   into Codex-phrased text, workable only because the Claude tree bypasses
   the typed path) and replaces argument sniffing with explicit declarations.
   `ResolverEntry` is the precedent: one typed part, two native spellings, no
   engine branch. Per existing validation rules, a renderer that cannot
   represent a part fails with the semantic object ID.
2. **Create `src/lup_template/devtools/harness/content/`** — one module per
   skill (30), one per agent (5), plus `guidance.py`, `patterns.py`, and
   `template_claude.py`. Each module exposes one frozen declaration built from
   the existing `Skill`/`Agent`/`PromptDocument` models, prose in
   triple-quoted strings, semantics in parts:

   ```python
   SKILL = Skill(
       id="skill.commit",
       name="commit",
       description="Create well-scoped atomic commits",
       arguments=[Argument(name="arguments", description="...")],
       prompt=PromptDocument(
           parts=[
               TextPart(text="""..."""),
               SkillInvocation(plugin="lup", skill="rebase"),
               ArgumentsRef(),
               TextPart(text="""..."""),
           ]
       ),
   )
   ```

   `catalog.py` aggregates through an explicit import list (no barrel,
   typo-safe under pyright). The `SkillSeed`/`BASELINE_SKILLS` rows, the
   name-keyed instruction chain in `skill()`, and
   `COMMAND_FRONTMATTER_OVERRIDES` all dissolve into the modules. Non-prose
   baseline files stop being catalog bytes: manifests and settings render
   from the existing typed models (as the Codex tree's already do), and
   `file_suggest.sh` becomes a plain committed asset file. Nothing stays
   base64.
3. **Write the one-off decompiler** (a `tmp/` script): for each catalog
   entry, split frontmatter with the existing parser, parse the body with an
   upgraded `portable_prompt` (emitting `ArgumentsRef`, keeping the
   skill-invocation lifting), and emit the content module through a
   deterministic Python-literal writer. Its output is committed and
   human-reviewed once; the tool is then deleted along with the string
   scanning it inherited.
4. **Build the Claude prompt renderer** — the missing inverse:
   `PromptDocument` to native command Markdown with frontmatter, `/lup:`
   invocation spellings, and `$ARGUMENTS`. Review the rendered native diffs,
   flip the Claude desired tree from the catalog reader to rendered content,
   and regenerate both ownership-tracked trees. Clean deterministic drift is
   the gate; byte equality with the retired encoded catalog is not.
5. **Then delete:** `native_catalog.py`, `baseline_content`, the parity
   reader path, and the description-only importer (`native_overrides.py`
   merges into the modules). Reconciliation stays conflict-explicit for
   native body edits in the interim; a typed importer that proposes patches
   against content modules is recorded as follow-up work, not part of this
   plan's gate.
6. **Scanner compatibility comes from Workstream K.** Prose containing
   anti-pattern examples or marker examples sits inside string literals; with
   kernel string-literal context and comment-token marker counting, neither
   the anti-pattern denial nor the marker-count ask fires on content modules.
   If T ever needs to land a module before K, the sanctioned interim is a
   file-level typed suppression in that module's first ten lines.

Acceptance: generated trees are deterministic and pass the drift check; the
one-time native migration differences are classified in
`docs/typed-content-migration-audit.md`; zero base64 remains under `src/`; a
prose edit to a command is a reviewable string diff in one module; `dev check`,
the marker gate, and the anti-pattern gate all pass over the content package.

## Workstream N — native-boundary lane

1. **A scheduled `native-nightly` workflow**: `pytest -m integration` plus
   `lup-devtools harness doctor all`, with live tests gated on secrets presence
   and cheap models (the parity test already uses Haiku and gpt-5.5). The
   strict doctor may fail on version drift without suppressing the live probes;
   a completed failing native job remains visible and release-blocking.
2. **Four new live smokes, one per historical failure class:**
   - a fresh Claude session completing one turn (the session-id class);
   - a miniature resolver run on a throwaway fixture repository (the
     pseudo-TTY/pager class);
   - a Codex `thread/start` carrying a dynamic tool (the schema-drift class);
   - a real Codex CLI session with the Lup plugin active attempting an
     `apply_patch` — this pins the currently-unknown behavior of a blocked
     edit hook (native approval prompt versus hard failure) and decides
     whether the Codex edit story needs design work or only documentation.
     The observed outcome is recorded in `docs/native-capabilities.md`
     either way.
3. **Version-drift trigger in doctor**: compare installed CLI/SDK versions
   against the evidence ledger; warn locally and exit nonzero in the nightly
   when installed is newer, so evidence re-probes have a trigger instead of a
   habit.

Implementation acceptance: the Codex edit-path evidence row exists; doctor
flags a deliberately stale ledger version in a test; the workflow runs the
full integration marker and still runs it when strict evidence fails. Release
acceptance: two consecutive scheduled runs have successful, non-skipped
`native` jobs and no version drift.

## Workstream D — documentation

Written last, against the end state:

- an adopter guide: add a skill (write a content module), change the fetch
  allowlist (edit `HookSet`), and what a reconciliation conflict means plus
  the `apply-reconciliation` walkthrough;
- a runnable `examples/` directory for runtime composition (one-shot `query`,
  the wrapper stack, background agent, profile transform, a route);
- a Lup-rule reference generated from the rule objects (ids, messages,
  examples) by a devtools command, so it cannot drift;
- decision records replacing the summary bullets in
  `docs/dev-tooling-decisions.md`: catalog retirement, the kernel, the
  hermeticity floor, and the Codex edit-path finding from Workstream N.

Acceptance: every deliverable named in `plan.md`'s documentation section
exists as more than a summary, and the adopter guide's three walkthroughs
each run as written.

## Implementation and release sequencing

| Order | Work | Gate to proceed |
|---|---|---|
| 1 | N1–N3 minus the edit-path smoke | workflow and drift fixtures pass |
| 2 | K (kernel, rewire, assembler, enforcement) | fixtures + hermetic subprocess + one-file rule-change proof |
| 3 | T (part, content modules, renderer, flip, deletions) | classified native migration audit, then clean deterministic drift |
| 4 | N's Codex edit-path smoke | evidence row recorded |
| 5 | D | walkthroughs run as written |
| 6 | Release observation | two consecutive green, non-skipped native jobs with no evidence drift |

The implementation landed as atomic commits in the `refactor-sdk-2` feature
worktree. The two-run native observation is independent of K and T development;
it gates a release cut rather than unrelated source work.

## Deletions ledger

The point of the plan is what becomes deletable:

| Deleted | Replaced by |
|---|---|
| `native_catalog.py` (4,522 lines of base64) | `devtools/harness/content/` typed modules |
| `claude_parity_tree` catalog-byte path | rendered content through the Claude renderers |
| `BUNDLED_POLICY_SOURCE` (~350-line parallel implementation) | verbatim kernel copy + generated data module |
| `SkillSeed` rows and the `skill()` name chain | per-module declarations |
| `COMMAND_FRONTMATTER_OVERRIDES` + description-only importer | descriptions in content modules |
| `portable_prompt` string scanning | the retired decompiler (one-off) |
| `RESOLVE_EDITOR_AGENTS` in shared policy | dispatcher-supplied autonomy flag |
| `SHELL_SEPARATORS` dead constant | already-live punctuation-run tokenizer |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Render-from-content changes native formatting in subtle ways | Review the source and native diffs together; deterministic generation and ownership drift tests guard both trees on every commit thereafter |
| The kernel erodes repository typing conventions | One module, pinned import allowlist, typed suppressions with reasons, a decision record; Pydantic wraps it everywhere above |
| Kernel copy goes stale in generated plugins | File-copy assembly is exercised by the drift check and the engine byte-identity test; the fixture suite runs against the assembled form |
| Prose-in-Python escaping (quotes, backslashes) | Deterministic literal writer picks quoting per block; the 35-module review pass is explicitly budgeted |
| Content prose trips edit gates during later maintenance | Kernel string-literal context and comment-token markers (K lands first); file-level typed suppression as the sanctioned fallback |
| Nightly flakiness or spend | Cheap models and secrets-gated live tests; failures stay visible, while only release cuts require two consecutive green native jobs |
| Codex blocked-edit probe returns "hard failure" | That is a finding, not a plan failure: record it as an evidence-backed gap and open the follow-up design; the plan's gate is the recorded row |
| Adding parts becomes a habit | Only `ArgumentsRef` is in scope; any further part requires the same ledger-and-cohesion path `plan.md` mandates |
