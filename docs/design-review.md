# The design review of 2026-10-12: what changes, and why

**One sentence:** lup is built as designed, without running its half-built judge on its own construction; an agent proposes its design changes through a lup tool, and nothing can be built on a design until it's approved; and the library, the environment's core and its modules take the shape below.

This note proposes changes to `DESIGN.md`, which is the operator's. It records a conversation between the operator and an agent that reviewed the repository's state, the first lup's code, and the projects using it. Once approved, `DESIGN.md` takes these decisions (*What changes in `DESIGN.md`*, at the end) and this note is removed, so the two never disagree.

Each decision is marked:
- **agreed:** the operator said yes during the review;
- **leaning:** the agent's proposal, which the operator didn't object to or didn't answer;
- **open:** still to decide, with the agent's lean.

## Where the repository stood

- **The judge and its machinery** in `lup-dev`: about 11k lines of Python (`policy/checkpoint.py` 1,774 lines, `policy/submissions.py` 1,399), the TypeScript engine on pyright's internals, and 45 rules.
- **The library:** 86 lines (`types.py` and the front door), though its first slice's note was approved on the first day. A parked draft sits on `feat-library` (`af4e83b`), not to be landed.
- **12 of the 18 open issues** were about the judge, the review flow or the engine.
- **The merge commits' "how it felt" notes** show agents working around the judge. Workers built in scratch clones, then retyped 1,400-line files into Write calls to land them (879fbb5, e84daec). One switched from Write to Edit to avoid an ask (98318c5). New modules waited about an hour in the queue (661df20).

The bridge was meant to be light scaffolding until lup hosts itself. Instead, it was the destination's judge, built first and run on its own construction before it was finished, so each of its bugs blocked the work.

## How the build proceeds

1. **(agreed)** **Build the design directly.** A piece of the environment goes live in lup's own sessions once it's finished, not while it's being built. *Alternative:* keep extending the bridge (the review flow's branches 3–7, then the declaration). *Cost:* a piece built without its own guardrails is reshaped afterwards, wherever review changes it.
2. **(agreed)** **During the build, the hooks run the code rules at the edit, and nothing else.** The checkpoint, the turn-end holds and the interim review are turned off. Design is reviewed through notes before code, and at landing. This lands separately, with the change to `.claude/settings.json` and `AGENTS.md`, since it changes how work goes today. *Alternative:* all hooks off; but the rules at the edit are stable, cheap, and the destination's own code.

## Rules at the edit, rules at the gate

3. **(agreed)** **Each rule has a timing:** `edit` or `gate`, a field in the rule table.
   - **At the edit:** the rules that pick an approach other code gets built on:
     - parsing: `regex`, `string-split`, `string-slice`, `string-strip`, `string-replace`, `dict-literal-key`;
     - data shapes: `tuple-shape`, `set-shape`, `dataclass`, `namedtuple`, `typed-dict`;
     - which library does a job: `subprocess`, `os-path`, `argparse` and the like;
     - errors and types: `bare-except`, `cast`, `any-type`;
     - suppressions, `silent-truncation`, `historical-voice`.
   - **At the gate:** the rules about how a correct thing is spelled: `elif`, `collection-loop`, `private-name`, `docstring-code`, `constant-home`. Where ruff has a fixer, `check --fix` applies it without reporting it.

   The table is protected, so each rule's timing is the operator's call; this is the first cut.

   *Why:* a design mistake compounds, because code gets built on it, so it's refused when it's written. A spelling inconsistency doesn't compound, so it's caught before landing, in one batch. A gate rule still blocks landing, so `DESIGN.md`'s worry that informational rules get bypassed doesn't apply. *Alternative:* every rule at the edit, as now, which made agents rewrite correct code into a house style at every edit.
4. **(agreed)** **`historical-voice` stays at the edit.** The agent writes from inside the session, where the change is the most visible thing, so its comments drift into "this now does X". *Alternative:* a fresh agent rewriting comments and docstrings at landing; the operator was unsure, and it isn't pursued.
5. **(leaning)** **`interface-shape` drops its count of one to three abstract methods,** and keeps "a class with abstract methods names `ABC`". Without `ABC`, `@abstractmethod` doesn't stop instantiation, which is a real bug. The count misfired on an approved six-method `Queue` (e84daec), and by `docs/rules.md`'s own standard that makes it the rule's bug.

## Approval: the agent proposes, and nothing builds on an unapproved design

6. **(agreed)** **Writing and proposing are separate acts.**
   - **Writing uses the runtime's native tools.** A new production file lands where it belongs, so its tests can import it straight away.
   - **Proposing is a lup tool:** `propose(paths, why, wait)`. The agent calls it when the files make a coherent design, with its reasons attached.
     - With `wait=True`, the call holds until the operator answers.
     - With `wait=False`, it returns at once, and the answer reaches the agent through its inbox at its next call.
     - A proposal names several files at once, which is the bundling `DESIGN.md` wanted.
   - **What needs a proposal:** a new production file, a whole-file overwrite, a public-API change, an added suppression, a protected path. Suppressions and protected paths are small enough to hold at the edit itself.
   - **The dependency guard.** A production edit that imports or uses an unproposed design is refused, saying "propose `a.py` first". If the design is proposed and still waiting, the edit is held until the operator answers. The engine already resolves imports and references. The agent chooses when to propose, never whether.
   - **Nothing is forgotten.** At the end of a turn, unproposed design changes are listed. Landing refuses a branch that still has one, or one the operator declined.
   - **A held call is invisible to the agent.** It returns once answered, saying it was held and carrying the operator's comment. A `PreToolUse` hold of four hours ran cleanly (`DESIGN.md`, *Field Notes*). A hold under an hour keeps the cache.
   - **The operator sees unproposed work as it forms.** The dashboard shows each agent's unproposed files live, labelled "in progress, not asking you". Stepping in is the operator's choice, and the agent hears a comment at its next call.
   - **The verdict log records how much code was written before each proposal,** so it can be seen whether agents write everything first and propose it all at once.

   *Why not the alternatives:*
   - **The per-write ask on a new file's first Write** shows a half-written file.
   - **The drafts flow (`docs/review-flow.md`)** made the write invisible, but not its use: "a test importing a module that exists only as a draft fails to import" (line 185), and the agent is to `wait` whenever its next step needs the change (line 302). Almost every new module is tested right after it's written, so each new file was a wait.
   - **Approval at landing** (open question 11's alternative) lets the agent build a whole architecture on an early choice. By the time the operator points it out, the agent changes the one flagged thing and keeps the rest.
   - **A cap on unproposed code** would ping the agent; the operator declined it.
   - **An MCP edit tool with a mode on each edit** would need lup to rebuild the runtimes' edit behaviour (Claude Code's exact-string edits, its read tracking, its diff display; Codex's `apply_patch`), and would make the agent decide intent at every edit. Intent belongs to a set of files at a moment, which `propose` carries.
7. **(leaning)** **A declined proposal stays in the worktree for the agent to revise.** The dependency guard already keeps anything from being built on it, which was why `DESIGN.md` restored declined changes. *Alternative:* restore the accepted version and save the agent's, as `DESIGN.md` says now.
8. **(leaning)** **No per-call checkpoint in the finished lup.** What the shell writes is caught at the turn's end, where unproposed changes are listed from the worktree's state, and at landing, where the gate runs the rules and unproposed or declined changes refuse the merge. This settles open question 11 toward judging writes at the edit. *Why:* most of the incidents it lists came from judging after the call (#22, #32, a removed worktree, holds on a commit and merge made in one command). *Alternative:* keep the checkpoint for shell writes.

## The library

9. **(leaning)** **Sessions keep the first lup's shape** (`providers/claude/__init__.py:520`, `sessions/turns.py`, under the first lup's `packages/lup/src/lup/`):
   - `async with agent.open(resume=None) as session:` gives a fresh session each time; the declaration holds no state.
   - `session.ask()` returns a lazy `Turn[T]`. Awaiting it gives the `TurnResult`; iterating it gives the content as it completes; `live()` streams text; `interrupt()` stops it. It starts on first use, so the typed-answer tool is attached before the runtime takes input.
   - **One runtime's abilities are types:** `steer()` exists only on Codex's turn, so pyright refuses it on Claude.
   - **One name:** `Session`, the runtimes' own word (`session_id`). The first lup's protocol said `Conversation` while its classes said `Session`.
   - **History** comes from the runtime's own record, so a session resumed from another process, or begun in a terminal, reads the same. lup's writer keeps the copy with secrets scrubbed.
   - **A refused resume raises.** The first lup silently began a fresh conversation (`providers/claude/runtime.py:430-462`).
   - **The first slice runs without persistence** (`docs/library.md`), which rules out resuming. The conversations slice needs its own config home.
10. **(leaning)** **On Codex, a conversation declares its output types when it opens,** with one submit tool each. Codex fixes a thread's dynamic tools when the thread starts, and a resume can't change them (the first lup's `docs/native-capabilities.md`). So `lup_submit` (`docs/library.md`, decision 6) holds for a single `ask`, but a conversation can't swap its submit tool from turn to turn. *Alternatives:* one generic submit tool carrying JSON, validated per turn, which loses the schema from the tool definition; a new thread whenever the type changes.
11. **(leaning)** **A room wraps an agent:** `Room(agent=Claude(...), container=Container(image=…, mounts=[…]), …)`. Both satisfy `Agent` with the same verbs (`ask`, `open`, `spawn`, `launch`), so anything that takes an agent takes either.
    - Swapping runtimes is one field, with the container, mounts and toolkit declared once.
    - `lup launch claude audiobook` picks the runtime at launch.
    - The inner declaration can't hold Bash without a container, so `room.agent.ask()` is a plain ask with no tools.

    *Alternative:* a `container` field on `Claude` and `Codex`, which restates the room for each runtime.
12. **(agreed)** **Where a lup tool runs is declared on the tool:** `@lup_tool(runs="inside")` by default, `runs="outside"` when declared.
    - **Inside** means the agent's side of the wall. With no container, that's the caller's own process. In a room, a small server inside the container imports the function by its path and runs it. lup's own tools in a terminal session use the same server, reaching the host service through a mounted socket. An inside tool must be importable by path (not a closure), and lup refuses a room declaring one whose image lacks the project.
    - **Outside** means the caller's process on the host. These tools are the deliberate openings in the wall: `lup_submit`, publishing, anything needing a credential.
    - **The tool's author decides,** since they know whether it needs a secret or touches the workspace. A declaration can't move a credential-holding tool inside.
    - **The room's own toolkit** is the CLIs and scripts in its image, which the agent runs with Bash and may extend.
13. **(agreed)** **A room's image is built with the project installed.**
14. **(agreed)** **A worker's hand-back is typed,** submitted through `lup_submit`: `Handback[T]` with `result: T` and `how_it_felt: str`. The field's description carries the three prompts (what was smooth, what got in the way with the exact command and message, what you'd change). The worker's turn can't end without it, and the spawn files it in the ledger. *Why not more structure:* the operator worried types would constrain the answer, and what mattered was the guarantee and the filing.
15. **(leaning)** **What the first lup's library had that the design lacked** (paths under the first lup's `packages/lup/src/lup/`):
    - **Waiting out a usage limit:** it slept until the reported reset, then retried the same request (`sessions/quota.py`). aib lost 21 of 24 partial forecasts to quota exhaustion, and inkwell lost a stage. Here it's a layer, on by default and bounded by the timeout layer, so a 30-second timeout still fails fast.
    - **Large tool results go to a file,** with the path and a preview, before Claude Code's own cap moves them somewhere the agent can't read (`tools/mcp.py:531`, `workspace/content_safety.py`). aib's search overflowed at 81k characters. This belongs in the tools slice.
    - **Model ids are checked types,** with portable tiers. An effort the model can't take is refused at declaration, since the CLI drops it silently.
    - **Tool search control:** a tool server kept loaded (aib's agent guessed search terms against deferred schemas), and a third-party MCP server passed through.
    - **`BudgetExceededError` leaves the first slice.** `docs/library.md`'s area table keeps it, but its errors table and layers hold no cost cap. Budgets own spend caps.
16. **(leaning)** **Runs make reading the wrong run impossible by construction.** This is the design nori's report asked for (`nori/tmp/lup-runs-design-prompt.md`), with one correction: the report has every file carry the run's identity and every reader filter by it, which is still a rule each reader must remember.
    - **One subdirectory per run,** `runs/<run-id>/`, plus a `current` pointer swapped atomically. A reader resolves `current` once, so another run's files aren't there to be counted. The id stays in each record as a check.
    - **`open()` is one call,** made before any slow pre-work: it mints the id, writes `starting`, and swaps the pointer. A refused pre-work records its ending, with the reason, under the new id. nori's `open_wave` workaround becomes this call.
    - **One append-only event log per run.** State, counts and the ending are derived from it and from the manifest. There's no separate summary to go stale.
    - **Every unit ends in a typed record:** landed, failed, killed (which deadline, which clock, how long it ran, its last report), abandoned, or reused.
    - **Reuse is per unit,** by the unit's own fingerprint, from a store shared across runs, and is reported as a reuse.
    - **A follower pins the run id when it attaches.** If `current` moves, it says "superseded by <id>".
    - **What a run shows:** a unit reports its progress (`unit.report("depth 12")`), and a run can carry its own detail model (`Run[CampaignDetail]`), whose fields become columns. Opening a run emits an event naming its directory, so the dashboard finds it without a declaration.
    - **A unit can wait on other units and on an inbox answer,** which is what the resolver needs (decision 22).
31. **(agreed)** **Every agent lup runs can speak to whoever asked, through lup's speaking tools.** They act on nothing, so they're served even where an agent has no other tool. Other tools an agent finds useful for speaking to its caller may join them.
    - **`report(problem)`** stops without an answer and says what's wrong: the question can't be answered, something needed is missing, an instruction seems wrong. The result depends on who asked:
      - from code, `ask` raises `ProblemReportedError` with the agent's words, so a caller tells "the agent says this can't be done" from a failure;
      - a worker's report is its hand-back;
      - an interactive session's report reaches the operator's inbox as a problem, and its turn ends.

      Terminal sessions get it through lup's MCP server.
    - **`note(remark)`** attaches a remark to the answer without ending the turn: an assumption, a doubt, a counterargument. A caller reads it in `TurnResult.notes`, and the trace keeps it. *Why:* aib found that in its worst misses the agent's own counterargument often held the right answer and was dismissed (`DESIGN.md`, *Field Notes*).
    - The attempts limit stays, as the safety net for an agent that neither answers nor reports.
    - *Alternative:* the guard alone, which leaves an agent that can't answer nothing to do but fail until its attempts run out.
32. **(agreed)** **A guarantee says what can actually happen, not how lup arranges it.** An ask from code can't run commands, touch files, reach the network or start agents; it can only call lup's tools. A runtime's own tools that can do none of those don't break it: Codex's code-mode models qualify if their `exec` reaches none of them, which the Codex adapter checks. *Alternative:* "no tools but lup's own" taken literally, which would refuse Codex's default model for tools that can't act.
33. **(agreed)** **On Claude, lup serves its tools through its own MCP server,** with `mcp` a direct dependency of `lup[claude]`, as the first lup did. The SDK's helper validates a call's arguments before the handler runs, so lup could neither count those refusals against the attempts nor keep them in `rejected`, and a turn making only malformed calls would be bounded by nothing but its timeout. *Alternatives:* the SDK's helper, with refusals read back from the message stream; or a cap on turns.

## The environment

17. **(agreed)** **One host service.** `DESIGN.md` implies several host-side processes: spawn's launcher, the budget control, credential actions, secret services, host companions, the dashboard's backend. They're one service, taking typed requests over a socket mounted into each container, with modules registering handlers.
18. **(agreed)** **The inbox is core, and replaces the `realtime` module.**
    - **Every party has an inbox:** the operator, and each agent.
    - **Everything that wakes someone lands in one,** with its reason: a message, a proposal's answer, a worker's result, a reminder, a timer.
    - **A hold is a wait on one's inbox.** The dashboard shows the operator's inbox, and notification channels push it off the page.
    - **Batching bursts and not talking over the operator** are rules of how an inbox delivers, built so they can't starve replies.
    - **Reminders and follow-ups are lup tools,** cancelled when the operator speaks.
    - **Messaging leaves `coordination`,** which `DESIGN.md` listed under both the core and the module.

    *Evidence (harmon, `/home/pfftz/job/pause/harmon.git`):* a Discord agent that waited inside a `sleep` tool and was woken by events with their reason. The waiting held up. What failed was loading every timing decision onto the agent through prompt rules: a reply grace window starved its replies for minutes. Latency (21–68 s) and memory lost across restarts failed too. The first lup carried its scheduler into `orchestration/realtime/`.
19. **(agreed)** **Modules may depend on modules, declared:** `requires = [Accounts]`.
    - The loader refuses dropping a required module while keeping one that requires it, naming both, and refuses a cycle.
    - The drop tests cover each module together with whatever requires it.
    - Known so far: `budgets` requires `accounts`, `coordination` requires `ledger`, `reflection` requires the outcome loop's module.

    *Why:* the first lup's evidence ("removing one module kept breaking another") was against undeclared dependencies. Banning dependencies outright pushes everything two modules share into the core, which `DESIGN.md` wants small. *Alternative:* `DESIGN.md`'s rule that a module uses only the core's API.
20. **(agreed in direction)** **The dashboard is extended with code, not only data.**
    - **A module can ship its own panel,** loaded by the prebuilt dashboard at runtime, so no project rebuilds the dashboard.
    - **Panels get data through the typed protocol,** with TypeScript types generated from the pydantic models.
    - **lup's components are exported,** so panels look consistent.
    - **lup's own panels** (agents, the inbox, runs, setup, usage) **use the same API.**
    - **Declared views stay as a shortcut,** for a table or a progress bar with no frontend code, built on panels.
    - **A panel runs sandboxed,** with a token scoped to its module's data. A panel is code an agent can write, and one holding the dashboard's full token could approve its own agent's proposals.

    *Evidence:* the first lup's views were a hardcoded union (`web/src/dashboard/state.ts:12`), no project extended the dashboard, and adlib built its own preview server instead. *Alternative:* views as data only, which the operator expected to constrain later additions and downstream projects.
21. **(agreed)** **`accounts`, a module:** logins, including keeping a renewed login in step across containers; usage windows, with the usage bars (dropping the module drops them); and downloading conversations from claude.ai and ChatGPT.
    - A renewal rotates the refresh token, and in the first lup one session's renewal stranded the others, until its dashboard copied the newest login every 30 seconds (`devtools/dashboard/logins.py`).
    - The browser and its cookies stay on the host, with the cookies in the host's secret store.
    - This absorbs `conversation`.
22. **(agreed)** **The resolver is a planner plus a run.** The run's units are concerns, each waiting on the concerns it depends on and on the operator's approval. Each is worked by a spawned worker in its own worktree. Then come the merge onto one branch and a recheck of every concern.
    - The first lup's 11.8k lines carried their own worktree leases, question delivery, persistence and process launching. Those come from shared parts here (worktrees, the inbox, runs, spawn, the gate).
    - That doubles as a check of the parts: if the resolver isn't small, one is missing.
    - It probably requires `git-workflow`. Its own note settles the rest, with inkwell's evidence (#200–#204, 144 fix commits).
23. **(agreed)** **`setup` is kept,** with its CLI and its dashboard pane, which becomes a module panel. *(leaning)* Secrets go to the host's secret store by default, since `DESIGN.md` makes `.env*.local` unreadable, and the masked display shows no leading characters (the first lup showed six, `devtools/setup.py:117`).
24. **(leaning)** **What the first lup's environment had that the design lacked:**
    - **Code-intelligence tools for agents:** find references, rename a symbol, hover, definition (`tools/lsp/tools.py`), used by adlib, nori and swarm-search.
    - **Host companions:** host processes a project declares per session, like adlib's live preview (`launch/companions.py`). They're handlers of the host service.
    - **Reaching the operator off the page:** the status line and desktop notices. They're notification channels of the inbox.
    - **Merge safety:** checking that a resolution didn't drop code (`git conflict audit`). This goes in `git-workflow`.
    - **Steering beyond pause:** interrupt, redirect, stop, and reading a transcript in the page. This goes in the dashboard.
    - **Defect reports to vendors** about components lup doesn't own.

## Still open

25. **The core's size.** `DESIGN.md`'s core lists about ten parts. *The agent's slight lean:* the core is what every module talks through (the declaration, the hook, the host service, the inbox and the dashboard's protocol), and launch, judging and worktrees become default modules.
26. **`tracked-repositories`.** The first lup's registry served eight purposes. Three are gone by decision: following lup through a writable mount, pins to branches, and harvesting downstream commits. Its commands saw 0–4 uses each. What's left is mostly a map from names to paths, which cross-project spawn, read-only mounts of known projects, the adopting pass and the downstream gate all read. *The agent's lean:* the registry is the core's, in two layers, as the first lup's `sync.json` and `sync.json.local` were. The person's config maps names to paths on this machine, and the project's declaration names what it reads or mounts. Per-machine facts (GPU grants, the difftool) go in the person's config or the room's declaration, and the `sync` commands go.
27. **`meta`** (skills for authoring skills; no uses in the measured window). *The agent's lean:* each kind's authoring tool lives with its kind (`lup rules new` in `CodeRules`).
28. **Waking a main session whose turn has ended.** harmon never ended its turn. lup can't copy that: a hold past the hour rebuilds the context, keepalive loops are declined, and Codex can't hold a turn open.
29. **The adopting pass's name.** `DESIGN.md` calls it `/lup:sync`, which collides with the first lup's `sync`.

## Build order

30. **(leaning)** Each step is built on the ones before it.
    1. **The library's first slice** (`docs/library.md`, approved). live-translator moves onto it.
    2. **Tools and events:** project tools, where they run, large results to a file, tool search control, the typed events anything long-running emits.
    3. **Rooms,** starting with a spike: the CLI inside the container, the SDK on the host, and in-process tools carried over the container's standard input and output.
    4. **Runs,** which barely depend on agent calls, so they can be built alongside any step. nori moves onto them.
    5. **Launch on rooms,** with the parts of the declaration it reads (guidance, skills, session settings).
    6. **The host service, the inbox, and lup's tools:** spawn, `propose`, message, ask.
    7. **Worktrees and landing,** with the dependency guard and the landing refusal.
    8. **The dashboard:** agents, the inbox, runs, panels.

    lup can host its own development once steps 5–7 are done. Then come budgets, `accounts`, the feedback modules, the outcome loop, the resolver, setup, the Codex capability check, and trust on launch.

    Already built: the engine and its 45 rules, the gate, and the judge, which is reshaped by decisions 6 and 8 before it goes live again. The declaration is built only as large as the steps above need.

## Checks owed

- **Codex:** can a hook hold an `apply_patch` that builds on an unapproved design? If not, the call is refused with "propose X first" until it's checked.
- **Rooms:** does the CLI run inside a container while the SDK and lup's in-process tools stay on the host? The SDK talks to the CLI over standard input and output, so a `podman run -i` wrapper as the CLI path should carry them.
- **Claude Code:** does resuming an SDK session work on the current version? The first lup measured "offered but not honoured" on 2.1.237.
- **Claude Code:** do parallel held calls in one response reach the operator as one review?

## What changes in `DESIGN.md`

- **The environment: core and modules:**
  - modules may depend on modules, declared (19);
  - the core gains the host service and the inbox (17, 18);
  - `coordination` keeps the roster and handoffs;
  - `budgets` requires `accounts`;
  - the resolver is a planner plus a run (22);
  - `setup` is kept (23);
  - `conversation` and `realtime` leave the list for `accounts` and the core's inbox (18, 21);
  - `reflection` requires the outcome loop.
- **Sessions:**
  - *A review queues; the agent carries on* becomes proposing (6, 7);
  - *Coordination is light* takes the inbox (18);
  - lup's spawn returns the typed hand-back (14);
  - the host service gets a paragraph (17).
- **Budgets:** require `accounts` for usage windows.
- **Policy:**
  - the ask becomes the proposal, with the dependency guard and the landing refusal (6);
  - *A declined change is restored* follows decision 7;
  - a design change made through the shell is unproposed, not refused (6, 8).
- **Code rules and the gate:**
  - rules at the edit and at the gate (3, 4, 5);
  - the gate runs lup's rules (since be47f6b).
- **Calling agents from code:**
  - sessions (9, 10), rooms (11), where tools run and images (12, 13);
  - the speaking tools (31), the guarantee as what can happen (32), lup's own tool server (33);
  - the additions from the first lup (15);
  - a runs subsection (16).
- **Sessions:** every session lup launches serves the speaking tools (31).
- **The dashboard:** panels (20), runs shown (16), unproposed work shown (6), steering (24).
- **Feedback:** the hand-back's `how_it_felt` (14).
- **Graveyard:**
  - parking reviews and the drafts flow;
  - approval at landing;
  - a cap on unproposed code;
  - modules never depending on each other;
  - running a half-built judge on its own construction;
  - each with its reason above.
- **Open questions:**
  - 11 settles (8), and 4 takes `Session` and `async with` (9);
  - 25–29 are added.
- **Checks owed:** the four above.
- **Build order:** decision 30 replaces phase 1's steps; the bridge's paragraph takes decision 2.
