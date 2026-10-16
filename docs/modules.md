# Modules: the bird's-eye view

**One sentence:** every part of lup is a module, with a library side a project's code imports, an environment side a project's sessions get, or both, and this note is the map of them: what each holds, what it requires, and what's settled, leaning, or still to discuss.

It comes from the conversations of 2026-10-15 and 2026-10-16 between the operator and the sessions that wrote it, from the first lup's modules (lup-legacy, `packages/lup/src/lup/harness/content/modules/`), and from how the downstream projects used them. `DESIGN.md` (*Modules*) holds the shape; this note holds each module's detail until the module has a note of its own. Marks: **(decided)**, the operator's answer; **(to confirm)**, agreed in the conversation of 2026-10-16 and waiting for a confirming pass; **(leaning)**, proposed and not yet confirmed; **to discuss**, not yet talked through.

The order of work it serves (`DESIGN.md`, *Build order*): discuss each module until its sides and boundaries are settled; then, with the map at its most cohesive, read the dependency graph and the build order off it.

## The unit

A module has up to three parts **(decided)**, all in one directory of `lup` **(to confirm)**. Taking the ledger as the example, `lup/ledger/` holds:
- **`lup.ledger`, its library side:** the store. swarm-search's own code imports it to declare `Evidence`, `Claim` and its other kinds, and to record them;
- **`lup.ledger.environment`, its environment side:** the `Ledger` module a project selects in `lup_project.py`, giving its sessions tools to record and read nodes, a `lup ledger` command, and its dashboard panel, built beside it and registered by its path;
- **what it requires:** the modules it builds on, declared on its `Module` (`requires = [...]`), and any third-party package, as an extra of `lup`'s.

A module adds to the environment, or to the dashboard, from its own directory, through the cores' interfaces: its environment side subclasses `lup_dev`'s `Module`, and its panel is a file the dashboard loads. A module may have one side only: the code rules are all environment, the test fake all library.

### Packaging (to confirm)

One monorepo, a uv workspace, every distribution built and released together at one version. Distributions are split by what installing them costs, not by module **(to confirm)**:

```
packages/
  lup/             # the library core, and every module, both sides in its directory:
                   #   lup/ledger/__init__.py     its library side
                   #   lup/ledger/environment.py  its environment side
                   #   lup/ledger/panel/          its dashboard panel, built at release
                   # extras for third-party packages: lup[claude], lup[codex], lup[testing]
  lup-dev/         # the environment core; requires lup-engine and lup-dashboard
  lup-engine/      # the 38 MB code-rules engine, which CodeRules and Proposals require
  lup-dashboard/   # the page: its shell, the typed protocol's client, the components panels use
```

It's how pytest is built: its own features are "builtin plugins which provide pytest's own functionality", loaded from its own package through the hooks third parties use, and "even builtin plugins can be blocked" (`-p no:name`), while a third party's plugin is a distribution of its own. pydantic-ai is one distribution, `pydantic-ai-slim`, whose extras pull only third-party SDKs. Airflow's way, a distribution per provider ("more than 80", "released and versioned separately from the Airflow releases"), fits providers that wrap third-party services, each with its own SDK, maintainers and release cadence; lup's modules are lup's own, released together, and mostly pure Python on pydantic. A distribution per module is in `docs/graveyard.md`.

So:
- **a module is a directory:** moving code between modules, or splitting one, moves files, and its import name is `lup.ledger`;
- **lup's modules take the path a project's do:** a module is an importable package with a `Module` class, whether it's in `lup`, in a project's own code, or in a distribution someone publishes; which distribution holds it doesn't change its API;
- **a module that needs a third-party package declares it as an extra:** `lup[claude]` brings Claude's SDK, with its CLI;
- **`lup-dev` requires `lup-dashboard` (to confirm):** the dashboard is the operator's main place of interaction, and CI pays a download.

### What a consumer downloads (leaning)

```toml
# swarm-search's pyproject.toml
[project]
dependencies = ["lup[claude, codex]"]   # what its consumers download

[dependency-groups]
dev = ["lup-dev"]                       # only while developing; never shipped
```

A consumer gets `lup` with the extras its code needs: every module's code, a few kilobytes each, environment sides and built panels included, inert, since nothing imports an environment side without `lup-dev`, and nothing serves a panel without the dashboard. The environment core, the engine and the dashboard come only with the development group.

Two import contracts make it safe:
- **inside lup,** a module's library side never imports an environment side, so `import lup.ledger` works without `lup-dev`; and a module imports only the modules it requires;
- **in each project,** its shipped code (by its path roles, `src/`) imports no environment side, so it never needs the development group to run. lup generates that contract for the project's gate.

### Selected and installed (leaning)

Every module of lup's is installed with `lup`, and `lup_project.py` says which environment sides a project's sessions get. What can be missing is a third-party package behind an extra, or a module from another distribution:
- **a module whose extra is missing** fails where it's imported, naming the extra: "`lup.claude` needs Claude's SDK: add `claude` to lup's extras in `pyproject.toml`." lup never writes a project's `pyproject.toml` after `lup new`, so it can't add it itself;
- **a module from another distribution,** a project's or one someone published, is imported by the declaration, so one that isn't installed fails the declaration's import;
- **installed but not selected** is fine: swarm-search's code uses the ledger's store while its sessions don't get the ledger's tools.

### Kinds a module declares (decided)

A module can declare a kind of entry other modules fill, which exists only where it's selected: the ledger's node kinds, which coordination, feedback and a project's code fill; budgets' shares; the judgement of a write, which every judging module fills (*Judging writes*).

### Nothing built in (decided)

A pipeline lup runs (judging a write, the gate, rendering the guidance, the dashboard) decides nothing itself: everything it decides with comes from modules, lup's own included, and a project's module adds, drops or replaces any of it. A project changes how its writes are judged, or what its dashboard shows, with a module of its own.

## How a module refers to code (open)

What's wanted: pyright checks the reference, and rename and go-to-definition follow it; loading the declaration stays cheap, since every judged hook loads it (about 1 ms once exported, `docs/judging-writes.md`); it imports nothing that runs elsewhere; and trust on launch isn't widened to code the host never runs. In plain Python a real reference is an import, so the options trade those against each other.

- **String addresses in entry-point form (the build uses these until it's settled):** `Tools.of("audiobook.studio.tools:narration")`. Lazy by construction; the gate imports each and fails on one that doesn't resolve, and could check it names the right kind; pyright can't see it.
- **Real references, with the gate checking what loading the declaration imports:**

  ```python
  # lup_project.py
  from audiobook.studio.tools import narration

  class Narration(Module):
      """Turning a page into an episode."""
      name = "narration"
      tools: Tools = Tools.of(narration)
  ```

  ```python
  # src/audiobook/studio/tools.py: its top level imports only models and lup
  from lup import Toolset, lup_tool
  from audiobook.studio.models import Episode, Page

  @lup_tool(runs="inside")
  async def narrate(page: Page) -> Episode:
      """Narrate one page into an episode."""
      from audiobook.studio.voice import synthesize   # torch and the rest, imported when called
      return await synthesize(page)

  narration = Toolset.of(narrate)
  ```

  The laziness then comes from what a file imports at its top level, not from the reference. The gate imports the declaration in a fresh interpreter, through the project's runner, with an import hook recording who imported what, and fails on anything beyond the standard library, pydantic, lup, the project's own modules and the packages the project lists with their reasons:

  ```
  declaration-imports: loading the declaration imports `torch`:
    lup_project.py → audiobook.studio.tools → audiobook.studio.voice → torch
    The declaration is loaded at every judged hook; import it inside the function that uses it.
  ```

  A room-side tool's file joins trust on launch's host zone, since the host imports its definitions, though it never runs them.

Considered and set aside:
- **Methods on the module class** (`@tool async def find_issues(self, …)`): typed, with the module's settings as `self`, but every tool sits flat in one class body, in one file, hard to split or reference across files (the operator), and a project's protected declaration would hold its tools' code, so every change to one would ask.
- **Python's entry points** (`[project.entry-points."lup.tools"]`, as the first lup's `lup.devtools`): still strings, the declaration split across two files, and a change seen only after a reinstall.
- **Lazy imports:** passing a lazily imported name to `Tools.of(…)` uses it, which imports it (PEP 810, Python 3.15, as read; lup is on 3.14); a name imported under `TYPE_CHECKING` can't be called.
- **Factory functions** whose body imports and returns the code: checked and lazy, but the grammar can't see a toolset's name without calling the factory.

**Tools, whichever is chosen (leaning):** one decorator, the library's `@lup_tool`, whether an ask from code, a room or a module serves the tool; toolsets group tools in any file and include other toolsets, and a module holds its toolsets as a selection (`Tools.of(reading, writing)`, `.drop("writing")`); a tool reaches its module's settings, its caller and its launch through parameters typed with them (`github: GitHub`), which lup fills when it calls. Today `@lup_tool` takes one model parameter; this widens the library's API.

## The cores

Each core is what every module builds on and none can drop (`DESIGN.md`, *The two cores*): the library core is `lup`'s own top level, beside its modules' directories, and the environment core is `lup-dev`.

- **The library core, `lup`:** asking an agent and typed answers, the speaking tools, tools and their serving, the layers, typed events; the runtimes (`claude`, `codex`) and the fake and the guard (`testing`) as modules of their own, each behind an extra for its third-party package.
- **The environment core, `lup-dev`:** the declaration and its modules, with a person's own layer; the one hook; the host service and its handlers; the inbox's delivery; launch and trust on launch; the limits on the operator's credentials, with git through the host; and the pipelines modules feed (judging a write, the gate's runner, rendering the guidance, the dashboard's protocol).
- **Why launch and trust are core (decided):** trust approves a module's code before the host runs it, so something must vet the modules first; and the wall is policy (`DESIGN.md` requires a container whenever an agent can run code), which a project configures through its modules but never drops.

## The map

| Module | Library side | Environment side | Requires | State |
|---|---|---|---|---|
| library core | asking, typed answers, speaking tools, tools and serving, layers, events | | | built: the library's first slice |
| `claude`, `codex` | each runtime's adapter | | | built |
| `testing` | the fake, the guard | | | built |
| environment core | | declaration, hook, host service, inbox delivery, launch, trust, credentials and git, the pipelines | `transcripts` | built, as one package |
| `transcripts` | | each session's record kept whole, every branch of it; resuming through it | | to confirm; to build (#65) |
| `rooms` | `Room`, `Container`, the engine | | | partly built (`lup.rooms`); leaning |
| `runs` | the run directory, its log, its units | panel | | to discuss |
| `ledger` | the typed store, blobs, snapshots | tools, `lup ledger`, panel | | leaning |
| `inbox` | mailboxes, on the ledger (leaning) | `lup inbox`; delivery is the core's | `ledger` | built with its own store; moves onto the ledger (decided) |
| `coordination` | `fetch`, claims, findings and questions, their kinds | your sessions' roster, panel | `ledger`, `inbox` | leaning |
| `budgets` | `SharedBudget` | shares, pace, pauses, spawn caps, panel | `accounts` | to discuss |
| outcome loop | outcomes, arms, comparing them | panel, command | | library side decided; to discuss |
| reflection | | | outcome loop | open (`DESIGN.md`, *Open questions*) |
| realtime | a present agent: sleep, wake, timing tools | | Jev, a decision model, as a dependency | library side decided; to discuss |
| `Python` | | runner, test roots, the gate's steps, lup's settings for ruff and pyright | | built |
| `CodeRules` | | selection, exemptions, judging writes, `rules` commands | `lup-engine` | built, but the judge isn't in it yet |
| `Proposals` | | `propose`, holds, the dependency guard | `lup-engine` | open (*To discuss*) |
| `spawn` | | lup's workers, isolation, moving between worktrees | | to discuss |
| `git-workflow` | | landing, pull requests, merge-resolution check | | to discuss |
| `GitHub` | | GitHub tools, the gate's issue states in a room | | built in the core; leaves it (leaning) |
| `accounts` | | logins, usage windows, conversations | | to discuss |
| `setup` | | integrations and their secrets | | to discuss |
| `release` | | version bumps, the release flow | | to discuss |
| `resolver` | | concerns, their worktrees, one integration branch | `git-workflow`, `runs` | to discuss |
| feedback | | "how it felt", telemetry, the pooling pass | `ledger`, `transcripts` | to discuss |
| `meta` | | authoring tools | | leaning: goes (*To discuss*) |
| the dashboard | | `lup-dashboard`, which `lup-dev` requires (to confirm); every panel a module's | | to build |

## Settled so far

### The ledger

The generic store the first lup had, kept **(the operator's)**: downstream projects each stored their own kinds in it (swarm-search's eleven, among them `Evidence`, `Source`, `Claim`, `Question`, `Lead`, `Correction` and `Incident`), and coordination needs a durable shared store. `DESIGN.md`'s earlier "a view over what exists, storing nothing" is in `docs/graveyard.md`.
- One log per repository, of typed nodes and edges declared by whoever uses them: a project's code, or a module (*Kinds a module declares*). Reads are per type.
- **Each kind committed or local:** committed with the code, or kept under the git directory, which every worktree of a clone shares and every room mounts, so five agents in five worktrees write one log with nothing to merge. A snapshot commits a local log to a branch of its own when a state is worth keeping.
- **A node's standing is read from what points at it,** never stored, so nothing has to be updated when an answer or a refutation lands.
- **Blobs are content-addressed:** first writer wins, needing no lock and no ordering.
- **Library side (leaning):** swarm-search's production code builds on it, and production code can't import the environment.
- **Open work is a pointer to a GitHub issue (decided),** not a ledger entry of its own.

### The inbox

- **Every party's (decided):** the operator's and each agent's. Agents message each other through the same inbox they ask the operator through, as the first lup's did ("a message to a peer and a message to a spawned worker travel one stream").
- **Stored on the ledger (decided):** an item is a node; "answered" is an answer pointing at it, "told" a delivery to that party pointing at it. Two things to design for: the inbox spans every project, held in the host's own state and never mounted, so a ledger store takes a location (a repository's committed or local store, or the host's); and it's read at every hook ("what hasn't this party been told?"), so the ledger needs an index for it, not a scan. The first lup kept mail apart from its ledger, for reasons not found yet. The ledger comes first; the inbox, which works today, then moves onto it.
- **Mailboxes as a library side (leaning),** so agents started from code message each other; delivery into launched sessions, and to the operator, is the environment core's (`DESIGN.md`, *Open questions*, shared state where no host runs).

### Transcripts

Keeping every session's record isn't feedback's **(to confirm)**: it's for seeing what went wrong, for not losing the traces of past agents, and for resuming reliably, which the runtime's own record doesn't always allow (after a rewind; Claude Code sets a transcript aside as `superseded` or `orphaned`, out of its session picker).
- **A module the environment core requires (to confirm),** so no project drops it; resuming, the dashboard and feedback read from it.
- **Sessions on the operator's machine are kept whole (to confirm):** launched, spawned and kept sessions, with every branch of a rewound conversation, the set-aside files, subagents' transcripts, large tool results, the file history and Codex's rollouts. Resuming goes through lup, from any point of any branch.
- **An ask from code keeps its turn whole where its declaration says so (to confirm),** on by default for code running in the operator's own projects; a product shipping lup to other people decides for its users.
- **Until it's built:** Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default, at least 1, no maximum in its schema; `0` is a validation error), which the operator raised in their own settings; Codex's configuration has no key that deletes rollouts. When the copy is taken is #65's open question.

### Coordination

What it's for **(the operator's)**: agents like swarm-search's investigators exchanging downloads, messages, findings and questions easily, saying what they're on, and not doing each other's work. The first lup's locks existed so agents wouldn't download over each other; a worktree per agent stops that, but alone it would have them repeat each other's work. Agents get in each other's way in four ways, each with its own answer **(leaning)**:
- **Records and downloads:** the ledger. Nodes are append-only and blobs content-addressed, so nothing shared can be overwritten. `fetch(url)` returns what's been downloaded already; if another agent is fetching it now, it waits for that and returns the same blob; otherwise it claims the URL, downloads it, stores the blob and records a `Source`.
- **Files in a working tree:** a worktree per agent. What the first lup's claims were for, in its own words: "the failure this exists for is finding out at merge time." The judge already sees every write and knows each session's worktree, so when two live sessions change one file, it trial-merges their branches, as the checkpoint already does for merges, and tells both at once, each naming the other. An advisory claim covers the one case watching writes comes too late (a whole package about to be rewritten); as in the first lup, writing under someone else's claim says who holds it, and is never refused.
- **Shared outside resources** (a host's rate, an account, a device, a browser): one owner. The repository swarm-search grew out of was blocked by a host when three sessions each kept the rate on their own; `SharedBudget` counts a rate across processes, and a module's handler on the host can own a resource agents request through it.
- **The same work twice:** claims on work (a lead, a question, a task), alive while their holder is on the roster, so nothing needs releasing.

The roster fills itself from what each session does; what an agent says it's working on is one line it sets when it starts or changes work, never a call repeated to keep it fresh (the first lup's 251 describe calls in nine days, `docs/graveyard.md`). Mail is the inbox's.

### Spawn and isolation

Isolation goes with spawn **(decided)**: where a session works is decided when it's started. Leaning a worktree per agent, its environment hardlinked from a cache, and a tool to move between worktrees. Kept apart from `git-workflow` because the two are dropped independently (a project whose history the operator writes drops landing but keeps each agent isolated), and because isolation may stop being worktrees (`DESIGN.md`, *Open questions*: a write layer).

### git-workflow

Landing, pull requests, and checking a merge resolution kept both sides **(decided: separate from isolation)**. It retires a worktree when its branch lands, through a hook, never requiring the module that made the worktree. In the first lup, worktree commands were the core's and `git-workflow` was skills (commit, rebase, merge, land, close) with guidance on commit messages and resolving conflicts.

### Judging writes

A pipeline of the environment core, fed by modules, with nothing built in **(decided)**: `Core` brings the protected paths, `CodeRules` its rules' findings, `Proposals` its holds and the dependency guard, and a project's module adds a judgement of its own or replaces one of lup's. Placing the judge in a module of its own, or inside `CodeRules`, was set aside: dropping that module would drop every other module's judgement, and `Proposals` would have to require it. The checkpoint, which judges after a call what the hook can't see before (Codex's patches, the shell), stays until `Proposals` decides what holds a write on a runtime that can't ask before it.

### The outcome loop, reflection and realtime

Mainly library-side modules **(decided)**: aib's forecasts and harmon's waiting agent use them from code; each gets an environment face (a panel, a command) where it needs one. What reflection is stays open: `DESIGN.md` has it recording data from each run for the outcome loop, while the first lup's was a reviewer an agent's output met before it was submitted.

Realtime pairs a fast decision model with Claude, as many harnesses do **(to confirm)**: Jev (and openjev) make decisions in real time. Jev is a dependency of realtime, not a runtime: it sits nearer the model than the runtime, so if the library ever takes it in, it's as a class of decision models beside the agents, never as a third runtime beside Claude and Codex.

### GitHub, and git through the host

The limits on the operator's credentials, and git through the host, stay in the environment core (`docs/host-tools.md`, decision 11). GitHub's tools leave it as a module of their own **(leaning)**, the first to prove that modules bring what they do.

## To discuss

Every boundary is tested by one question **(to confirm)**: would a project take this module without its neighbour, or replace one of them with its own? Where it would, they stay apart; where they always come together, they're one module. Most pass (`accounts` without `budgets`, `inbox` without `coordination`, `rooms` without `runs`); `meta` fails, holding nothing once each authoring tool lives with its kind.

Each remaining module, with the question it raises first:
- **`rooms` and `runs`:** what of a room is the library's and what launch's; a run's panel; whether a run's log is a ledger.
- **`spawn`:** lup's spawn on both runtimes; workers' identity and budget share; cross-project spawns through the host; moving between worktrees.
- **`Proposals`, open, as the operator asked (2026-10-16).** The engine is `lup-engine`, which it and `CodeRules` both require. Discussed on 2026-10-16, nothing settled:
  - the operator's concern: approving a shape after its code is written is back and forth that holding first would have avoided, as the code rules exist so a bad pattern is caught before code is built on it; a hold costs the agent nothing it notices, while a systematic refusal is friction;
  - one principle proposed: refuse what the agent can fix alone (a code rule's finding), hold what needs the operator (the design);
  - one flow proposed: a shape (docstrings, public signatures, models' fields) is free to write; a body for an unapproved public signature, or a use of an unapproved name from other production code, is held; `propose` holds by default; building without proposing becomes a hold whose item lup writes itself, the shape it read marked "not proposed"; the operator approves the shape, not the code;
  - the friction the agent named: small public additions mid-work each becoming an item for the operator (the real risk, on the operator's side), a body showing the approved signature was wrong, the habit of writing a whole file at once, names public only by having no underscore, agents waiting overnight at their first new shape, and Codex's patch held only at the next call.
- **`budgets` and `accounts`:** the kinds budgets declares; usage windows; logins kept in step across rooms.
- **`setup`, `release`, `resolver`:** each against the first lup's version (setup's wizard, version's two reviewing agents, the resolver's supervisor).
- **Feedback:** "how it felt", telemetry and the pooling pass as one module or several; upstream candidates (`DESIGN.md`, *Open questions*).
- **The outcome loop, reflection, realtime:** their library APIs, and what each shows on the dashboard.
- **`meta`:** leaning that it goes, each kind's authoring tool living with its kind (`lup rules new` with `CodeRules`).
- **The dashboard's panels:** which module brings each of lup's.

## What the first lup's modules became

| The first lup's | What it was | Here |
|---|---|---|
| `core` | reading a codebase, reporting what's left, debugging, querying the permission policy | the environment core; code-intelligence tools (leaning); the permission policy's shell analyzer is in the graveyard |
| `git-workflow` | committing, rebasing, merging, landing, and what must be green first | `git-workflow` |
| `meta` | changing the machinery: the harness, and walks that move code | `meta`, open; its regenerated trees are in the graveyard |
| `resolver` | reviewed feedback becoming concerns, worktrees, workers and one integration branch | `resolver` |
| `version` | deciding and making a version change, with two agents gathering and reviewing | `release` |
| `observability` | a session's trace, and the archive kept once its worktree is gone | feedback's telemetry; transcripts (#65) |
| `sandbox` | the confined execution a session is offered | the graveyard (the inner posture, `execute_code`); the wall is launch's |
| `setup` | configuring keys, integrations and profiles | `setup` |
| `conversation` | retaining authenticated AI conversations | `accounts` |
| `feedback-loop` | turning an observed failure into a capability change | feedback and the outcome loop; its five-skill chain is in the graveyard |
| `runs` | work that outlives its tool call, as a resumable pipeline | `runs` |
| `ledger` | one append-only log per repository of typed nodes | `ledger` |
| `coordination` | a roster per repository, mail, the person as a peer | `coordination`; mail is the inbox's |
| `realtime` | persistent agents controlling their own attention | realtime |
| `reflection` | a reviewer between finishing the work and submitting it | reflection, open |
