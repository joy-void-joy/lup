# lup: the design

lup is the operator's environment for developing projects with Claude Code and Codex, built on a library that any project whose code calls agents can use on its own. This document is the design as it stands, and it's the operator's: changing it is a design decision. Items not yet confirmed by the operator are marked **(leaning)**; anything undecided is under *Open questions*. Facts that were expensive to learn are in `docs/field-notes.md`, and what was tried and left behind, with why, in `docs/graveyard.md`. Each piece's detail is in its note under `docs/`.

## Purpose

lup serves two parties, and is judged by how well it works for both:
- **The operator** steers early, sees every agent and everything waiting on them in one place, and reviews what matters before it lands.
- **The agents** spend their effort on the task, not on the environment. They know what's theirs to decide and where the walls are, they can say when something is wrong, and they're asked how the work felt so the environment keeps improving.

It isn't a framework prescribing how agents work. An agent gets a room with walls and room to work, not a corridor.

**What lup must not become:**
- **Instructions that pull against each other.** Guidance, skills, hooks and the runtime's own prompt say one thing, which every session resolves the same way.
- **A system no agent can hold.** The whole may be larger than an agent can hold, as long as each part can be held on its own, stated in one sentence.
- **The work that pulls side work toward itself.** In a project, lup is small, fast and quiet; when lup is in the way, the project fixes it locally and tells lup (*How lup reaches a project*).

**Who uses it, and for what:**
- **Maintaining a project** (two private projects, and lup itself): sessions with gates, branches and reviews.
- **Doing a project's work in a room:** an art studio making art with code; an audiobook pipeline producing a book's audio with a few tools and free rein over its code; a research project running parallel investigations; nori's certificate-search campaigns.
- **Calling agents from code:** live-translator's quick typed call with no tools; aib's forecasts, whose outcomes come back later to compare versions.

## Architecture

### Two packages: the library and the environment

One repository, a uv workspace, three packages, dependencies running one way:
- **`lup`, the library:** what a project's production code imports.
- **`lup-dev` (`lup_dev`), the environment:** what a project uses only while it's being developed. It ships the one command, `lup`. A session it launches is a library launch with more attached.
- **`lup-dashboard`, the dashboard:** the one part with its own stack, behind a typed protocol.

The library never imports the environment, and the environment never imports the dashboard. Python 3.14 or later, for its lazily evaluated annotations. Each runtime is an extra (`lup[claude]`, `lup[codex]`), since each SDK ships its runtime's binary; `lup[testing]` brings the fake and the guard.

### The library

**One construct runs through it: the declaration of an agent.** `Claude(...)` or `Codex(...)` is a frozen model, and compiles two ways: to SDK options for code, and to a command line and environment for a terminal. Every way an agent starts goes through it: `ask` from code, `spawn`, `lup launch`, lup's spawn tool, a maintaining session.

```python
translator = Claude(model="opus", system_prompt=PROMPT)
result = await translator.ask(segment.model_dump_json(), Translations)   # TurnResult[Translations]

async with translator.open() as session:                                 # a fresh session each time
    await session.ask("Now in German", Translations)

narrator = Room(agent=Claude(model="opus"), container=Container(image="studio", mounts=[...]))
episode = await narrator.ask(f"Narrate {chapter}", Episode)              # waits
job = await narrator.spawn(f"Narrate {book}", Episode)                   # outlives the caller
narrator.launch()                                                        # a terminal in the same room
```

- **Asking (`docs/library.md`):**
  - `ask(prompt, Output)` returns a `TurnResult[T]` (`output`, `usage`, `duration`, `session_id`, `rejected`, `notes`). A failure is always an error, classified from what the runtime reports in structured form, never from message text.
  - **Typed answers come through `submit`,** an ordinary lup tool whose input is the output model, on both runtimes. Validation and its `before` hooks (`Submit(Forecast, before=[cites_sources])`) refuse an answer with the reason, and the agent corrects it within its turn. A typed turn can't end until an answer is accepted or a problem reported: lup's own guard, a stop hook on one runtime and a continuation on the other.
  - **Every agent can speak to whoever asked, through lup's speaking tools.** They act on nothing, so they're served even where an agent has no other tool:
    - `report(problem)` stops without an answer and says what's wrong; `ask` raises `ProblemReportedError` with the agent's words;
    - `note(remark)` attaches an assumption, doubt or counterargument to the answer, read in `TurnResult.notes`.
  - **Layers,** one field on the declaration: timeout, recovery (retrying an unavailable runtime, on tenacity), submission (attempts), trace (one `CallRecord` per ask, in full). **(leaning)** A wait for a spent usage window to reset, on by default and bounded by the timeout.
  - **What an ask can do is a guarantee about what can happen:** an ask from code can't run commands, touch files, reach the network or start agents; it can only call lup's tools. Each adapter configures its runtime for it and checks it on every call where the runtime lets it.
  - **Out of the operator's history:** calls from code persist no session and load no user settings.
  - **(leaning)** Model ids are checked types with portable tiers, and an effort a model can't take is refused at declaration.
- **Sessions (leaning):** `async with agent.open(resume=None)` gives a fresh session. `session.ask()` returns a lazy `Turn[T]`: awaited for its result, iterated for its content, with `live()` and `interrupt()`. An ability only one runtime has is a type (`steer()` exists only on Codex's turn). History comes from the runtime's own record; lup's writer keeps the copy with secrets scrubbed. A refused resume raises. On Codex, a conversation declares its output types when it opens, since a thread's tools are fixed when it starts.
- **Tools:** `@lup_tool` makes a typed async Python function a tool, with `before` hooks. Where it runs is declared on the tool: `runs="inside"` (the default) is the agent's side of the wall, which with no container is the caller's process; `runs="outside"` is the caller's process on the host, the deliberate openings in the wall (`submit`, publishing, anything needing a credential). lup serves its tools through its own MCP server, so its handler sees and counts every call. **(leaning)** A large result is written to a file and the agent gets its path and a preview; a tool server can be kept out of tool search; a third-party MCP server can be passed through.
- **Rooms (leaning):** a room wraps an agent with a wall: `Room(agent=…, container=…)`. Both are `Agent`s with the same verbs, so swapping runtimes is one field and `lup launch claude audiobook` picks the runtime at launch. A room's image is built with the project installed. Its own toolkit is the image's CLIs and scripts, which the agent runs and may extend. Publishing stays outside the room, in host code.
- **Runs (leaning):** durable work in a directory that can't report the wrong run:
  - one subdirectory per run with a `current` pointer swapped atomically, so a reader never sees another run's files;
  - `open()` mints the run's id and writes `starting` before any slow pre-work; a refused pre-work records its ending under that id;
  - one append-only event log per run, from which state, counts and the ending are derived;
  - every unit ends in a typed record (landed, failed, killed with its deadline and last report, abandoned, reused), and reuse is per unit, by its own fingerprint;
  - a follower pins the run's id when it attaches;
  - a unit reports progress, a run can carry its own detail model, and a unit can wait on other units and on an inbox answer.
- **Also:** typed events for anything long-running, which the dashboard follows; `SharedBudget` for request rates, local or across processes; the outcome loop (a module, below); the fake agent and the guard (`lup.testing`).
- **Delegation from code** is a nested call through the client, or lup's spawn.
- **Auth:** the CLI login by default; a product other people use declares an API key.

### The environment: core and modules

**The core** is what every module talks through, small enough to hold alone:
- the declaration (`lup_project.py`) and its modules;
- the one hook, which maps each runtime's events onto a few neutral ones;
- **one host service,** taking typed requests over a socket mounted into each container, with modules registering handlers: spawn's launcher, credential actions, secrets, host companions, budget control, the dashboard's backend;
- **the inbox,** one per party (*Sessions*);
- the dashboard's protocol;
- **(leaning)** launch, judging writes and worktrees are default modules rather than core (*Open questions*).

**Modules,** each one line to drop, each with its sentence:
- `Python`: how a Python project is run, tested and checked: the runner, test roots, the gate's Python steps, lup's settings for ruff and pyright.
- `CodeRules`: lup's rule selection and exemptions.
- `coordination` (requires `ledger`): the roster, which fills itself, and handoffs.
- `ledger`: the one place for open work, a view over what exists (GitHub issues, the inbox, handoffs, the felt notes).
- `git-workflow`: landing, pull requests, and checking a merge resolution kept both sides.
- `budgets` (requires `accounts`): shares, pace, pauses and spawn caps.
- `accounts`: logins, kept in step across containers when one renews; usage windows and their bars on the dashboard; downloading conversations from claude.ai and ChatGPT. The browser and its cookies stay on the host.
- `setup`: the integrations a project declares, set up from the command line or a dashboard pane, their secrets kept in the host's secret store.
- `release`: version bumps and the release flow.
- `resolver` (likely requiring `git-workflow`): open work grouped into concerns, each approved by the operator, worked in its own worktree, merged onto one branch and rechecked: a planner plus a run.
- `tracked-repositories`, `meta`: *Open questions*.
- the outcome loop, off by default, for graded projects: attaching outcomes to runs, grouping runs into arms, comparing them; the project decides what success is.
- reflection, requiring the outcome loop: *Open questions*.

**Modules may depend on modules, declared** (`requires = [Accounts]`). The loader refuses a selection missing a module that another requires, whether it was dropped or never added, naming both, and refuses a cycle: it never adds or drops a module behind the project's back; dropping each module is tested together with whatever requires it.

**Everything is a selection, never an on/off switch.** At every level (modules, rules, commands, skills, hooks), a project starts from lup's defaults and changes them with one grammar: `Kind.default()`, `.all()`, `.only()`, `.of()`, then `.add`, `.drop`, `.replace`, and `.edit` on modules, each change carrying its reason where given (`docs/declaration.md`). Whatever a shared base or a project writes is a layer on what's below it, naming only what it changes (`docs/declaration.md`, *The verbs on modules*).

**A project extends anything lup declares as easily as lup declares it:** a project's module is a `Module` subclass written as lup's are, filling the same kinds (rules, commands, path roles, protected paths, rooms, panels). lup's defaults are its own modules, declared through the same surface, and lup's repository declares its own specifics in its own `lup_project.py`.

### How lup reaches a project

- **A project holds its code, a dependency on lup, and one declaration,** `lup_project.py` at its root (or the package `lup_project/`), found without a pointer (`docs/declaration.md`).
- **Paths have roles** (code held to lup's rules, ruff and pyright; tests to ruff and pyright; excluded; protected), and lup's settings for ruff and pyright are generated from them into lup's own files (`.lup/settings/`), which the project's `pyproject.toml` extends by one pointer per tool. lup never writes the project's `pyproject.toml` after `lup new`; the gate fails when lup's files are stale.
- **Requirements:** each module declares the tools it needs from outside the project's environment; they're checked all at once when a session launches and when the gate runs, a missing one named with its module and how to install it.
- **Nothing of lup is copied into a project.** Runtime trees (`.claude/`, `.codex/`) are built at launch and never committed; lup's docs are served from the installed version (`lup docs <topic>`).
- **One CLI, `lup`,** built from the selected modules' commands, loading only the command invoked. A project's published commands are its own `[project.scripts]`.
- **`lup new <name>`** makes a project that passes the gate as made.
- **Precedence:** lup's default, then the person's config (`~/.config/lup/config.toml`: accounts, theme, budget shares, the projects on this machine), then the project, then an argument.
- **Releases only, never pins to branches.** An update is a version bump plus migrations, stopping only for what a person must decide.
- **When lup is in a project's way,** the project fixes it locally, through its declaration or its own code, and declares an upstream candidate beside the fix: the friction, the fix, the evidence, the lup version. The adopting pass, run in lup's repository when the operator starts it, designs overlapping needs as one construct; the release that adopts a candidate ships a migration removing each project's local fix. Nothing waits on adoption. **(leaning)** A defect in a component lup doesn't own (a runtime, a tool) is declared the same way, as a report ready to file with its vendor.
- **The README says how to use lup and what each module does;** sample applications live in `examples/`.

### Sessions

- **Two roles:** maintaining a project, or doing its work in a room. **(leaning)** A maintaining session is itself a room lup declares, with the gate and git in its toolkit, code rules as its hooks, and a worktree as its mount.
- **lup's spawn replaces the native `Agent` tool, on both runtimes.** Every worker is a top-level session with its own identity, budget share and place on the dashboard, under the agent that spawned it. A spawn returns the worker's hand-back in the same call or leaves it detached. Work in another project is spawned there, under that project's declaration, by the host service. A worker's hand-back is typed: its result and `how_it_felt: str`, which its turn can't end without.
- **Native tools for an agent's own work** (Edit, Read, Bash, `apply_patch`, search, web, its own task list, skills); **lup's tools for everything between agents, and between an agent and the operator** (spawn, message, wait, ask, propose, and the speaking tools). The native `Agent`, messaging and worktree tools are denied by default. **(leaning)** Code-intelligence tools for an agent's own work: find references, rename a symbol, hover, go to definition.
- **Approval: the agent proposes, and nothing builds on an unapproved design.** An approval costs the agent nothing it notices, however many there are; it costs the operator only the attention the decision needs. A design that relies on there being few approvals for the agent's comfort is the wrong design.
  - Writing uses the native tools: a new file lands where it belongs, so its tests can import it.
  - `propose(paths, why, wait)` puts a coherent design before the operator, with the agent's reasons. With `wait`, the call holds until answered; without, the answer reaches the agent through its inbox at its next call.
  - What needs a proposal: a new production file, a whole-file overwrite, a public-API change, an added suppression, a protected path. Suppressions and protected paths hold at the edit itself.
  - **The dependency guard:** an edit that imports or uses an unproposed design is refused ("propose `a.py` first"); one that uses a proposed design still waiting is held until it's answered. The agent chooses when to propose, never whether. It applies where the code rules do, by path role: tests, scratch, docs and data use an unproposed design freely, so a design can be tested before it's proposed.
  - At the end of a turn, unproposed design changes are listed; landing refuses a branch with one, or with one declined.
  - A held call is invisible to the agent: it returns once answered, with the operator's comment. A hold under an hour keeps the cache; past it, the context rebuilds, and no loop re-enters a wait to keep it warm.
  - The dashboard shows each agent's unproposed work as it forms, as "in progress, not asking you"; stepping in is the operator's choice. The verdict log records how much code preceded each proposal.
  - **(leaning)** A declined proposal stays in the worktree for the agent to revise; the guard keeps anything from being built on it.
- **The inbox:** every party has one, the operator and each agent.
  - Everything that wakes someone lands in an inbox, with its reason: a message, a proposal's answer, a worker's result, a reminder, a timer. A hold is a wait on one's inbox.
  - Messages are received at the next tool call, through the one hook, or with a blocking wait. Each answer is told once, never again.
  - Batching bursts and not talking over the operator are rules of how an inbox delivers, built so they can't starve replies. Reminders and follow-ups are lup tools, cancelled when the operator speaks.
  - The operator is a peer on the roster: telling them something is a message with a `kind` (question, disagreement, note, problem). Notification channels reach them away from the dashboard.
- **Coordination is light:** the roster fills itself from what each session does, and conflicts are found when writes merge, not through locks.
- **Session settings,** declared defaults a project can change: workers get the 1-hour prompt cache; unused built-in tools are removed from context; auto memory is off on both runtimes; compaction stays at the runtime's default.
- **Isolation between sessions:** a worktree per agent, environments hardlinked from a cache (*Open questions*).

### Budgets

Shares per project or agent over a time window; a pace limit for unattended runs, so usage stays under the window instead of hitting it; pausing low-priority agents through the spawn hierarchy; caps on how much a subtree may spawn; an automatic resume when a window resets. It runs as handlers of the host service, reading usage windows from `accounts`. Throttling trades time, not tokens.

### Policy

- **What the wall is for:** it keeps untrusted code (a compromised dependency, or an agent that's prompt-injected or just wrong) from damaging the host, so that commands inside it run without prompts. It also gives every agent the same standard machine, whatever the host is: bash and the usual tools, none of the operator's own shell setup. It isn't there to contain the agent: the judge steers, it doesn't guard.
- **Walls, protected paths and proposals; no verdicts on commands.** Inside the container a command simply runs. Effects that can't be undone are stopped by a wall where they pass.
- **Every write is judged by what it produces,** whichever tool made it: code rules on the native file tools before they land, and on everything at the gate. No command's spelling is parsed.
- **lup allows, holds for a proposal, or refuses:**
  - **allow:** tests, scratch, docs and data at any size, and any production edit the rules pass;
  - **proposals** (*Sessions*): a change to the design waits for the operator, so they understand the codebase's design and redirect early;
  - **refuse:** a code rule's finding, or an edit built on an unproposed design.
  - Every verdict is logged (tool, path, outcome, reason), so how often lup intervenes can be measured and tuned.
- **A container is required whenever an agent can run code or write files.** Interactively without a container engine there's no lup policy, only the runtime's own permission mode, behind an explicit `--dangerously-…` flag; from code, a call with Bash and no container raises unless it sets a `dangerously_…` flag. Mounts are one declaration: bind mounts in a container, the file tools' allow-list without one.
- **Leaving the wall is a request with a typed reason** (tentative; the reasons are open): work in another project (spawned there); credentials (a host service doing one action without asking, within limits the declaration sets, such as no push to `main` and no force push); a protected path (a proposal); a tool or device the container lacks, or repairing the environment (a reviewed command on the host); anything else (always reviewed). An answer can be scoped to the session and the reason; a reason that keeps recurring surfaces as what the room's declaration lacks; a launch reports what the host has that the container doesn't.
- **(leaning) Open egress,** with nothing secret mounted but the runtime's own login, hidden from the agent's commands. Project secrets live in host services the container reaches by name; pushes happen from the host. Saved transcripts and traces are scrubbed of known secret values, each replaced by its name.
- **(leaning) Sudo in room modes;** inherited capabilities always cleared; package installs held to a minimum age.
- **Protected paths:** the project's declaration and the rule tables its modules name; lup's settings files (a write equal to what the declaration generates is allowed); dependency manifests and lockfiles; what runs outside the container (CI, git hooks and `.git/config`, pre-commit, editor and devcontainer configs); what widens the wall; secrets (not even readable); in lup itself, its policy and launch code.
- **Reviews happen before, by default.** Examples, docs and guidance are reviewed after: they land, the operator is told, and one step reverts them.
- **Trust on launch:** the host-zone fingerprint, the review at launch (in the terminal until the inbox, then wherever the inbox is answered), and launching from the approved copy (`docs/launch.md`, *Trust on launch*). The installed judge gets the same: refreshing it shows its diff since the copy the operator last approved.

### Code rules and the gate

- **Code rules steer an approach at the moment it's chosen.** Each rule has a timing:
  - **at the edit,** the rules that pick an approach other code gets built on (parsers over regex and splitting, named fields over tuples and sets, the library for each job, errors and types, suppressions, truncation, historical voice): refused before the write lands, since code gets built on the mistake;
  - **at the gate,** the rules about how a correct thing is spelled (`elif`, collection loops, private names, docstring code, constants' homes): reported once before landing, fixed silently where ruff has a fixer. A gate rule still blocks landing.
- **A refusal reports every finding in the file at once,** like pyright: path, line and column, the rule, why it exists, and the fix. The refused version is saved at a path the refusal names; nothing is resent whole.
- **Each rule names the design mistake it prevents and where it steers.** A rule that can't name one goes; a rule that misfires is that rule's bug, rewritten until it fires only where a design choice is at stake.
- **Rules read one typed tree:** each file parsed and type-checked once, with pyright's own tree at a pinned release (`docs/judging-writes.md`). The conventions they enforce, and which tool owns each, are in `docs/conventions.md`.
- **`# lup:` comments are one grammar:** a directive is a call (`# lup: ignore("tuple-shape", why="…")`), anything else a note. Every rule accepts `ignore`; adding one is a suppression the operator reviews. `defer` points at a GitHub issue or a condition the gate can check.
- **Tests are exempt from code rules,** by the declared test roles. A project writes its own rules in a table one of its modules names, as lup's are (`lup rules new`, `lup rules check`).
- **Tests stub every agent and network call;** the library ships the fake and the guard. **No flaky tests:** a test that fails and then passes is a failure to fix; tests depending on the real clock or wall-clock timing are refused; a unit test over about 10 s fails the gate unless declared slow with its reason.

### The gate

One command, judged by its exit code: lup's rules, ruff, the formatter, pyright, the tests and the import contracts. `--changed` compares against the branch's own base; a nested project's tests run in its own environment; it stays bounded in time and memory.

### Runtimes

- **Codex is a peer.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Everything above the runtime contract is shared, so features are on both runtimes by construction.
- **What lup needs from a runtime is small:** launching in a container with lup's tools and guidance; one hook that holds a call and delivers waiting messages; a transcript reader for telemetry and cost; optionally, an interrupt.
- **Capabilities are declared per runtime,** and a short real session checks them whenever an installed CLI's version changes, cached per version. A feature needing a missing capability is unavailable on that runtime, and the launch and the docs say so. A guarantee is checked against what the runtime can actually do: Codex's code-mode models keep the no-tools guarantee: their `exec` reaches no shell, files, network or agents (checked on 0.162; `docs/field-notes.md`), and the check is owed again on each version.

### Calling agents from code

*The library*, above, is the design; `docs/library.md` holds the first slice's detail. The client is the declaration; a room has the same shape; one declaration compiles to SDK options for code and to a command line for a terminal. Rooms and anything long-running appear on the dashboard and fall under budgets; a quick call with no tools records only its cost. Sessions started from code run under their own config home where they're kept, so they never appear among the operator's own.

**(leaning) A persistent REPL** for agents run from code and in rooms, inside the wall, which can freeze, fork and rewind its state, and stays light.

### The dashboard

- **The main place of interaction,** including spawning sessions, behind a typed protocol so the page can be redesigned without touching the rest. It ships prebuilt, so no project builds its stack.
- **The first screen is the agents,** as a tree: what each is doing, what it waits on, its spend, with its proposals and questions underneath.
- **The operator's inbox:** proposals, questions, problems and messages as one mechanism. The operator sees every waiting item at once, comments on lines, agrees with a stated lean, answers several at once, and leaves some for later. Numbered decisions show as separate items answerable "leaning", "undecided" or "leave open".
- **Modules extend it with code:** a module ships its own panel, loaded at runtime, getting data through the typed protocol (TypeScript types generated from the pydantic models) and lup's exported components; lup's own panels (agents, inbox, runs, setup, usage) use the same API. Declared views (a table, a progress bar) are a shortcut built on panels. A panel runs sandboxed, with a token scoped to its module's data.
- **Runs** announce themselves and show their identity, plan, ETA, history, each step's progress, and each unit's state, deadline, last report, ending and log.
- **Controls:** budgets, pause, pace, spawn caps. **(leaning)** Steering beyond pause: interrupt, redirect, stop, and reading an agent's transcript.
- **Every key is also a button or a menu entry, and every view has a command-line counterpart** (`lup inbox` for the inbox), for answering from any terminal, over SSH, or when the dashboard is down.

### Feedback

- **"How it felt": core, on by default.** Every worker's hand-back carries it, and every main session's end-of-task report ends with it: what was smooth, what got in the way (the exact command and message), what you'd change. "Nothing notable" is a fine answer. Notes go to the ledger and serve as the evidence of upstream candidates.
- **Telemetry is attached automatically:** refusals and recurring messages, errors and retries, cache rebuilds, cost. A pooling pass, run on demand, groups repeats, links or files issues, and ranks by frequency and cost; it looks hardest at what telemetry can't see, mainly moments when an agent wasn't sure a decision was its to make.
- **The outcome loop and reflection** are modules (*The environment: core and modules*).

### Footprint and cleanup

lup cleans up after itself: containers, images (retired with their checkout) and volumes; environments in idle worktrees; merged worktrees nobody holds; run outputs, bounded; trace archives, deduplicated; git objects, collected. Environments hardlink from a cache on the same filesystem.

### Guidance and skills

- **Every gate, rule and hold names why it exists and where it steers:** one line in each refusal, the full reason in the docs.
- **Guidance gives each rule with its reason,** says what's the agent's to decide, what's the operator's and where the walls are, contradicts neither the runtime's own prompt nor any skill, and is written once the system it describes exists.
- **The operator likes numbered questions in plain text,** each with a stated lean; the structured question tool is for a quick single choice.
- **Skills are reference:** what the work is for, what good output looks like, the known traps; fixed steps only where the order is mechanical.
- **One template serves lup and the projects using it,** with the project's own section and lup's, rendered with Jinja.

## Open questions

The operator's to decide; the agent's lean where it has one.
1. **Isolation between sessions.** Leaning a worktree per agent with hardlinked environments. A write layer isn't ruled out, behind two problems: overlayfs leaves its lower layer undefined while mounted, so a layer can't sit on the live checkout; and showing a layer on the host exposes what the agent wrote there to the operator's editor before review.
2. **The core's size.** Lean: launch, judging writes and worktrees as default modules, the core being what every module talks through.
3. **`tracked-repositories`.** Lean: the registry is the core's, in two layers: the person's config maps names to paths on this machine, the project's declaration names what it reads or mounts; per-machine facts (devices, the difftool) go in the person's config or the room's declaration; the first lup's `sync` commands go.
4. **`meta`.** Lean: each kind's authoring tool lives with its kind (`lup rules new` in `CodeRules`).
5. **Reflection:** the shape of the module, which records data from each run for the outcome loop.
6. **Upstream candidates:** their format, where a project declares them, how often the adopting pass runs, and keeping candidates and notes from piling up. Lean: reports are evidence attached to themes, so the open list counts distinct problems; a theme whose signal hasn't recurred since some version closes itself. The adopting pass needs a name that isn't `sync`.
7. **Waking a main session whose turn has ended:** a hold past the hour rebuilds the context, keepalive loops are declined, and Codex can't hold a turn open.
8. **Native `Agent` for short jobs, beside lup's spawn.** Leaning deny; to settle by measuring the new spawn's start time and first request for a short worker, and whether a fork reads its parent's cache.
9. **Carrying the operator's preferences across containers,** or seeding from the personal config only.
10. **The verbs** (tentatively settled), each named for what comes back: `ask` returns the answer while the caller waits, whatever the target; `spawn` returns a handle to a session that outlives the caller; `launch` gives a person a terminal; `open` starts a session from code.

**Still to discuss:** the dashboard's design (readability, lag, filtering, keys and buttons, spawning, budget controls, how the inbox's items look and are answered); the CLI's naming; one standard for warnings and diagnostics, with the actionable part parseable; guidance on fan-out, and budget defaults keeping a day of work inside a week; Codex specifics; a security review for downstream users (age gates, sudo, mounts, egress, secrets, capabilities); the feedback modules' design; moving the downstream projects onto lup; why the first lup's gate and runs grew so large in time and memory.

## Checks owed

- Does a fork's first request read the parent's cached context? How fast does lup's spawn start a short worker, and how large is its first request?
- Does the runtime's own sandbox run nested in the container, configured only to hide its login from the agent's commands?
- Can a hook rewrite a built-in tool's result before the model sees it (`updatedToolOutput`), so a secret is scrubbed live?
- Does a maintaining session need anything a room can't declare?
- Does a `PreToolUse` hook's `allow` skip auto mode's classifier? Which of Claude Code's own commands use `Agent` internally, and break when it's denied?
- Do parallel held calls in one response reach the operator as one proposal?
- Can a Codex hook hold an `apply_patch` that builds on an unapproved design?
- Does resuming an SDK session work on Claude Code's current version?
- Is the cache keepalive flag on for a subscription account? How light can the REPL be?
- If the write layer is pursued: a frozen snapshot with a hardlinked environment, the host's view keeping `.git` and editor configs out of reach until review, git inside it, and what merging a layer back costs.

## Build order

Each step builds on the ones before it **(leaning)**:
1. **The library's first slice** (`docs/library.md`): asking either runtime from code, typed answers, the speaking tools, the layers, the fake and the guard. live-translator moves onto it.
2. **Tools and events:** project tools and where they run, large results to a file, tool search control, the events anything long-running emits.
3. **Rooms,** starting with the spike of the CLI inside a container.
4. **Runs,** built alongside any step; nori moves onto them.
5. **Launch on rooms,** with the parts of the declaration it reads (guidance, skills, session settings).
6. **The host service, the inbox, and lup's tools:** spawn, propose, message, ask, report.
7. **Worktrees and landing,** with the dependency guard and the landing refusal.
8. **The dashboard:** agents, the inbox, runs, panels.

**#56 pulls ahead (leaning)** what a maintaining session needs from steps 3, 5, 6 and 7, after the declaration's first slice (`docs/declaration.md`), in four pieces: launch on rooms, with the host service (`docs/launch.md`); lup's MCP server, the inbox and the credential actions; proposals and holds; the dependency guard. The rest of those steps keeps its place.

lup hosts its own development once steps 5–7 are done. Then: budgets, `accounts`, the feedback modules, the outcome loop, the resolver, setup, the Codex capability check.

**Already built:** the engine and its rules, the gate, and the judge, which is reshaped around proposals before it goes live again. The declaration is built only as large as the steps above need. **While lup is being built,** its own sessions run only the code rules at the edit, and only protected paths ask (`AGENTS.md`, *How work goes*); a piece of the environment goes live in lup's own sessions once it's finished.
