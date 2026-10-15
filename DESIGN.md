# lup: the design

lup is a set of modules for working with agents (Claude Code and Codex): a small library any project's code can call agents with, and an environment on the operator's machine where agents do a project's work and develop its code, each made of the modules a project selects. This document is the design as it stands, and it's the operator's: changing it is a design decision. Items not yet confirmed by the operator are marked **(leaning)**; anything undecided is under *Open questions*. Each module's sides and boundaries are in `docs/modules.md`, each piece's detail in its note under `docs/`, facts that were expensive to learn in `docs/field-notes.md`, and what was tried and left behind, with why, in `docs/graveyard.md`.

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
- **Calling agents from code:** live-translator's quick typed call with no tools; aib's forecasts, whose outcomes come back later to compare versions.
- **Doing a project's work with agents:** an art studio making art with code; an audiobook pipeline producing a book's audio with a few tools and free rein over its code; swarm-search's investigators sharing what they download, find and ask; nori's certificate-search campaigns.
- **Maintaining a project** (two private projects, and lup itself): sessions with gates, branches and reviews.

**Where it stands:** the downstream projects stay on the first lup until lup's modules and their ports are done, then each moves onto it (*Build order*). Until then lup's own maintenance is its first user, and each module is designed against the projects that will use it.

## Modules

**lup is modules all the way down.** Each module is one thing, said in one sentence, and a project takes the modules it uses and nothing more. lup's own parts are modules, declared through the same surface a project's are, so a project extends anything lup ships as easily as lup ships it.

### What a module is

A module has up to three parts (`docs/modules.md`, *The unit*):
- **a library side:** an API a project's own code imports. The ledger's is its store, on which swarm-search's code declares the kinds it records;
- **an environment side:** a `Module` a project selects in its declaration, giving the project's sessions what it brings: tools, commands, answers to the room's requests, what it does at the hook's events, guidance, skills, rules, gate steps, path roles, the room's packages, dashboard panels, and kinds of its own for other modules to fill. The ledger's gives sessions tools to record and read nodes, a `lup ledger` command and a panel;
- **its dependencies.**

A module may have one side only: the code rules are all environment, the test fake all library.

- **Packaging (the operator's):** lup is one monorepo, a uv workspace, each module a distribution of its own, all released together at one version. The two cores are packages requiring their modules (*The two cores*); every other module is an extra on them (`lup[ledger]` installs `lup-ledger`). A project, or anyone, publishes a module of its own exactly as lup publishes its.
- **What a project installs, and what its consumers download (leaning):** the project's `dependencies` list the modules its own code imports; its development group lists `lup-dev` and the modules only development needs. A consumer of the project downloads library sides alone: a module's environment side travels in its distribution but can't run without `lup-dev`, which never ships, and the modules that are all environment (the code rules and their engine, 38 MB) aren't there at all.
- **Two import contracts hold the line (leaning):** inside lup, a module's library side never imports an environment side, and a module imports only the modules it requires; in each project, its shipped code imports no environment side, a contract lup generates from the project's path roles for its gate.
- **Selected and installed (leaning):** the declaration selects environment sides; `pyproject.toml` says what's installed. A selected module that isn't installed fails the load, naming the extra to add, since lup never writes a project's `pyproject.toml` after `lup new`. An installed module the declaration doesn't select is fine: the project's code may use its library side while its sessions don't get its environment side.
- **Modules depend on modules, declared** (`requires = [Ledger]`). The loader refuses a selection missing a module that another requires, whether it was dropped or never added, naming both, and refuses a cycle: it never adds or drops a module behind the project's back. Dropping each module is tested together with whatever requires it.
- **A module can declare a kind other modules fill** (the operator's): the ledger declares node kinds, which coordination and a project's code fill; budgets will declare shares; judging a write is a kind every judging module fills. A kind a module declares exists only where that module is selected.
- **Nothing is built in** (the operator's): where lup runs a pipeline (judging a write, the gate, the guidance, the dashboard), the pipeline decides nothing itself. Everything it decides with comes from modules, lup's own included, and a project's module adds, drops or replaces any of it, so a project changes how its writes are judged or what its dashboard shows with a module of its own, never by forking lup.
- **How a module refers to code is open** (*Open questions*): string addresses in entry-point form (`"audiobook.tools:narration"`) until it's settled, as `docs/declaration.md` has them.
- **Everything is a selection, never an on/off switch.** At every level (modules, rules, tools, commands, skills, hooks), a project starts from lup's defaults and changes them with one grammar: `Kind.default()`, `.all()`, `.only()`, `.of()`, then `.add`, `.drop`, `.replace`, and `.edit` on modules, each change carrying its reason where given (`docs/declaration.md`). Whatever a shared base or a project writes is a layer on what's below it, naming only what it changes.

Python 3.14 or later, for its lazily evaluated annotations.

### The two cores

Each core is a package requiring a few modules, which every other module builds on and none can drop (`docs/modules.md`, *The cores*).

**`lup`, the library core:** what calling an agent from code needs, small enough that a product shipping it carries little. Asking an agent, typed answers, the speaking tools, tools and their serving, the layers, typed events, and each runtime as a module of its own (`lup[claude]`, `lup[codex]`), since each SDK ships its runtime's binary; `lup[testing]` brings the fake and the guard.

**`lup-dev`, the environment core:** what every environment module talks through, on the operator's machine:
- the declaration (`lup_project.py`) and its modules, with a person's own layer (`lup_project.local.py`);
- the one hook, which maps each runtime's events onto a few neutral ones;
- one host service, taking typed requests over a socket mounted into each room, with modules registering handlers;
- the inbox's delivery, to launched sessions and to the operator;
- launch and trust on launch. Trust approves a module's code before the host runs it, so it can't itself be a module; and the wall is policy, which a project configures through its modules but never drops;
- the limits on the operator's credentials, with git through the host;
- the pipelines modules feed: judging a write, the gate's runner, rendering the guidance, the dashboard's protocol.

**The dashboard** is a distribution of its own, the one part with its own stack, behind the typed protocol; the environment core never imports it.

### The modules

Each with its sentence; `docs/modules.md` holds each one's sides, what it requires, and what's still to discuss.

**Mainly library-side,** each with an environment face where it needs one (a panel, a command):
- `rooms` **(leaning)**: an agent behind a wall, with the same verbs as an agent (*Calling agents*).
- `runs` **(leaning)**: durable work in a directory that can't report the wrong run (*Calling agents*).
- `ledger`: one typed graph store per repository: nodes and edges of kinds declared by whoever uses them, each kind committed with the code or kept locally, a node's standing read from what points at it.
- `inbox` (requires `ledger`): one per party, the operator and each agent, each item told once; stored on the ledger; its delivery is the environment core's (*Sessions*). **(leaning)** Its mailboxes are a library side, so agents started from code message each other through it too.
- `coordination` (requires `ledger`, `inbox`): agents finding each other, sharing what they download, find and ask, and claiming work so none is done twice (*Sessions*).
- `budgets` (requires `accounts`): shares, pace, pauses and spawn caps (*Budgets*); `SharedBudget` for request rates across processes.
- the outcome loop, off by default, for graded projects: attaching outcomes to runs, grouping runs into arms, comparing them; the project decides what success is.
- reflection, requiring the outcome loop: *Open questions*.
- realtime: an agent present over time, sleeping and waking on events, every timing a tool.

**Environment-side:**
- `Python`: how a Python project is run, tested and checked: the runner, test roots, the gate's Python steps, lup's settings for ruff and pyright.
- `CodeRules`: lup's rule selection and exemptions, and their judgement of each write.
- `Proposals` **(leaning)**: `propose`, holds, and the dependency guard (*Sessions*).
- `spawn` **(leaning)**: lup's workers, which replace the native `Agent`, and isolation: a worktree for each agent, which it can move between with a tool.
- `git-workflow`: landing, pull requests, and checking a merge resolution kept both sides. It retires a worktree at landing through a hook, never requiring the module that made it.
- `GitHub` **(leaning)**: lup's GitHub tools, and the gate's issue states in a room, through `gh` on the host.
- `accounts`: logins, kept in step across rooms when one renews; usage windows and their bars on the dashboard; downloading conversations from claude.ai and ChatGPT. The browser and its cookies stay on the host.
- `setup`: the integrations a project declares, set up from the command line or a dashboard pane, their secrets kept in the host's secret store.
- `release`: version bumps and the release flow.
- `resolver` (likely requiring `git-workflow`): open work grouped into concerns, each approved by the operator, worked in its own worktree, merged onto one branch and rechecked: a planner plus a run.
- feedback, on by default: "how it felt", telemetry and the pooling pass (*Feedback*).
- `meta`: *Open questions*.

## How lup reaches a project

- **A project holds its code, its dependencies on lup's modules, and one declaration,** `lup_project.py` at its root (or the package `lup_project/`), found without a pointer (`docs/declaration.md`). Beside it, a person's own layer, `lup_project.local.py`, uncommitted, layered on top in the same grammar: which other repositories that person's sessions read, mounted read-only (`docs/related-repositories.md`), and any part they change for themselves.
- **Paths have roles** (code held to lup's rules, ruff and pyright; tests to ruff and pyright; excluded; protected), and lup's settings for ruff and pyright are generated from them into lup's own files (`.lup/settings/`), which the project's `pyproject.toml` extends by one pointer per tool. lup never writes the project's `pyproject.toml` after `lup new`; the gate fails when lup's files are stale.
- **Requirements:** each module declares the tools it needs from outside the project's environment; they're checked all at once when a session launches and when the gate runs, a missing one named with its module and how to install it.
- **Nothing of lup is copied into a project.** Runtime trees (`.claude/`, `.codex/`) are built at launch and never committed; lup's docs are served from the installed version (`lup docs <topic>`).
- **One CLI, `lup`,** built from the selected modules' commands, loading only the command invoked. A project's published commands are its own `[project.scripts]`.
- **`lup new <name>`** makes a project that passes the gate as made.
- **Precedence:** lup's default, then the person's config (`~/.config/lup/config.toml`: accounts, theme, budget shares, the projects on this machine), then the project, then the person's own layer, then an argument.
- **Releases only, never pins to branches.** An update is a version bump plus migrations, stopping only for what a person must decide.
- **When lup is in a project's way,** the project fixes it locally, through its declaration or its own code, and declares an upstream candidate beside the fix: the friction, the fix, the evidence, the lup version. The adopting pass, run in lup's repository when the operator starts it, designs overlapping needs as one construct; the release that adopts a candidate ships a migration removing each project's local fix. Nothing waits on adoption. **(leaning)** A defect in a component lup doesn't own (a runtime, a tool) is declared the same way, as a report ready to file with its vendor.
- **The README says how to use lup and what each module does;** sample applications live in `examples/`.

## Calling agents

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
  - **Out of the operator's history:** calls from code persist no session and load no user settings; sessions started from code that are kept run under their own config home, so they never appear among the operator's own.
  - **(leaning)** Model ids are checked types with portable tiers, and an effort a model can't take is refused at declaration.
- **Sessions (leaning):** `async with agent.open(resume=None)` gives a fresh session. `session.ask()` returns a lazy `Turn[T]`: awaited for its result, iterated for its content, with `live()` and `interrupt()`. An ability only one runtime has is a type (`steer()` exists only on Codex's turn). History comes from the runtime's own record; lup's writer keeps the copy with secrets scrubbed. A refused resume raises. On Codex, a conversation declares its output types when it opens, since a thread's tools are fixed when it starts.
- **Tools:** `@lup_tool` makes a typed async Python function a tool, with `before` hooks; it's the one way to write a tool, whether an ask from code, a room or a module serves it. Where it runs is declared on the tool: `runs="inside"` (the default) is the agent's side of the wall, which with no container is the caller's process; `runs="outside"` is the caller's process on the host, the deliberate openings in the wall (`submit`, publishing, anything needing a credential). lup serves its tools through its own MCP server, so its handler sees and counts every call. **(leaning)** Toolsets group tools in any file, and a tool reaches its module's settings, its caller and its launch through parameters typed with them (part of *Open questions*, how a module refers to code). **(leaning)** A large result is written to a file and the agent gets its path and a preview; a tool server can be kept out of tool search; a third-party MCP server can be passed through.
- **Rooms (leaning),** the `rooms` module: a room wraps an agent with a wall: `Room(agent=…, container=…)`. Both are `Agent`s with the same verbs, so swapping runtimes is one field and `lup launch claude audiobook` picks the runtime at launch. A room's image is built with the project installed. Its own toolkit is the image's CLIs and scripts, which the agent runs and may extend. Publishing stays outside the room, in host code. Rooms and anything long-running appear on the dashboard and fall under budgets; a quick call with no tools records only its cost.
- **Runs (leaning),** the `runs` module: durable work in a directory that can't report the wrong run:
  - one subdirectory per run with a `current` pointer swapped atomically, so a reader never sees another run's files;
  - `open()` mints the run's id and writes `starting` before any slow pre-work; a refused pre-work records its ending under that id;
  - one append-only event log per run, from which state, counts and the ending are derived;
  - every unit ends in a typed record (landed, failed, killed with its deadline and last report, abandoned, reused), and reuse is per unit, by its own fingerprint;
  - a follower pins the run's id when it attaches;
  - a unit reports progress, a run can carry its own detail model, and a unit can wait on other units and on an inbox answer.
- **Also:** typed events for anything long-running, which the dashboard follows. **(leaning)** A persistent REPL for agents run from code and in rooms, inside the wall, which can freeze, fork and rewind its state, and stays light.
- **Delegation from code** is a nested call through the client, or lup's spawn.
- **Auth:** the CLI login by default; a product other people use declares an API key.

## Sessions

- **Two roles:** maintaining a project, or doing its work in a room. **(leaning)** A maintaining session is itself a room lup declares, with the gate and git in its toolkit, code rules as its hooks, and a worktree as its mount.
- **lup's spawn replaces the native `Agent` tool, on both runtimes.** Every worker is a top-level session with its own identity, budget share and place on the dashboard, under the agent that spawned it. A spawn returns the worker's hand-back in the same call or leaves it detached. Work in another project is spawned there, under that project's declaration, by the host service. A worker's hand-back is typed: its result and `how_it_felt: str`, which its turn can't end without.
- **Isolation (leaning, *Open questions*):** each agent works in a worktree of its own, its environment hardlinked from a cache, and moves between worktrees with a tool; `spawn` holds both, and `git-workflow` retires a worktree when its branch lands.
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
- **The inbox:** every party has one, the operator and each agent, and agents message each other through the same inbox they ask the operator through.
  - Everything that wakes someone lands in an inbox, with its reason: a message, a proposal's answer, a worker's result, a reminder, a timer. A hold is a wait on one's inbox.
  - Messages are received at the next tool call, through the one hook, or with a blocking wait. Each answer is told once, never again.
  - **Stored on the ledger:** an item is a node, and its state (answered, told to whom) is read from what points at it.
  - Batching bursts and not talking over the operator are rules of how an inbox delivers, built so they can't starve replies. Reminders and follow-ups are lup tools, cancelled when the operator speaks.
  - The operator is a peer on the roster: telling them something is a message with a `kind` (question, disagreement, note, problem). Notification channels reach them away from the dashboard.
  - **What goes where:** what's addressed to a party and told to them once is an inbox item; what's recorded to be found later, by anyone, with a standing others' answers change, is a ledger node. A question to one peer is a message; a question put to a swarm is a node. Open work is a pointer to a GitHub issue.
- **Coordination, with no file locks (leaning)** (`docs/modules.md`, *Coordination*). Agents get in each other's way in four ways, and each has its own answer:
  - **records and downloads** go to the ledger: nodes are append-only and downloads content-addressed blobs, first writer winning, so nothing shared can be overwritten; fetching what's been fetched, or is being fetched, returns that;
  - **files in a working tree** stay in each agent's worktree. When two live sessions change one file, both are told at once, each naming the other, rather than at merge. An advisory claim covers the one case watching writes comes too late (a whole package about to be rewritten): writing under someone else's claim says who holds it, and is never refused;
  - **shared outside resources** (a host's rate, an account, a device) have one owner: `SharedBudget`, or a module's handler on the host that agents request through;
  - **the same work twice** is prevented by claims on work (a lead, a question, a task), alive while their holder is on the roster.
  
  The roster fills itself from what each session does; what an agent says it's working on is one line it sets when it starts or changes work.
- **Session settings,** declared defaults a project can change: workers get the 1-hour prompt cache; unused built-in tools are removed from context; auto memory is off on both runtimes; idle compaction is off where a runtime has it, and compaction when the context fills is left to the runtime. A person's own runtime settings outrank lup's defaults, and a project's declared settings outrank theirs.

## Budgets

Shares per project or agent over a time window; a pace limit for unattended runs, so usage stays under the window instead of hitting it; pausing low-priority agents through the spawn hierarchy; caps on how much a subtree may spawn; an automatic resume when a window resets. It runs as handlers of the host service, reading usage windows from `accounts`. Throttling trades time, not tokens.

## Policy

- **What the wall is for:** it keeps untrusted code (a compromised dependency, or an agent that's prompt-injected or just wrong) from damaging the host, so that commands inside it run without prompts. It also gives every agent the same standard machine, whatever the host is: bash and the usual tools, none of the operator's own shell setup. It isn't there to contain the agent: the judge steers, it doesn't guard.
- **Walls, protected paths and proposals; no verdicts on commands.** Inside the container a command simply runs. Effects that can't be undone are stopped by a wall where they pass.
- **Every write is judged by what it produces,** whichever tool made it: before it lands where the runtime lets the hook see it, just after where it doesn't, and on everything at the gate. No command's spelling is parsed.
- **lup allows, holds for a proposal, or refuses:**
  - **allow:** tests, scratch, docs and data at any size, and any production edit the rules pass;
  - **proposals** (*Sessions*): a change to the design waits for the operator, so they understand the codebase's design and redirect early;
  - **refuse:** a code rule's finding, or an edit built on an unproposed design.
  - **Judging is a pipeline the modules feed, with nothing built in:** `Core` brings the protected paths, `CodeRules` its rules' findings, `Proposals` its holds and the dependency guard; a project's module adds a judgement of its own, or replaces one of lup's.
  - Every verdict is logged (tool, path, outcome, reason), so how often lup intervenes can be measured and tuned.
- **A container is required whenever an agent can run code or write files.** Interactively without a container engine there's no lup policy, only the runtime's own permission mode, behind an explicit `--dangerously-…` flag; from code, a call with Bash and no container raises unless it sets a `dangerously_…` flag. Mounts are one declaration: bind mounts in a container, the file tools' allow-list without one.
- **Leaving the wall is a request with a typed reason** (tentative; the reasons are open): work in another project (spawned there); credentials (a host service doing one action without asking, within limits the declaration sets, such as no push to `main` and no force push); a protected path (a proposal); a tool or device the container lacks, or repairing the environment (a reviewed command on the host); anything else (always reviewed). An answer can be scoped to the session and the reason; a reason that keeps recurring surfaces as what the room's declaration lacks; a launch reports what the host has that the container doesn't.
- **(leaning) Open egress,** with nothing secret mounted but the runtime's own login, hidden from the agent's commands. Project secrets live in host services the container reaches by name; pushes happen from the host. Saved transcripts and traces are scrubbed of known secret values, each replaced by its name.
- **(leaning) Sudo in room modes;** inherited capabilities always cleared; package installs held to a minimum age.
- **Protected paths:** the project's declaration, a person's own layer, and the rule tables its modules name; lup's settings files (a write equal to what the declaration generates is allowed); dependency manifests and lockfiles; what runs outside the container (CI, git hooks and `.git/config`, pre-commit, editor and devcontainer configs); what widens the wall; secrets (not even readable); in lup itself, its policy and launch code.
- **Reviews happen before, by default.** Examples, docs and guidance are reviewed after: they land, the operator is told, and one step reverts them.
- **Trust on launch:** what the host runs for a project (its declaration, a person's layer, the code they import, and the `lup-dev` the project pins) is approved before it runs, a summary first, in the inbox and at the launching terminal, and launched from the approved copy (`docs/launch.md`, *Trust on launch*).

## Code rules and the gate

- **Code rules steer an approach at the moment it's chosen.** Each rule has a timing:
  - **at the edit,** the rules that pick an approach other code gets built on (parsers over regex and splitting, named fields over tuples and sets, the library for each job, errors and types, suppressions, truncation, historical voice): refused before the write lands, since code gets built on the mistake;
  - **at the gate,** the rules about how a correct thing is spelled (`elif`, collection loops, private names, docstring code, constants' homes): reported once before landing, fixed silently where ruff has a fixer. A gate rule still blocks landing.
- **A refusal reports every finding in the file at once,** like pyright: path, line and column, the rule, why it exists, and the fix. The refused version is saved at a path the refusal names; nothing is resent whole.
- **Each rule names the design mistake it prevents and where it steers.** A rule that can't name one goes; a rule that misfires is that rule's bug, rewritten until it fires only where a design choice is at stake.
- **Rules read one typed tree:** each file parsed and type-checked once, with pyright's own tree at a pinned release (`docs/judging-writes.md`). The conventions they enforce, and which tool owns each, are in `docs/conventions.md`.
- **`# lup:` comments are one grammar:** a directive is a call (`# lup: ignore("tuple-shape", why="…")`), anything else a note. Every rule accepts `ignore`; adding one is a suppression the operator reviews. `defer` points at a GitHub issue or a condition the gate can check.
- **Tests are exempt from code rules,** by the declared test roles. A project writes its own rules in a table one of its modules names, as lup's are (`lup rules new`, `lup rules check`).
- **Tests stub every agent and network call;** the library ships the fake and the guard. **No flaky tests:** a test that fails and then passes is a failure to fix; tests depending on the real clock or wall-clock timing are refused; a unit test over about 10 s fails the gate unless declared slow with its reason.
- **The gate** is one command, judged by its exit code, running the steps the selected modules give it: lup's rules, ruff, the formatter, pyright, the tests and the import contracts for a Python project. `--changed` compares against the branch's own base; a nested project's tests run in its own environment; it stays bounded in time and memory.

## Runtimes

- **Codex is a peer.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Everything above the runtime contract is shared, so features are on both runtimes by construction.
- **What lup needs from a runtime is small:** launching in a container with lup's tools and guidance; one hook that holds a call and delivers waiting messages; a transcript reader for telemetry and cost; optionally, an interrupt.
- **Capabilities are declared per runtime,** and a short real session checks them whenever an installed CLI's version changes, cached per version. A feature needing a missing capability is unavailable on that runtime, and the launch and the docs say so. A guarantee is checked against what the runtime can actually do: Codex's code-mode models keep the no-tools guarantee: their `exec` reaches no shell, files, network or agents (checked on 0.162; `docs/field-notes.md`), and the check is owed again on each version.

## The dashboard

- **The main place of interaction,** including spawning sessions, behind a typed protocol so the page can be redesigned without touching the rest. It ships prebuilt, so no project builds its stack.
- **The first screen is the agents,** as a tree: what each is doing, what it waits on, its spend, with its proposals and questions underneath.
- **The operator's inbox:** proposals, questions, problems and messages as one mechanism. The operator sees every waiting item at once, comments on lines, agrees with a stated lean, answers several at once, and leaves some for later. Numbered decisions show as separate items answerable "leaning", "undecided" or "leave open".
- **Nothing on it is built in:** every panel is a module's, loaded at runtime, getting data through the typed protocol (TypeScript types generated from the pydantic models) and lup's exported components. lup's own panels (agents, inbox, runs, setup, usage) are its modules' and use the same API, so a project replaces one as it adds its own. Declared views (a table, a progress bar) are a shortcut built on panels. A panel runs sandboxed, with a token scoped to its module's data.
- **Runs** announce themselves and show their identity, plan, ETA, history, each step's progress, and each unit's state, deadline, last report, ending and log.
- **Controls:** budgets, pause, pace, spawn caps. **(leaning)** Steering beyond pause: interrupt, redirect, stop, and reading an agent's transcript.
- **Every key is also a button or a menu entry, and every view has a command-line counterpart** (`lup inbox` for the inbox), for answering from any terminal, over SSH, or when the dashboard is down.

## Feedback

- **"How it felt", on by default.** Every worker's hand-back carries it, and every main session's end-of-task report ends with it: what was smooth, what got in the way (the exact command and message), what you'd change. "Nothing notable" is a fine answer. Notes are recorded in the ledger and serve as the evidence of upstream candidates.
- **Telemetry is attached automatically:** refusals and recurring messages, errors and retries, cache rebuilds, cost. A pooling pass, run on demand, groups repeats, links or files issues, and ranks by frequency and cost; it looks hardest at what telemetry can't see, mainly moments when an agent wasn't sure a decision was its to make.
- **The outcome loop and reflection** are modules (*The modules*).

## Footprint and cleanup

lup cleans up after itself: containers, images (retired with their checkout) and volumes; environments in idle worktrees; merged worktrees nobody holds; run outputs, bounded; trace archives, deduplicated; git objects, collected. Environments hardlink from a cache on the same filesystem.

## Guidance and skills

- **Every gate, rule and hold names why it exists and where it steers:** one line in each refusal, the full reason in the docs.
- **Guidance gives each rule with its reason,** says what's the agent's to decide, what's the operator's and where the walls are, contradicts neither the runtime's own prompt nor any skill, and is written once the system it describes exists. Each module brings its own section; the guidance is rendered from the sections of the modules selected.
- **The operator likes numbered questions in plain text,** each with a stated lean; the structured question tool is for a quick single choice.
- **Skills are reference:** what the work is for, what good output looks like, the known traps; fixed steps only where the order is mechanical.
- **One template serves lup and the projects using it,** with the project's own section and lup's, rendered with Jinja.

## Open questions

The operator's to decide; the agent's lean where it has one.
1. **How a module refers to code:** string addresses in entry-point form, lazy by construction but unchecked by pyright, which the gate imports and fails on when one doesn't resolve; or real references (`Tools.of(narration)`), checked by pyright and followed by rename and go-to-definition, with the gate importing the declaration in a fresh interpreter and failing on anything heavy it pulls in, naming the chain (`docs/modules.md`, *How a module refers to code*). String addresses until it's settled.
2. **Isolation between sessions.** Isolation is `spawn`'s (the operator's). Leaning a worktree per agent with hardlinked environments, which an agent moves between with a tool. A write layer isn't ruled out, behind two problems: overlayfs leaves its lower layer undefined while mounted, so a layer can't sit on the live checkout; and showing a layer on the host exposes what the agent wrote there to the operator's editor before review.
3. **Shared state where no host runs (leaning):** the inbox's and coordination's library sides keep their stores in the repository's ledger, and reach the operator, the dashboard and budgets through the host service where one runs; agents started from code on a machine with no host still share and message, without the operator's inbox.
4. **`meta`.** Lean: each kind's authoring tool lives with its kind (`lup rules new` in `CodeRules`).
5. **Reflection:** the shape of the module, which records data from each run for the outcome loop. The first lup's was a different thing, a reviewer the agent's output met before it was submitted (`docs/modules.md`).
6. **Upstream candidates:** their format, where a project declares them, how often the adopting pass runs, and keeping candidates and notes from piling up. Lean: reports are evidence attached to themes, so the open list counts distinct problems; a theme whose signal hasn't recurred since some version closes itself. The adopting pass needs a name that isn't `sync`.
7. **Waking a main session whose turn has ended:** a hold past the hour rebuilds the context, keepalive loops are declined, and Codex can't hold a turn open.
8. **Native `Agent` for short jobs, beside lup's spawn.** Leaning deny; to settle by measuring the new spawn's start time and first request for a short worker, and whether a fork reads its parent's cache.
9. **Carrying the operator's preferences across containers,** or seeding from the personal config only.
10. **The verbs** (tentatively settled), each named for what comes back: `ask` returns the answer while the caller waits, whatever the target; `spawn` returns a handle to a session that outlives the caller; `launch` gives a person a terminal; `open` starts a session from code.

**Still to discuss:** each module's sides and boundaries (`docs/modules.md`, *To discuss*); the dashboard's design (readability, lag, filtering, keys and buttons, spawning, budget controls, how the inbox's items look and are answered); the CLI's naming; one standard for warnings and diagnostics, with the actionable part parseable; guidance on fan-out, and budget defaults keeping a day of work inside a week; Codex specifics; a security review for downstream users (age gates, sudo, mounts, egress, secrets, capabilities); the feedback modules' design; moving the downstream projects onto lup; why the first lup's gate and runs grew so large in time and memory.

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

**Built,** as two packages, `lup` and `lup-dev`, whose modules carry configuration only:
- the library's first slice (`docs/library.md`): asking either runtime from code, typed answers, the speaking tools, the layers, the fake and the guard, serving tools over MCP;
- the code rules' engine and the gate; the judge, before an edit lands, and after a call for what it can't see before (Codex's patches, the shell: the checkpoint, `docs/judging-writes.md`);
- the declaration's first slice (`docs/declaration.md`);
- launch on rooms with the host service, trust on launch, the inbox and lup's tools, git and GitHub through the host, related repositories (`docs/launch.md`, `docs/host-tools.md`, `docs/related-repositories.md`).

**Next, in order (leaning):**
1. **The module system made solid:** modules bring what they do (tools, commands, answers to the room's requests, what they do at the hook's events), declare kinds for others to fill, and feed the pipelines with nothing built in; the cores split into their modules, each a distribution; GitHub, git through the host, the inbox and the judge moved into their modules, each with its drop test.
2. **The bird's-eye view** (`docs/modules.md`): each module discussed with the operator until its sides and boundaries are settled. At its most cohesive, it gives the dependency graph, and the order of what follows.
3. **The modules rebuilt** in that order, each against the first lup's evidence: among them the ledger with the inbox on it, coordination, spawn with isolation, proposals and the dependency guard (replacing the checkpoint's holds), git-workflow, the dashboard and budgets.
4. **The downstream projects move onto lup,** each dropping its copy of the first lup.

**While lup is being built,** its own sessions run only the code rules at the edit, and only protected paths ask (`AGENTS.md`, *How work goes*); a piece of the environment goes live in lup's own sessions once it's finished.
