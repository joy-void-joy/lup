# lup: design brief for the restart

This is the distillation of lup's first incarnation (`joy-void-joy/lup-legacy`, archived; about 4,600 commits from February to October 2026) into a brief for rewriting it. The rewrite takes the name `joy-void-joy/lup`. Nothing is carried from the old code; this brief is the only thing that crosses over. The old repository stays readable as evidence. Decisions are the operator's unless marked as the agent's call; anything not settled is listed under **Open questions**. The evidence behind each part, and the running record of decisions (`DECISIONS.md`), stay in the first lup's local checkout and aren't published; the `tmp/` paths below refer to it.

## Purpose

lup is the operator's environment for developing projects with Claude Code, and with Codex. One environment is carried across projects and configured per project by a declaration. It's built on a library, its own package, that any project whose code calls agents can use without the environment.

It serves two parties, and is judged by how well it works for both:
- **The operator** steers early, sees every agent and everything waiting on them in one place, and reviews what matters before it lands.
- **The agents** spend their effort on the task, not on the environment. They know what's theirs to decide and where the walls are, and they're asked how the work felt so the environment keeps improving.

It is not a framework prescribing how agents work. The first lup grew around a single agent with many tools and a scripted workflow. With current models that shape is obsolete: the work that went best gave the agent a room with walls and room to work, not a corridor.

### The three problems the restart must solve

Each comes from the exploration's evidence:
1. **Too many instructions, resolved differently by each session.** Guidance, skills, hooks and the runtime's own prompt pulled against each other, so each session picked differently, and one agent dismissed a problem another later called "pre-existing".
2. **A system no agent can hold.** About 170k library lines, 71k devtools lines, 176k test lines, 256 commands, 77 rules and 38 skills. Each agent fixed the slice it saw, and the fixes were local and kept coming back.
3. **lup pulling every task's side work toward itself.** In downstream projects, most sessions ended up maintaining lup: nearly every commit in live-translator, and every session of a research project after its first week.

The answer is a module-first lup that is small, fast and quiet while an agent works in a project, with each part built on one idea that can be stated in a sentence. The whole may be larger than any agent can hold, as long as each part can be held on its own (see *The environment: core and modules*).

### Who uses it, and for what

- **Maintaining a project** (two private projects, and lup itself): sessions with gates, branches and reviews.
- **Doing a project's work in a room**:
  - an art studio, where the agent makes art with code;
  - an audiobook pipeline: given a whole chapter or book, the agent produces the audio in its destination, using a few existing tools, with free rein over the codebase;
  - a research project running parallel investigations.
- **Calling agents from code**:
  - live-translator makes a quick typed call with no tools;
  - aib forecasts, where outcomes come back later and experiments compare versions.

## Architecture

### Two packages: the library and the environment

The split is what a project imports in its production code, against what it uses only while being developed. The environment depends on the library and never the reverse: a session the environment launches is a library launch with more attached.

- **The library** is what live-translator, the audiobook pipeline and aib's forecaster import:
  - `Claude`/`Codex` clients with `ask` and typed output, sessions and their history;
  - tools defined from Python functions;
  - launching a container for a call that needs one, with its mounts;
  - rooms (see *Calling agents from code*);
  - `runs`: durable long-running work;
  - the outcome loop, shipped as it is;
  - traces and cost;
  - `SharedBudget`, with `Throttle` merged into it: request rates, local or shared across processes;
  - the fake agent, and the guard that refuses real agent and network calls during tests.

  The library emits events, and a dashboard that's running picks them up, so the library never imports the dashboard.
- **The environment** is what the operator launches to develop a project: everything below.

**Packages (tentative).** One repository with a uv workspace holds three packages, with dependencies running one way only:
- `lup`, the library;
- `lup-dev` (`lup_dev`), the environment, named for the boundary: what a project uses only while it's being developed;
- `lup-dashboard`, the dashboard, the one part with its own stack. It depends on `lup-dev` through the typed protocol, never the reverse.

Python 3.14 or later, for its lazily evaluated annotations. The library's runtimes are the optional extras `lup[claude]` and `lup[codex]` (`docs/library.md`).

**The library's shape (tentative; detail in `docs/library.md`):**
- **Split.** Runtime-neutral code under `lup/sessions/` and `lup/tools/`; one adapter per runtime under `lup/adapters/`.
- **Results.** `ask` returns a `TurnResult[T]` (`output`, `usage`, `duration`, `session_id`, `rejected`); a failure is always an error.
- **Layers.** One `layers` field on the declaration carries timeout, recovery (on tenacity), submission and trace.
- **What the declaration doesn't hold:**
  - tools are `lup_tool` constructs;
  - the endpoint and API key are given when the client is created;
  - resume and history belong to the session holder;
  - transcripts belong to lup's own writer.

### The environment: core and modules

The whole may be larger than any agent can hold, as long as each part can be held on its own:
- the core is small enough to hold alone;
- every module uses only the core's public API, never another module or the core's internals;
- dropping each module is tested (in the first lup, removing one module kept breaking another).

The parts that cut across everything (the one hook, the dashboard's protocol, the declaration) sit in the core, so the core's size is the number that matters.

- **Core:**
  - launching sessions, with containers, mounts and accounts;
  - the wall, holds and protected paths (the policy);
  - code rules and the gate;
  - compiling the harness at launch;
  - worktrees, commits and merging;
  - updates and migrations;
  - the dashboard;
  - the "how it felt" notes;
  - lup's tools for spawning, messaging, waiting and asking.
- **Modules, on by default:**
  - `coordination`: roster, messages, handoffs;
  - `ledger`: the one place for open work;
  - `git-workflow`: landing and PRs.
- **Other modules:**
  - `budgets`: the operator's control over shares, pace, pauses and spawn caps;
  - `resolver`;
  - `release`;
  - `tracked-repositories`: today's `sync`;
  - `setup`;
  - `meta`;
  - `realtime`: wanted;
  - `conversation`;
  - **reflection** (open).
- **What the library holds and the environment serves:** `runs` and the outcome loop are the library's; the environment serves their commands (`run monitor` and the like) to a project that uses them. Rooms are the library's; the free mode is a room a project declares, and a tidy pass follows a free run that changed shared code.
- **Corpus merges into the ledger** as a kind, for reports that regenerate and stay current, as the research project used it.

**Everything is a selection, never an on/off switch.** At every level (modules, rules and rule families, commands, skills, hooks), a project says "take these" or "everything except these". Overrides are operations on lup's defaults, one grammar for every kind: set arithmetic for selections, and `.add`, `.replace` and `.drop` for the rest.

### How lup reaches a project

- **A project holds its own code, a dependency on lup, and one declaration.** Where it lives is open (Open questions, 8): a fixed `lup_project.py` at the project's root (leaning), or a module named in `pyproject.toml` (`[tool.lup] project = "audiobook.lup_project:project"`), as lup's own declaration is today.
  ```python
  project = Project(
      package="audiobook",
      modules=Modules.all() - {"ledger"},
      rules=Rules.all() - {"tuple-shape"},
      guidance=Guidance.default().replace("code", Path("guidance/code.md")),
      skills=[Skill.from_file("skills/narrate.md")],
      devtools=Devtools.default().add(studio_cli, name="studio"),
      rooms=[audiobook],
      tests=[Pytest("tests"), Pytest("studio/tests", environment="studio")],
  )
  ```
- **The declaration says which paths are what, and every tool's settings are compiled from it.** It declares the paths that are code (held to lup's rules, ruff and pyright), tests (ruff and pyright only) and excluded (held to nothing), beside the protected ones. ruff's, pyright's, pytest's and import-linter's settings are compiled from lup's defaults plus the declaration, with a gate test failing when they drift, so no project copies lup's tool settings, and an update to lup reaches them by recompiling. Where the declaration lives, where the compiled settings go, and who owns dependencies are open (Open questions).
- **Nothing of lup is copied into a project.** There's no copied half and no lup tests in projects. Changes to lup go upstream; whoever wants a different lup forks it.
- **Runtime trees (`.claude/`, `.codex/`) are built at launch and never committed.** Wherever the launch places them they're read-only, and an attempt to edit one is refused with a pointer to the source to change. lup's own docs stay committed in lup and are served to projects from the installed version (`lup docs <topic>`).
- **One CLI, from the library.** It builds its command tree at startup from the declaration: lup's groups for the selected modules, plus the project's own commands, replacements and removals. It loads only the command invoked, and stays fast under load; today each call costs about 10 seconds.
- **A new project starts with `lup new <name>`.** lup itself has its own declaration, since it's developed with itself.
- **Precedence:** lup's default, then the person's config (`~/.config/lup/config.toml`), then the project, then an argument. Personal matters live in the person's config: accounts, theme, budget shares.
- **An update is a version bump plus automatic migrations.** It stops only for what a person must decide. `Rules.all()` includes rules added later, and an update that brings one lists its findings in the project and asks whether to exclude it.
- **Releases only, never pins to branches.** A project never edits lup in place and never points at a branch of lup. When lup is in its way:
  - **It fixes the problem locally**, through its declaration's overrides or in its own code, with whatever unblocks its task. The local fix may be ugly: the generic one is lup's job.
  - **It declares an upstream candidate** beside the fix: the friction, the local fix or a pointer to it, the evidence, and the lup version it was written against. A candidate is the dual of a migration: a migration is lup telling a project what changed, a candidate is a project telling lup what it needed.
  - **The adopting pass** (`/lup:sync`) runs in lup's repository when the operator starts it, never automatically. An agent reads the registered projects' candidates side by side, groups them by the construct they touch, designs overlapping needs as one construct, consults the operator, and adopts. It gates everything together, checking the registered downstream projects.
  - **The release that adopts a candidate ships a migration** that removes each project's local fix and its candidate in the same step. A candidate lup declines stays local, with the decline recorded on it so it isn't proposed again.
  - **Nothing waits on adoption**, since the project already works.
  - **The declaration's override surface decides how much friction can take this path.** A defect in the core hook or the launcher can't be patched from a project; it becomes a "how it felt" note with no fix attached.

  The candidate's format, and keeping candidates and notes from piling up, are open.
- **The README is rewritten whole:** how to use lup at all, and what each module does. The template's sample application moves to `examples/`.

### Sessions

- **Two roles.** A session either maintains a project (gates, workflow) or does the project's work in a room (container as the wall, a toolkit the agent may extend, short guidance). Leaning: a maintaining session is itself a room that lup declares, with the gate and git in its toolkit, code rules and holds as its hooks, and a worktree as its mount, so the two roles are two room declarations. To check: whether maintaining needs anything a room can't declare.
- **lup's spawn replaces the native `Agent` tool, on both runtimes.** Every worker is a top-level session with its own identity, budget share and place on the dashboard, under the agent that spawned it. A spawn can return the worker's result in the same call or leave it detached.
  - Forks use `--resume <parent> --fork-session`.
  - Claude Code's built-in types run as top-level sessions with `--agent` (measured: `--agent Explore` narrows the tools to read-only).
  - lup's own agent types are definitions in its Python API.
  - Only lup's spawn lets a Claude session hand work to a Codex worker, or the reverse.
  - **Work in another project is spawned there.** "Fix nori's core bug" from a lup session spawns a worker in nori's worktree, which runs under nori's own declaration, rules and reviews and reports back, so nobody quits and remounts.
    - A host-side lup service launches it. The asking agent never leaves its container, and can start only sessions, with typed arguments, never arbitrary host commands. So spawning is automatic: the worker shows on the dashboard, and budgets bound it.
    - A session writes only in its own project. The projects it knows are mounted read-only, so it can read how one works and brief the worker well.
    - It needs registered projects, so a name like `nori` resolves to a repository.
  - Why not native subagents: with `subagentPromptCacheTtl: "1h"` they get the 1-hour cache too, so cache rebuilds don't separate the two. What does is seeing, pausing, messaging and budgeting every worker as part of the whole. Keeping native `Agent` for short jobs stays open, to settle by measuring the new spawn (Open questions).
- **Native tools for the agent's own work; lup's tools for everything between agents, and between an agent and the operator.**
  - Kept native: Edit, Read, Bash, `apply_patch`, search, web, background processes, the agent's own task list, `Skill`.
  - Denied by default: `Agent`, `SendMessage`, `ListAgents`, `EnterWorktree`/`ExitWorktree`, and Codex's own spawn.
  - `AskUserQuestion` is denied once lup's inbox exists, and the agent is pointed at lup's own ask tool, which reaches the inbox. Until then it stays in the terminal, in sessions the operator is attached to.
- **Waiting is one mechanism.** A wait is a hold inside the tool call, released by the operator's answer, so the agent doesn't have to manage it.
  - Holds are wanted: they pause the agent so the operator can catch up.
  - When a held call returns, its result says it was held and carries the operator's comment, so the agent knows it was seen and whether to change course.
  - A hold answered within the hour keeps the agent's cache. One that runs past the hour costs a rebuild, which is accepted: the agent is never put in an automatic loop re-entering a wait to keep its cache warm.
  - A main session stays free to talk and is woken when the answer comes.
- **Coordination is light.**
  - The roster fills itself from what a session is doing (its brief, its branch, the paths it changed), with no describe calls.
  - Messages are sent with a lup tool and received at the next tool call (through the one hook) or with a blocking wait.
  - The operator is a peer on the roster. Telling them something is a message to a peer, with a `kind` (question, disagreement, note) that lets the dashboard show disagreements apart from status. The tool's description names the case: if an instruction seems wrong for this case, say so, without stopping.
  - Handoffs go to the ledger, and a handoff can directly spawn the agent that picks it up.
  - Conflicts are detected when writes merge back, instead of through path locks.
- **Session settings:**
  - subagents and workers get the 1-hour prompt cache (`subagentPromptCacheTtl: "1h"`);
  - five unused built-in tools are removed from context (`Artifact`, `SendFeedback`, `Workflow`, `ScheduleWakeup`, `ReportFindings`);
  - auto memory is off on both runtimes;
  - compaction stays at the runtime's default (leaning): long contexts are kept, and budgets keep their spend in check.

  All are declared defaults a project can change.
- **Isolation between sessions (open).** Leaning: a worktree per agent, with environments hardlinked from a cache on the same filesystem. The write layer (`open/write-layer.md`) isn't ruled out, but the operator isn't convinced, and it has two problems to check first:
  - overlayfs leaves changes to its lower layer undefined while the overlay is mounted, so a layer can't sit on the live checkout other agents merge into. It needs a frozen snapshot per base commit, each with its own environment, which is the worktree alternative with an overlay on top.
  - Showing a layer on the host at `tree/<name>` exposes what the agent wrote there, its own `.git` (with a `core.fsmonitor`) or `.vscode/` settings among it, to the operator's editor before any review. That's the worktree-pointer escape the first lup closed.

  What a layer would add over worktrees: background writers and gitignored files are captured, and a whole layer can be discarded.

### Budgets

- **Shares per project or agent over a time window,** torrent-style.
- **A pace limit for unattended runs,** so usage stays under the 5-hour window instead of hitting it and stopping abruptly.
- **Pausing low-priority agents through the spawn hierarchy,** so pausing a parent pauses its subtree.
- **Caps on how much a subtree may spawn.**
- **An automatic resume when a window resets.**

The control runs as its own small host process. A hold within the hour keeps its cache; past it, the context rebuilds. Throttling trades time, not tokens.

### Policy

- **Walls plus protected-path review, and no verdicts on commands** (leaning yes). Inside the container a command simply runs. Effects that can't be undone are stopped by a wall where they pass. Protected paths are reviewed before they land. The shell-spelling analyzer, per-command verdicts and `dev policy` go.
- **Every write path is judged the same way, by what it produces.** Whatever the tool (Edit, Write, a `sed`, a script, `apply_patch`), code rules and asks apply to the content it produces. No command's spelling is parsed.
  - **`Edit` and `Write` are judged before they land,** on the content they would produce, so a refused edit never touches the file.
  - **Everything else is judged at a checkpoint.** lup keeps one accepted state per worktree, compares the worktree with it, and judges whatever changed, whichever call or process made it. This covers parallel calls and writes landing after their call.
  - **A checkpoint** runs whenever a call finishes and no other call is running, and again at turn end. It's built from four runtime-neutral events (session started, call started, call finished, turn ended), so it works the same on every runtime (`docs/judging-writes.md`).
- **lup allows, asks, or refuses.**
  - **allow:** tests, scratch, docs and data at any size, and any production edit the code rules pass. There's no line count: in auto mode, edits inside the working directory skip the classifier anyway, and the first lup's 3-line limit mostly made agents split edits. The allow keeps routine work from interrupting, which is what the operator relied on in the first lup.
  - **ask:** a change to the design waits for the operator: a new production file or a whole-file overwrite (the one that matters most to them), a protected path, an added suppression, and a public-API change (a package root's names, a new class, a changed signature of a definition that existed when the session started). These show design better than a line count does. On Claude Code it's the runtime's own prompt before the call. Where a runtime can't ask before a call, the change is held at the checkpoint instead.
  - **refuse:** a code rule's finding, or a design change that bypassed the ask (a new file made through the shell). The change doesn't land, or is put back, with the agent's version saved.
  - **Every verdict is logged** (tool, path, outcome, reason), so how often lup asks can be measured and tuned.

  The point of an ask is that the operator understands the codebase's overall design and redirects early when an approach looks shaky or differs from what they had in mind. Guidance never teaches splitting a change to slip under a limit.
- **A container is required whenever an agent can run code or write files.**
  - **Interactively, without a container engine:** there's no lup policy, only the runtime's own permission mode, and launching that way takes an explicit `--dangerously-…` flag.
  - **From code:** a call with Bash and `sandbox="none"` raises, unless it sets a `dangerously_…` flag. A call with no tools needs no container.
  - **Mounts are one declaration.** Inside a container they're bind mounts. With `sandbox="none"` they become the allow-list for the file tools.
- **Leaving the wall is a request with a typed reason (tentative; the reasons are open).** The first lup's `# lup: escalate[sandbox]: <why>` comment becomes a lup tool call whose reason is a field, so nothing parses a command. Each reason gets its own outcome, a selection like everything else. The reasons below are the ones agents actually gave for `escalate[sandbox]` in the first lup's transcripts:
  - **work in another project:** lup's spawn there, automatic (see *Sessions*);
  - **credentials** (push, opening a pull request, publishing): a host service that does that one action, asked per action;
  - **a protected path** (runtime settings, generated harness files): the ordinary ask;
  - **a tool or device the container lacks** (a pinned toolchain under the home directory, a GPU, audio, a display): a reviewed command on the host, plus a note that the room's image should carry it;
  - **repairing the environment** (git pointers after a repository moved): a reviewed command on the host;
  - **anything else:** a free-text reason, always reviewed. Unknown problems are the case the list can't foresee: once, nobody realized the sandbox hid the GPU, and the agent had to escalate every few commands to debug it.

  Three things keep that case from turning into a prompt per command (tentative):
  - **Answers can be scoped.** The operator can answer one request "for this session, for this reason" as well as "once".
  - **Repeats are the signal.** Every escalation is logged with its reason. The same reason coming back means the room's declaration is missing something (a device, a mount, a toolchain), and it surfaces on the dashboard as that, to fix at the source.
  - **Launch says what the wall hides.** A launch reports what the host has that the container doesn't: GPUs and other devices, toolchains on the host's `PATH`. A hidden GPU is then visible before anyone debugs it.

  Several of the first lup's escalations came from its per-call sandbox (a unix socket refused, a read-only symlink), which the container as the only wall removes.
- **Network: leaning open egress.** Filtering produced constant friction and reviews that were mostly fine. So nothing secret is mounted, apart from the runtime's own login (below).
- **Secrets: leaning the art studio's pattern.** No secrets and no GitHub credentials in the container. Project secrets live in host services the container reaches by name, and pushes happen from the host.
  - **The runtime's own login is the one secret a container has to hold**, since Claude Code and Codex can't run without it, and open egress could send it out. It's hidden from the agent's commands by the runtime's own sandbox, configured only for that and not as the wall (whether it runs nested in the container is a check owed).
  - **Saved transcripts and traces are scrubbed** on the host of known secret values. Only a name is written in their place (`[redacted: GH_TOKEN]`), with no prefix or length, and the scrubber logs nothing but that name. A command once printed a gh credential that then had to be rotated.
  - **Filtered egress stays possible**, but it's expected to bring the old friction back.
- **Privileges: leaning sudo in free (room) modes.** Inherited capabilities are always cleared; a session user held root's capabilities without sudo. Package installs default to a minimum age, for example nothing newer than 3 days.
- **Protected paths:**
  - the project declaration;
  - dependency manifests and lockfiles;
  - what runs outside the container: CI, git hooks and `.git/config`, pre-commit, editor and devcontainer configs;
  - what widens the wall: `sync.json`, `sync.json.local`;
  - secrets (`.env*.local`, not even readable);
  - in lup itself, its own policy and launch code, which trust on launch reviews before the next launch runs it.
- **Reviews happen before, by default.** The operator steers early rather than finding a patchy approach hours later. Examples, docs and guidance are reviewed after: they land, the operator is told, and one step reverts them. Comments and declines on a launch review become the first input of the session that launch starts.
- **A declined change is restored, never lost.** The agent's version is saved at a path the refusal names, beside the operator's comment. The agent revises the lines in question in the saved copy and moves it into place, and the move is judged like any write. Nothing is resent whole. Restoring matters: a change left in place invites building on a design the operator just turned down.
- **Trust on launch is ported as it is.** The host-zone fingerprint, the review in the dashboard, and launching from the approved copy.
  - Until it's ported, the judge gets the same review: refreshing the installed judge from `dev` shows its diff since the copy the operator last approved, and the approved copy keeps judging until they approve. The operator is sure of what runs before it runs (`docs/judging-writes.md`).

### Code rules and the gate

- **Code rules refuse at the edit, early and loud.** A rule exists to stop an approach at the moment it's chosen, before anything is built on it. The anti-regex rule replaced quick regex patches, which often silently didn't work, with proper parsers. A regex refused at the edit costs one rewrite; one refused at commit has had an hour of code built around it. An informational rule would get bypassed.
  - **A refusal reports every finding in the file at once, like pyright:** path, line and column, the rule, why it exists, and the fix.
  - **A refused write is restored, and the agent's version saved** at a path the refusal names. The agent fixes the listed lines in the saved copy (with a `sed`, or an Edit after reading just those lines) and moves it into place; the move is judged like any write. Nothing is resent whole.
  - **Each rule names the design mistake it prevents and where it steers.** The regex rule names silent parsing bugs; `tuple-shape` and `set-shape` name positional data a reviewer has to decode ("what is field 5?"). A rule that can't name one goes.
  - **A rule that misfires is that rule's bug,** and a noisy rule is rewritten until it fires only where a design choice is at stake.
  - **Rules read one typed tree, from the first rule.** Each file is parsed once and type-checked once, and every rule reads types straight from that tree: pyright's own tree, built against its source at a pinned release, as a spike measured (`docs/judging-writes.md`). No regex, no separate oracle asked about one position at a time, and no syntax-only first stage, which is how the first lup's catalog grew into a patchwork. The conventions the rules enforce, and which tool owns each, are in `docs/conventions.md`.
  - **`# lup:` comments are one grammar.** A directive is written as a call (`# lup: ignore("tuple-shape", why="…")`), and anything that isn't a call is a note. A call to an unknown directive is a finding, and so is an `ignore` without its reason. Every rule accepts `ignore`, and adding one asks the operator. `defer` points at a GitHub issue or carries a condition the gate can check; the ledger's to-do items point at GitHub issues too. A note added in the same session can be removed freely; removing a committed one is reported.
- **Information never travels on a "blocking" channel.** Type errors and ruff's findings arrive as plain context, limited to the files touched, at each checkpoint. What must be fixed before finishing is enforced when the turn ends. The formatter runs at commit.
- **Tests are exempt from code rules, and the rule docs say so.** A file's test role comes from the declared test roots, nested projects included. In the art studio the exemption existed but never applied, because a pytest root gave its files no test role. lup's own architecture rules (front-door, seam-boundary and the like) apply only to lup itself.
- **No flaky tests.** A test that fails and then passes is a failure to fix. Changed and new tests run repeatedly and under load before they land. Tests depending on the real clock or on wall-clock timing are refused. A unit test over about 10 s fails the gate unless it's declared slow with a reason.
- **Tests stub every agent and network call.** The library ships a fake agent, and a guard refuses real calls during tests.
- **The gate:**
  - `--changed` compares against the branch's own base, and covers markdown too;
  - a nested project's tests run in its own environment;
  - the gate stays bounded in time and memory (why today's grew so much is to be found out).

### Runtimes

- **Codex is a peer.** The operator wants Codex agents, and the option to use them, alongside Claude's.
- **Shared constructs, and an adapter per runtime.** A shared change is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Leaving one untested is not an option. Everything above the runtime contract below is shared, so it's on both runtimes by construction: Codex rotted in the first lup because features were built per runtime above that line.
- **What lup needs from a runtime is small:**
  - launching in a container with lup's tools and guidance;
  - one hook that holds a call and delivers waiting messages;
  - a transcript reader for telemetry and cost;
  - optionally, an interrupt.
- **Capabilities are declared per runtime.** A short real session checks them on its own whenever either installed CLI's version changes, and the result is cached per version. A feature that needs a missing capability is unavailable on that runtime, and the launch and the docs say so. A stand-in is allowed only when it's declared and covered by that check.
- **Codex's `apply_patch` parsing is dropped:** the after-call diff shows every file changed.

### Calling agents from code (the library)

- **The client is the declaration:**
  ```python
  translator = Claude(model="opus", system_prompt=PROMPT)            # no tools: no container
  result = await translator.ask(segment.model_dump_json(), Translations)
  result.output                                                      # Translations
  ```
- **A room has the same shape, and is the library's.** It's declared in `lup_project.py` and used from code, waiting (`room.ask()`) or detached (`room.spawn()`), or in a terminal (`room.launch()`, or `lup launch claude audiobook`). One declaration compiles two ways: to SDK options for code, and to argv for the terminal. `Claude(...).launch()`, `.command()` and `.prepare()` already work that way on today's dev (merge `008d23ca1`), and `harness claude|codex` is built on them. The parity checklist in `tmp/lup-dx-overhaul.md` maps every harness flag and launch step to a declaration field. The verbs are open (see Open questions).
- **Publishing stays outside the room.** An audiobook pipeline ("turn this page into an episode and publish it") runs the room to produce the episode, and host code publishes it, with credentials the container never sees.
- **Typed output through a lup tool on both runtimes (tentative; earlier leaning: native on both).** The answer is submitted through `lup_submit`, an ordinary lup tool whose input is the output model, so it keeps everything a normal tool has, hooks included.
  - **Corrections happen inside the turn.** Validation, and any `before` hook on the output tool (a review answering `Allow()` or `Deny(reason)`), reject with feedback, and the agent corrects its answer without being re-prompted.
  - **The turn can't end without an accepted answer.** lup's own stop hook refuses the ending: in-process on Claude, a same-thread continuation on Codex.
  - **Native structured output is used on neither runtime.** Codex's isn't a tool call, so nothing could reject it inside the turn, and its strict-schema subset forced a carrier (`docs/library.md`).
- **Supervision.** Rooms and anything long-running appear on the dashboard and fall under budgets; a quick call with no tools records only its cost. Sessions started from code run under their own config home, so they never appear among the operator's own sessions, history or messages.
- **A persistent REPL (leaning yes).** A tool for agents run from code and in rooms, inside the wall. The agent can freeze, fork and rewind its state, and it must be light.
- **Delegation from code** is a nested call through the client, or lup's spawn. No third route.
- **Auth.** The CLI login by default, which fits the operator's own use. A project other people will use declares an API key (Anthropic's terms).

### The dashboard (core)

- The main place of interaction, including spawning sessions. It replaces Claude Code's task view for lup's workers. Every ask lup makes of the operator goes through it.
- **In lup, behind a typed protocol** between the sessions and the dashboard (agents, the inbox, reviews, the ledger, budgets), so the page can be redesigned without touching the rest. It ships prebuilt, so no project builds its stack.
- **The first screen is the agents**, as a tree: what each is doing, what it waits on, and its spend, with its reviews and questions underneath.
- **The operator's inbox:** reviews, open questions from agents, and the ledger's open work.
  - **Messages are reviews, and reviews are messages:** one mechanism. An agent's message is read and answered the way a change is reviewed: the operator sees every waiting message at once, comments on its lines, agrees with a stated lean, replies to several at once with answers that refer to one another, and leaves some unanswered for later.
  - **It's generic and asynchronous both ways:** agents write to the operator and the operator replies in their own time, beyond deciding things. The plain linear question and answer stays.
  - Numbered decisions, each with its lean, show as separate items answerable "leaning", "undecided" or "leave open", so a question can't scroll away and an answer to one doesn't wait on another.
- **Controls:** budgets, pause, pace and spawn caps; runs are shown.
- **Every key is also a button or a menu entry.**
- **Its readability and navigation need a redesign** (see Still to discuss).

### Feedback

- **"How it felt": core, on by default.** The point is to gather friction and wellbeing data from the agents and make lup as good as possible to work in.
  - Every hand-back, and every main session's end-of-task report, ends with a free-text note under three prompted headings: what was smooth, what got in the way (the exact command and message), what you'd change. "Nothing notable" is an acceptable answer, so the note doesn't turn into filler.
  - Notes are stored in the ledger, and serve as the evidence attached to upstream candidates.
  - The pooling pass looks hardest at what telemetry can't see, mainly moments when an agent wasn't sure a decision was its to make.
  - Telemetry is attached automatically: refusals and recurring messages, errors and retries, cache rebuilds, cost.
  - A pooling pass, run on demand, groups repeats, links or files issues, and ranks by frequency and cost. The dashboard shows what recurs.
- **The outcome loop: a module, off by default,** for graded projects like aib. lup provides the machinery only: attaching a project-defined outcome to a run, grouping runs into arms, comparing them. The project decides what success is and which experiments to run.
- **Reflection (open).** The operator's current leaning is a separate module, off by default and requiring the outcome loop, that records data from each run for the outcome loop to use. It's neither self-critique nor the "how it felt" notes.

### Footprint and cleanup

lup cleans up after itself:
- containers, images (session image tags are retired with their checkout), volumes;
- environments in idle worktrees;
- merged worktrees nobody holds;
- run outputs, bounded;
- trace archives, deduplicated;
- git objects, collected.

Environments hardlink from a cache on the same filesystem instead of being copied.

### Guidance and skills

- **Every gate, rule and hold names why it exists and where it's trying to steer,** so an agent can judge the cases it doesn't spell out: one line in each refusal, the full reason in the docs.
- **Guidance gives each rule with its reason,** so an agent can judge the cases the rule doesn't spell out.
  - It states what's the agent's to decide, what's the operator's, and where the walls are.
  - It contradicts neither the runtime's own prompt nor any skill.
  - It's written last, once the system it describes exists.
- **The operator likes being asked numbered questions in plain text,** each with a stated lean, that they can answer "leaning", "undecided" or "leave open". Guidance and skills prefer this for decisions. The structured question tool is kept for a quick single choice.
- **Skills are reference:** what the work is for, what good output looks like, the known traps. Fixed steps only where the order is mechanical, like merge and release.
- **One template serves lup and the projects using it.** It has the project's own section and lup's sections, rendered with Jinja.
- **Starting points** in the old repository: `tmp/guidance-rewrite/interim.md`, and `tmp/guidance-rewrite/REVIEW-BRIEF.md` for a fresh-eyes review.

## Graveyard

What the exploration tried and the restart leaves behind, each with its reason:

- **The copied half** (`src/` and `tests/` stamped out at init, updated by merge): every update was a large merge, and projects spent their sessions on it.
- **Committed runtime trees** (`.claude/`, `.codex/`, about 88k lines each): conflict markers in a compiled hook dispatcher refused every command; the launcher rebuilt them anyway.
- **Projects declining modules by subtracting from a full copy:** leaky; declined modules' commands were still served, and skills failed before their first step.
- **Pins to branches:** deleted branches broke installs.
- **A linear pre-release per project:** projects changing lup at once drift apart.
- **The shell-spelling analyzer** (about 17k lines) and per-command verdicts: it grew a case per spelling and couldn't see what a script writes.
- **The "inner" posture** (the runtime's own sandbox as lup's wall): replaced by "container, or no lup policy".
- **The `execute_code` sandbox module:** the agent runs inside the wall with Bash.
- **The single-agent template app** (tool policy, system prompt, subagents, reflect gate): every adopter deleted it.
- **Native subagents as workers, and native messaging between sessions:** subagents share their parent's identity, can't reach it, and can't be stopped after a resume; native messages don't cross containers.
- **Routing lup through each runtime's own orchestration features:** "mostly a nightmare".
- **"Equal on both runtimes" with nothing that runs regularly:** Codex rotted between uses.
- **Turtle mode:** a one-key slowdown, replaced by budget shares and pace.
- **A proxy replaying requests to keep caches warm:** Anthropic's terms forbid intermediating subscription tokens.
- **Explicit roster describe calls and path locks:** 251 describe calls in nine days; replaced by a roster that fills itself and conflict detection at merge.
- **Informational-only code rules:** they'd be bypassed.
- **The feedback loop's five-skill chain built on the template's agent:** it had no place for outcomes, and the loop never closed.
- **Guidance grown by patches:** 18 KB of bare imperatives, overriding the runtime's own advice and contradicting skills.
- **Undo snapshots taken for read-only commands:** writes into a repository the agent was only reading.
- **A prompt for every decision** (manual review before lup): it wore review down into approving everything, while files that looked fine carried design directions and regexes through. Approving whole new files and code rules pointing at the risky decisions are what made review work.
- **Refusals that report one violation at a time:** the art studio's agent resent a 550-line file four times, once per rule.
- **Guidance teaching agents to split a change under the edit-size limit:** it dodged the review the limit exists for, and turned one change into many tiny edits.
- **Code rules enforced only at landing** (proposed during the exploration, never built): by then an approach the rule exists to stop has had code built around it.
- **A keepalive loop for held agents** (re-entering a wait about every 50 minutes to keep the cache warm; proposed during the exploration, never built): the operator won't put an agent in an automatic wait loop. A hold past the hour pays a rebuild instead.
- **Contribution branches in lup's repository** (proposed during the exploration, never built): a project fixes locally and declares a candidate instead, so it never touches lup's repository or points at a branch.

## Field Notes

Facts that were expensive to learn. Versions are as measured in October 2026.

**Claude Code 2.1.291:**
- **Caching.**
  - Prompt-cache lifetimes are only 5 minutes or 1 hour (an API limit). The main conversation gets 1 hour on a subscription; everything else gets 5 minutes, unless `subagentPromptCacheTtl: "1h"` is set (or `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`). The setting is ignored while a subscription is in overage.
  - A cache read resets the timer, and the lifetime counts from the start of a request. Only a request resets it: a blocking hook or tool call makes none, so a hold past the hour rebuilds the context.
  - Every turn re-reads the whole context, so a long session's cost grows roughly with the square of its length.
  - Opus 5.5 prices: input $4 per million tokens, 5-minute write $5, 1-hour write $8, read $0.20, output $20.
  - A built-in cache keepalive exists for the main conversation only, behind a server flag; it did not run in our probe.
- **Tools.**
  - A bare tool name in `--disallowedTools` or `permissions.deny` removes the tool from context, subagents included (measured).
  - Print mode never loads `Artifact`.
  - An interactive session carries 113 KB of built-in tool schemas, of which `Artifact` is 55 KB. Claude Code's own system prompt is about 7.5 KB.
  - `autoMemoryEnabled: false` removes the memory section from the system prompt.
  - Edit refuses a file that wasn't opened with Read first: 894 "File has not been read yet" errors in the measured week, 785 of them after a read through `sed` or `cat`.
- **Sessions.**
  - `--agent Explore` runs a top-level session as that built-in type.
  - `--resume <id> --fork-session` forks a session.
  - `--bg`, `claude agents --json`, `attach`, `logs`, `stop` and `respawn` manage background sessions. Sessions in other containers aren't visible.
- **Other flags.**
  - `--autocompact <tokens>` sets the compaction window (100k to 1M).
  - `--system-prompt` replaces the whole prompt, tool guidance included.
  - `--bare` requires an API key.
  - `--json-schema` gives native structured output in print mode.
  - `--debug` writes to a log file, not the screen (`--debug-file <path>` names it).
- **Nested runs.** A nested `claude -p` does not inherit the outer session's `--plugin-dir`, but it does load the parent directory's `CLAUDE.md` and a nested repository's own `.claude/settings.json`.
- **Hooks.**
  - `updatedInput` takes effect, and `additionalContext` reaches the model.
  - A PreToolUse hold of 4 hours ran cleanly.
  - Each Bash call runs as `bash -c` in its own process group.
  - aib found that an `updatedInput` is discarded when a later hook overwrites it, so a submission gate must run last.
  - A PreToolUse hook that returns no decision sends the call through the normal permission flow ("staying silent doesn't approve it"). Its `ask` forces a prompt even in auto mode. Its `defer` pauses a headless run to resume later, and is ignored when several calls run at once (hooks docs).
  - A bare `permissions.ask` rule on `Write` prompts in auto mode (tested, 2.1.292).
  - PostToolUse hooks for parallel calls run concurrently. `PostToolBatch` fires once after a batch. `updatedToolOutput` replaces a built-in tool's result before the model sees it (hooks docs).
  - Command hooks get no terminal. `statusMessage` sets the spinner text while a hook runs.
- **Subagent writes.** Claude Code may refuse a subagent's write of a report file ("Subagents should return findings as text").
- **Terms.** OAuth is for ordinary use of Claude Code and Anthropic's own apps. Tokens may not be intermediated. Products used by other people need API keys. Plan limits assume ordinary individual use.

**Codex 0.160.1:**
- its own memories feature, off by default;
- no prompt-cache lifetime setting;
- no way to remove a built-in tool by name;
- the spawn argument is `task_name`;
- `turn/interrupt` responds in about 10 ms;
- `write_stdin` fires no hook;
- `outputSchema` is the shape of the final message, not a tool call.

**Isolation and effects:**
- An overlay mounts over 300k files in 13 ms and lists its changes in 12 ms, without root, in lup's container (kernel 7.2).
- A git snapshot per command costs about 50 ms at lup's size, 0.4–0.8 s at 100k files, and 1.4–2.8 s at 300k.
- Judging after the fact misses three things:
  - background writers (a process detached with `setsid` escapes);
  - files git ignores;
  - code that runs inside the same call (a planted `core.fsmonitor` ran).

**Package age gates:**
- uv's `exclude-newer` accepts "3 days" (`UV_EXCLUDE_NEWER`);
- bun 1.3.14 has `minimumReleaseAge`;
- pacman needs a dated Arch Linux Archive mirror (not verified).

**From the downstream projects:**
- **aib:**
  - tool names in prompts must be exact (`mcp__x__y`);
  - deferred tool schemas made the agent guess search terms;
  - `allowed_tools` auto-approves but doesn't restrict;
  - plan mode never submits structured output;
  - in its worst misses, the agent's own counterargument often held the right answer and was dismissed;
  - scores never moved attributably after the feedback loop's changes.
- **live-translator** needed five things: a provider switch, a timeout, a trace, a guarantee of no tools, and a fake for tests (stubbing one call took about 70 lines).
- **The art studio:**
  - `DISPLAY` set in the container breaks headless Chromium's WebGL;
  - the image had no fonts at all, which makes every CSS `@font-face` fail;
  - uv-managed interpreters weren't kept between containers;
  - pyright's `venv` name didn't match the contained environment's;
  - a pytest test root gave its files no test role;
  - xdist was looked up in the wrong environment.

## Open questions

The operator's to decide:
1. **Isolation between sessions:** leaning a worktree per agent with hardlinked environments. The write layer stays open, behind its two problems (see *Sessions*).
2. **Reflection:** the shape of the module.
3. **Upstream candidates:** their format and where a project declares them, and how often the adopting pass runs. Also keeping candidates and notes from piling up, as lup's issues did. The agent's proposal: reports are evidence attached to themes, so the open list counts distinct problems; a theme whose telemetry signal hasn't recurred since some lup version closes itself, and reopens if it comes back.
4. **The verbs** (tentatively settled), each named for what comes back, so the call site alone says whether the caller waits:
   - `ask(prompt, Output)` returns the answer while the caller waits, whether the target is a client with no tools, a turn in a conversation, or a room carrying a task to its end; the declaration decides tools and container, not the verb;
   - `spawn(prompt, Output)` returns a handle to a top-level session that outlives the caller and shows on the dashboard, the same thing the agents' spawn tool creates;
   - `launch()` gives a person a terminal session;
   - `open()` starts a conversation from code.

   `run` and `start` are dropped: with `launch`, they were three words for "begin". The cost: a call site no longer tells a quick question from a long task, so the target's name has to.
5. **Carrying the operator's preferences across containers,** or seeding from the personal config only.
6. **Native `Agent` for short jobs, beside lup's spawn:** leaning deny. To settle by measuring the new spawn, not today's lagging one: its start time and first request for a short worker, and whether a fork reads its parent's cache.
7. **A maintaining session as a room lup declares:** leaning yes, if nothing in maintaining falls outside what a room can declare.
8. **One overseeable place for a project, and who owns what in `pyproject.toml`** (for the declaration piece). The operator wants everything about a project in one place that's easy to oversee. Settled: the declaration declares the paths that are code, tests and excluded, and every tool's settings are compiled from it. Open:
   - **Dependencies.** (i) Declared in the declaration, which becomes the only source: `pyproject.toml` is compiled from it whole, `lup-dev add` resolves with uv and writes the result into the declaration, and plain `uv add` or a hand edit is refused by the drift test. Costs: a tool editing Python source, a changed habit, tools that edit `pyproject.toml` themselves (dependency bots) stop working, and a fresh project's first `pyproject.toml` comes from `lup new`. (ii) Left in `[project]`, uv's and the packaging standard's, with one overview (`lup-dev project`, then the dashboard) rendering everything about the project on one page: dependencies, paths, rule selection, protected paths, compiled settings. Costs: two sources behind one view. Leaning (ii), lightly.
   - **Where compiled tool settings go.** `pyproject.toml`'s `[tool.*]` sections (one file, where tools and editors already look, but compiled keys beside uv's), or each tool's own file (`ruff.toml`, `pyrightconfig.json`, …: compiled files apart from what uv edits, but several generated files at the root).
   - **Where the declaration lives.** A fixed `lup_project.py` at the project's root, found without a pointer (leaning), or a module named in `pyproject.toml` (`[tool.lup] project = …`).

**Still to discuss:**
- **The dashboard's design:** readability, lag, filtering auto-allowed files, keys and buttons, spawning, budget controls, and how the inbox's messages-as-reviews look and are answered (see *The dashboard*).
- **The CLI's naming:** answering a review is approving a request, not answering a question.
- **One standard for warnings and diagnostics:** the actionable part in a form that can be parsed, as with `uv run --with package`; code-rule findings take pyright's shape.
- **The one sentence for each core part and module,** once the library and environment split settles the list.
- **The guidance on fan-out,** and budget defaults that keep a day of work inside a week (leaning: no earlier compaction).
- **Codex specifics:** its question prompt, `task_name`, the content of the capability check.
- **A security review for downstream users:** age gates, sudo, mounts, egress, secrets (the runtime's login included), capabilities.
- **The design of the feedback modules.**
- **Moving the downstream projects onto the new lup.**
- **Why the gate and runs grew so large in time and memory.**

## Checks owed during the build

- Does a fork's first request read the parent's cached context?
- How fast does the new spawn start a short worker, and how large is its first request?
- Does the runtime's own sandbox run nested in the container, configured only to hide its login from the agent's commands?
- Can a hook rewrite a built-in tool's result before the model sees it, so a secret is scrubbed live and not only in saved transcripts? The docs say yes (`updatedToolOutput`); not yet tried.
- Does a maintaining session need anything a room can't declare?
- If the write layer is pursued: can it sit on a frozen snapshot with a hardlinked environment, can the host's view of it keep `.git` and editor configs out of reach until review, how does git behave inside it (commits, refs, merging back), and what does merging a layer back cost?
- Is Claude's native structured output a tool that hooks see? (Codex's isn't.)
- Does a `PreToolUse` hook's `allow` skip auto mode's classifier? No vendor doc says, and the first lup never measured it.
- Which of Claude Code's own commands use `Agent` internally, and would break when it's denied?
- Is the keepalive flag on for a subscription account?
- Does a dated Arch Linux Archive mirror hold against `pacman -Sy` in the image?
- How light can a REPL with freeze, fork and rewind be?

## Build order

The agent's proposal. How work is cut into branches is the agent's to do; this order is for the operator to correct.

**Phase 0, before the restart: only the disk.** Remove merged worktrees, and delete `.venv-contained` in the maintained projects' idle worktrees. The old lup isn't built on any further, so its flaky tests, its review leak and its waiting branches stay as they are; the session settings go in the operator's personal settings (DECISIONS.md, *Where to pick up*).

**Phase 1, in the new repository, built anew.** Nothing is copied from the old code, which stays readable as evidence.

**The bridge.** Until the new lup hosts itself, sessions run plain Claude Code with no lup plugin, and the operator reviews by hand. What burned the operator in manual review before lup: files that looked fine but carried a large design direction or a flaky decision (a regex in place of a parser), and a prompt for every decision, which wore review down into approving everything. What let them review where it mattered was approving whole new files, and the code rules pointing at the risky decisions. So the bridge (the agent's proposal):
- a short design note before the code of each piece (its modules, what each is for, its public API), approved in its pull request before implementation starts;
- a `permissions.ask` rule on `Write`, so every new file reaches the operator as a prompt, and no other prompts (it does prompt in auto mode, tested). Tentative: once the after-call diff is installed, its hook asks before a new file or a suppression lands, and this blanket rule goes;
- the code rules as early as possible, typed from the first rule, starting with those that catch a design decision (parsers over regex, `string-split`, `tuple-shape`, `set-shape`), as a hook in the build's own sessions; until they land, the first lup's checker runs as an asynchronous interim hook. Each suppression is asked of the operator as it's added, in place of a pull-request check listing them;
- one concern per branch. Branches land on `dev` once the gate passes, landed by the agent, with a merge commit whose message lists every design decision taken, its alternative and where it lives in the code, plus what changed and why, and how it was tested. The first lup's `dev` worked the same way. Earlier, each branch was a pull request into `main` that the operator merged;
- `main` protected on GitHub ("require a pull request before merging"), so no direct push reaches it. A release is a pull request from `dev` to `main` that the operator reviews and merges; `gh pr merge` asks;
- Codex works in the bridge too, reading the same `AGENTS.md` (`CLAUDE.md` imports it). Its declared gap: it has no per-tool prompt, so on Codex a new file doesn't reach the operator as a prompt, and the pull request names every new file instead;
- the after-call diff, once built, is installed in the build's own sessions as a plain hook, so the bridge shrinks as it's built.

The starting files (`AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, `.gitignore`) are staged in the old repository's `tmp/direction-research/day-one/`; this brief goes in as `DESIGN.md`.

1. **First the code rules and the allow policy, then the library's first slice.** The operator relies on the first two most, so they come back first.
   - Judging every write (`docs/judging-writes.md`), with its three outcomes (allow, ask, refuse), restored declines and saved versions, and the typed engine with the code rules (`docs/conventions.md`). It's the review workflow, every call goes through it, and its cost on a large repository (a git snapshot per command took 1.4–2.8 s at 300k files) is the main technical unknown.
   - The library: `Claude`/`Codex` with typed output, the fake agent and the test guard. live-translator can move to it at once, and the environment launches through it.
2. **The declaration and the CLI skeleton.** `Project` and its selections, a CLI that loads lazily, `lup new`, `lup docs`.
3. **Launch.** A container per session, mounts, secrets through host services, the harness compiled at launch, the session settings, native orchestration tools denied.
4. **lup's own tools.** Spawn, message, wait, ask, handoff; the one hook (hold and delivery); the roster; the ledger as the place for open work.
5. **Review.** Hardlinked worktrees, protected paths, merging back, and the dashboard with agents first and the inbox. **Milestone: the new lup hosts its own development**, and the bridge ends.
6. **Gates.** The rest of the code rules (each with its fixes: every finding at once, the refused version saved, each rule naming its reason), the gate's guards, updates and migrations, release, upstream candidates and the adopting pass.
7. **The rest.** In the library: runs (overhauled), rooms, the REPL and the outcome loop. In the environment: budgets, the feedback modules, the Codex adapter with its capability check, trust on launch.
