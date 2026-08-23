<!-- Generated from lup_template.devtools.harness.content.guidance by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. Deliberately rendered as .claude/CLAUDE.md under Claude Code, AGENTS.md under Codex. -->

# Lup repository guidance

Lup is a reusable framework and template for autonomous, tool-using agents. Keep library code provider-neutral and keep provider syntax in generated adapter artifacts.

## Plan at Agent Speed

Every instinct you have about how long software takes was learned from human teams, whose implementation time is scarce. Yours is not: what you would estimate as months completes in an afternoon. Your duration estimates are not cautious, they are wrong by orders of magnitude, and every practice built on them inverts.

**Never scope, defer, or reject work from a predicted duration.** Scope by content — what changes, what it touches, how it is verified. A calendar figure in a plan is noise from someone else's constraints: delete it and re-derive the plan. Prototype-first exists to protect scarce human effort, and for you the real implementation costs what the throwaway was supposed to, so build it and let review cut scope rather than pre-shrinking the attempt.

Catch the reflex in the act. "Let's start with a simple version", "too ambitious for this pass", "phase 2 can add the rest" — that is a human-scarcity practice firing on constraints you do not have. Ask what is actually expensive besides the imagined schedule.

## Agent Vocabulary

Two kinds of delegated agents look alike and must not be conflated:

- A **native subagent** ("subagent" for short) is dispatched by the harness: its delegation tool hands a focused task to a named role defined upfront, inside the main agent's session — shared trace, shared metrics.
- A **nested agent** (a *tool-subagent*) runs inside a tool call: the handler opens one independent session via `query()` and folds the result into the tool's response. The harness never sees it — to the caller it is just a tool.

Guidance that says "subagent" unqualified means the native kind. `docs/orchestration.md` carries the delegation catalog and when to reach for each; `docs/patterns.md` carries the recurring *code* shapes.

## The Gates You Will Meet

You are not expected to hold this repository's conventions in memory. Gates enforce them, and their diagnostics — which name what was caught and how to answer — are written to be read cold. What is worth knowing up front is only that they exist.

**The rule checker.** Anti-pattern, boundary, spelling, and architecture rules run on every edit and in `dev check`. A denial cites its rule id and spells the suppression where the rule admits one; one marked **refused** admits none, its replacement being right every time. `# noqa`, `# type: ignore`, and `# pyright: ignore` are forbidden shapes rather than suppressions.

**The permission policy.** Every shell command, URL scope, and edit in a batch is classified, and a denial names what tripped and the recovery. `dev policy '<command>'` answers before you spend a turn on it, and `# lup: escalate: <why>` as a command's leading line promotes a deny or ask into an approval question carrying that reason.

`# lup: escalate` is one-off. For recurring walls, **widen the protected declaration** so review approves the rule. Regenerate and reopen with `--continue` to load it at startup while keeping the conversation; it remains drift-checked next session.

**The edit budget.** A change block of at most three "real" changed lines is auto-allowed, so split large changes — imports in one edit, logic in another. A file declared human-owned surfaces every change as an approval: propose the exact edit and let the user apply it.

**The drift check.** Generated trees are regenerated, never hand-edited and never hand-merged. Take either side of a conflict, regenerate, and let the check confirm it settled.

`docs/rules.md` indexes every rule from the registry that runs, `docs/permissions.md` carries the lattice and what counts as a real changed line, and `docs/contributing.md` carries how a suppression is scoped.

Change the policy those gates enforce with $lup:hooks, which edits the canonical inputs in `lup.policy` and the `HookSet` in `devtools/harness/catalog.py`, regenerates both native plugins, and runs the shared fixture suite. Harness generation compiles one hermetic dispatcher and runtime per plugin, so never edit a generated dispatcher or runtime.

Harness settings stay project-level, in the tree the harness owns (.codex/config.toml), which holds only the native settings outside that semantic policy boundary — never user-level.

### The `# lup:` Marker Vocabulary

A `# lup:` (or `// lup:`) comment is **actionable review feedback** left in the code for the agent to address — anything whose subject is the code and belongs at the site it concerns. Three flavors carry feedback, and **deleting one is denied**: bare `# lup: <text>` is open, `# lup: solved: <text>` claims you addressed it, `# lup: defer: <text>` parks it. Two more share the namespace without being feedback and go when what they annotate does — `# lup: ignore[<rule>]` is the suppression above, and `# lup: template: <decision>` marks a customization point the scaffold leaves to whoever adopts it.

Resolve open feedback by fixing what it points at, or, for a question, by answering it definitively in the code, the docs, or a recorded user decision. Then rewrite the marker as **`# lup: solved: <the note's original words>`**, text unchanged, so the claim sits beside what it claims to fix and can be checked against what was asked; only the verify-solved pass retires one. `docs/contributing.md` carries the lifecycle, and how a customization marker reads differently in a scaffold and in a repository that adopted it (`$lup:resolve`), and `dev todos` walks the customization points still standing.

### Deferred Work

**Never create tracking files.** A `TODO.md`, backlog, or roadmap parks a decision where no workflow will surface it again — deferral by tracking file is delegation to nobody. Work not being done now lives in one of three places, chosen by what it attaches to:

- **A `# lup: defer: <text>` note**, when the work belongs to a site in this code, where `dev check` keeps it visible until somebody wakes it. A bracketed `defer[gone:<path>]` or `defer[branch:<name>]` states a gate `dev check` resolves rather than reads, failing the run the answer turns yes; any other gate stays prose, and prose stays advisory.
- **A GitHub issue**, when the tooling is misbehaving rather than the code and the repair is not one this session can make — nothing in the tree owns that, so a note would have nowhere to sit.
- **A question to the user**, when whether to defer at all is itself the open question.

`docs/contributing.md` carries what each gate wakes on, and the one exception to all three — a `tmp/` briefing, which starts a fresh session on a situation this one cannot finish, rewritten whole rather than appended to.

---

## Development Workflow

Use a **git worktree**; never commit code to `dev`. Run `uv run lup-devtools dev worktree create feat-name`, then start a session rooted at <the path it prints> and continue there — this runtime cannot move a running session, so work carried on here would land in the checkout it started from. Already running, keep working where you are and address files there by absolute path, which reaches the same branch. — creation does not move the session, so old-checkout edits miss the branch. Late relocation may persistently reject ordinary shell words anywhere in argv. `docs/contributing.md` carries the branch model, refused-word set, and merge loop.

### Merge Conflict Resolution

**Never silently drop code during conflict resolution.** Keeping both sides is safer than losing features, and a rename on one side must not swallow an addition on the other. Before completing any merge, **audit for deletions**: compare the result against both parents and verify that every removed function, parameter, or command went deliberately, not as a side effect of choosing one side.

Use `$lup:merge` for guided conflict resolution; the command carries the decision tree.

### Commit Guidelines

- **Commit before responding**, and often — frequent commits are checkpoints
- **Keep commits atomic** — if you need "and" in the message, it is two commits
- **History will be rebased**, so a message need not be perfect while developing; after rebasing, each commit should tell what changed and why

**Format:** `type(scope): description`

The type comes from the table in `docs/contributing.md`, which the commit skill renders at the moment one is being chosen.

---

## Code Conventions

Build on `lup` and pydantic. The runtime an application composes against is provider-neutral, and each provider's SDK is one adapter's dependency behind an extra rather than a framework the application talks to: no module under `src/lup_template/` imports one, and `seam-boundary` keeps adapter imports to the composition roots that name them. `docs/conventions.md` names each library and puts each typed form beside the raw dict it replaces. Prefer an existing PyPI library to raw HTTP or a rebuilt wheel.

**Model selection.** Default to the **strongest** tier everywhere — main agent, subagents, reviewers, background agents. This runs on a subscription where the best model is the point: reach for **balanced** only when latency or cost provably dominates quality, and **fast** almost never. A role that warrants less declares that tier with a reason, and declarations state a tier, not a model id.

**Error handling.** A `@lup_tool` handler takes a validated model and returns one; raise `ToolError` to send a recoverable failure back as an MCP error saying what to do about it — the `is_error` envelope and the input-validation reply are the decorator's. Elsewhere raise for unrecoverable errors, wrap transient ones in `with_retry`, validate inputs early, and never swallow one silently. A catch-all `except Exception` is fine at a boundary that logs, handles, or re-raises — a task loop, a subagent delegation — which is why no rule refuses one.

**Placement, in this repository.** Reusable utilities belong in `packages/lup/`; what only this application needs belongs in `src/lup_template/`. If logic already exists in `lup`, import it rather than copying it. Deciding a module belongs on the other side is one line of judgement and a hundred of consequence, which is where the judgement usually gets abandoned — so the consequence is a command: `dev relocate old.module=new.module` repoints every import and reports the mentions it left for you.

### Design Principles

A gate catches a violation once it is written. These change what gets written, so they are here rather than in the index.

- **Compiling is stronger than emitting** — build an artifact from a typed declaration and it cannot diverge. Tempted to check that two things still match, ask whether one can be derived from the other (`docs/patterns.md`).
- **Structured data, not strings** — reaching for `re`, `.replace()`, `.split()`, or slicing to process structured data means a parser was missed, and `docs/conventions.md` names one per format. Never hand-parse an agent's output either — take it through a Pydantic model.
- **Placement decides the package** — would another project built on this library want it? Then it belongs to the library; only this application, and it stays there. The same test applies to values, not only to code.
- **Never truncate** — the container grows to fit what it holds, not the reverse. Cut only where a document format or a function contract imposes a hard limit, never for printing space, log volume, or ease of reading; where a cut is forced, save the full copy and point at it. A cut artifact looks exactly like a complete one, which is the whole difficulty: `[:200]` loses the rest with nothing said, and the reader who needed it cannot tell.
- **The code is the source of truth** — it should read as though it had always been written this way. Never reference what code used to do, and never write "now", "new", "updated", "fixed", or "changed" in a comment. Change history belongs in commit messages.
- Reach for `for` and comprehensions over `while`, and `match`/`case` over an `if`/`elif` chain dispatching on a value.

Some rules shape a design before any gate could catch it. Know these by name while choosing a shape rather than after being stopped: `own-model-dispatch` (a union answers through its members, never through `isinstance` over our own types), `abc-capability` (a capability ABC is an engine, never a surface a consumer holds), and `constant-declaration` (a judgement reaches its caller as an overridable default).

### Exceptions No Rule Can See

A rule states the shape it refuses. These carve-outs are ours, and its diagnostic does not carry them:

- **Barrel files.** `__all__` and `__init__.py` re-exports are refused; import directly from the module that defines the symbol. The exception is a standalone package's own top-level `__init__.py`, which may declare a public API that way — the package root only, never a subpackage.
- **Private prefixes.** Nothing is private, so a `_` prefix is refused on functions, methods, classes, and constants. An unused parameter (`_context`, `_exc_type`) is exempt: a linting convention, not a privacy one. A helper that should not pollute the module namespace **nests inside its only caller**, which hides it without claiming privacy; a wrapper whose only purpose is to call one other function is not worth hiding — inline it.

---

## Tooling

`uv` is the package manager — `uv add <package>`, never edit pyproject.toml directly. Lint and format with ruff, type-check with pyright; `docs/contributing.md` carries the commands that have to be green.

`lup` itself is the one dependency not added that way: how a project obtains it is a mode `dev library` reads and rewrites, and the mode decides what upgrading means. Ask `dev library status` before assuming lup's source is on disk to edit — in three of the four modes it is not.

When a command genuinely has to run outside the sandbox, put it through the runtime's native per-call escalation on its first attempt rather than replacing the whole session with an unsandboxed one; the policy still judges the escalated call, so an allowed command can be approved at that narrower boundary.

### lup-devtools

Development tooling is the `lup-devtools` CLI, composed from the reusable commands under `packages/lup/` and this repository's under `src/lup_template/`. **Use it instead of ad-hoc commands.** Inline Python (`-c`, `-m`, a REPL, or bare `python`) is denied; `uv run python <script.py>` is allowed because a file can be reviewed. Running the same command repeatedly means **add a command** to the half that would reuse it.
`tmp/` is gitignored scratch. To **read** code, use `py info`/`py source`/`py search`/`py text`/`py imports` or codeintel; to **compute once**, write a script under `tmp/` and run it; to reuse the computation, add a devtools command. `docs/contributing.md` carries the rest of this reviewability ladder.

The `codeintel` group answers questions about code by *resolving* it, through a language server. **Prefer it or `py search` for anything about a name**, and `rename_symbol` over an edit with `replace_all`, which cannot tell one scope from another. Use `py text` for literal text in explicitly scoped Python source, and grep for characters in non-Python files.
`docs/commands.md` carries every command the CLI serves, walked from the wired app at generation time rather than listed by hand — so a command exists there by existing, and reading it is how you find one you did not know to look for. `--help` gives its options.

### Generated Trees

`harness generate all` regenerates every native plugin; `harness <runtime>` regenerates one and launches it. Skills and agents render from typed catalogs — one under `packages/lup/` for what is about agent work, one under `src/lup_template/` for what is about being a template, composing both. Change the catalog that owns the subject, then regenerate.

**Every runtime, same change.** State and build each answer to every policy, flag, hook, or artifact; name substitutes for unsupported concepts. One runtime drops `sandbox="outside"` for lack of a per-call escape. Done means `harness generate all` reconciles both; `docs/permissions.md` maps gaps.

---

## Configuration

Configuration loads through pydantic-settings in `src/lup_template/agent/config.py`, the only module that reads the environment. `.env.local` holds secrets, is gitignored, and overrides the defaults in `.env`; `docs/template.md` lists the variables.

---

## Process & Communication

**Wait on pushed tool output, not polls.** Keep a long-lived command's resumable call live and yield to the runtime's event-driven waiter. Repeated shell-session reads are polling, even with long timeouts.

**Surface every question through the harness's structured facility**, not narration: clarifications, choices, and destructive confirmations included. Even open-ended questions need concrete options plus free-form because downstream notifications read structured answers.

**Explain decisions from scratch:** the problem, relevant state, options, rationale, and your recommendation marked as yours. A verdict cannot be judged; prefer complete context over brevity.

Verify claims against **what was actually asked** — the note or issue itself, not a title, commit, or prior summary. State surviving claims plainly; correct failures out loud, including yours.

**After every command**, compare actual use with its docs and propose any update as a question. External docs, corrections, uncovered requests, or ignored sections signal that the command should evolve.

### Reporting Friction

**Fix tooling friction instead of working around it.** This repository usually owns the hook, command, or classifier that obstructed you. Repair it on its own branch so the diff stays single-purpose.

**Open an issue only when this session cannot repair it**: the owner is outside this repository, a design decision is missing, or reproduction is the work. A narrated workaround teaches nobody, so what cannot be fixed is still recorded.

Record the exact command, error, resulting state, recovery cost, and owning component — repair commit or issue — with `uv run lup-devtools dev report-friction`; the checkout selects the repository. Evidence beats conclusions.
**Read the tracker first.** `uv run lup-devtools dev issues` lists open reports; search closed ones too. Update a matching report with `--issue NUMBER`, or comment on a closed match, rather than splitting evidence across duplicates.

### External Resources

When a question is about the harness you run under, its agent SDK, or its model API, read that runtime's own documentation rather than answering from memory — delegate to the documentation subagent your harness ships, or fetch the vendor's docs at the Codex documentation at https://developers.openai.com/codex/ and https://learn.chatgpt.com/. The fetch scopes the policy admits are declared in `harness/catalog.py`. When the user provides documentation links, fold what they teach into the guidance source or the relevant skill.

---

## Self-Improvement Loop

`docs/self-improvement.md` carries the full loop, and the feedback-loop, review, and meta skills each work from it.

**When analyzing failures:** Ask "what general principle would have prevented this?" not "what specific rule would catch this case?" The fix is almost never a prompt line about a specific decision. Instead: does the agent have enough context? The right tools? A strong enough model?

The durable fix is a capability, not a rule: trace the failure to the missing input or the workflow step where the wrong decision entered, and change that — a prompt rule coexists peacefully with the failure it warns about.
