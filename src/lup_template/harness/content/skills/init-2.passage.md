This checkout is the one supplying the library, and `packages/lup/` is whatever
branch is checked out — so if the answer was the stable branch, `git switch` to
it now, before Phase 0 reads anything.

## Phase 0: Check for DESIGN.md

Before starting the interview, check if `DESIGN.md` exists in the project root. If it does:

1. Read it thoroughly
2. Use it as context for the entire init process -- it contains design decisions from a `{{ brainstorm_skill }}` session
3. Still run the full interview, but reference design decisions when asking questions (e.g., "DESIGN.md mentions you want a persistent agent with sleep/wake -- does that still hold?")
4. Skip questions whose answers are unambiguously covered in the design doc
5. If no DESIGN.md exists, proceed normally

## Phase 1: Project Identity

Determine the project name by asking:

### 1. Project Name

- What should the project be called? This becomes the Python package name.
- Must be a valid Python identifier (lowercase, underscores, no hyphens or spaces).
- Examples: `aib`, `forecast_bot`, `coach`, `game_agent`

### 2. Agent Purpose

- What does the agent do? (forecasting, coaching, game playing, task completion, etc.)
- What is a "session" or "run"? (one forecast, one conversation, one game, one task)

### 3. Ground Truth & Success Metrics

- How do you know if the agent did well?
  - **External ground truth**: Outcomes that resolve later (predictions, game wins, task success)
  - **Human feedback**: Ratings, corrections, preferences
  - **Proxy metrics**: Engagement time, task completion, coherence scores
  - **Self-assessment**: Agent's own meta-reflection quality
  - **No clear ground truth**: Focus on process quality and trace analysis

### 4. What to Track

- What outputs should be saved per session?
- What metrics matter? (accuracy, cost, time, tool usage, user satisfaction)
- What trace data is valuable? (reasoning, tool calls, intermediate states)

### 5. Feedback Sources

- Where does feedback come from?
  - Resolution/outcome data
  - User ratings or corrections
  - Comparison against baselines
  - Expert review
  - Automated quality checks

### 6. Task Format

- How are tasks provided to the agent? (free text, IDs, files, API calls)
- Should the `loop` CLI command batch-process them?
- What does auto-commit look like for this domain?

## Interviewing Style

Ask extensively -- don't make assumptions about the domain. Ask open-ended questions first, then drill into specifics. Example questions (adapt based on context):

- "What should this project be called? (valid Python package name, e.g., 'aib', 'forecast_bot')"
- "What does your agent do and what does a single session look like?"
- "How do you know if the agent did well? Is there ground truth that resolves later?"
- "What metrics matter most to you?"
- "How are tasks provided -- free text, IDs, files, API calls?"
- "Should results auto-commit after each session?"
- "What tools or APIs will the agent need?"

Let the conversation flow naturally. The goal is to understand the domain well enough to customize the template files below.

Open-ended exploration is ordinary conversation, but every answer that *forks
the scaffolding* — the package name, what a run is, whether ground truth
resolves later — decides which files exist at the end. {{ ask }} rather than leaving it in prose the user has to notice and correct.

## Phase 1.5: Choose the Modules

First, the part that is not a decision. The template ships demonstrations of
*itself* — `examples/` composing lup's own runtime against lup's own README,
and the test modules driving them. A domain that adopted the template is a
consumer of that library rather than a demonstrator of it, so what it inherits
there is a directory it will never run and a suite it has to keep green. Run:

```bash
uv run lup-devtools dev init drop-examples --dry-run
uv run lup-devtools dev init drop-examples
```

It reports the handful of lines still naming what went — a README link, two
docstring citations, and the `"examples/"` composition root in the catalog,
which is dead once the directory is. Fix those; the README is human-owned, so
propose that edit rather than making it.

Now the decisions, and there is one kind of them. Everything lup ships belongs
to a **module** — a subject as one value, carrying its skills, its agents, its
page under `docs/`, its paragraph in the always-loaded document, its command
tree and its tool group. A module is taken or declined whole, so there is no
keeping a subject's skills and deleting its page, and there are no files to
hunt down: declining is a name in a list.

Start by reading the roster, which is the only complete statement of what is on
offer:

```bash
uv run lup-devtools dev modules --verbose
```

Each row says what the module is, whether this project has it, what its prose
costs in the always-loaded document, and what it contributes. Walk it against
the interview answers. **Declining is the expected answer for several of them,
and it is not a loss** — a module a domain has no subject for spends guidance
budget and session context every time and earns nothing. Three ship off by
default and are worth naming here, because each is a real capability rather
than a leftover:

- **`reflection`** — the gate an agent meets on its own output, an independent reviewer between finishing the work and submitting it. Take it if the agent commits a consequential, judgment-bearing output where self-critique helps.
- **`realtime`** — persistent agents that control their own attention: the sleep/wake loop, and the relay that spells it for subprocess backends. Take it for an agent that lives over time (chat, monitoring, a game), never for a one-shot one.
- **`feedback-loop`** — turning an observed agent failure into a durable capability change. Take it only if ground truth or a feedback signal resolves over time; a domain whose output nobody grades has nothing to feed it.

Ask about every module the roster offers rather than only those three — this
list goes stale and `dev modules` does not.

{{ ask_2 }} — for each, say which way you would go and why, from what the interview
established rather than from what sounds useful.

Write the answer as module ids in `DECLINED`, in `harness/content/catalog.py`.
Nothing else changes: a declined module's skills, page, prose, commands and
tools stop arriving together, and a module left unnamed keeps its own default —
including the ones lup grows after that line was last edited, which is why the
list is refusals rather than what is kept. Then regenerate with
`uv run lup-devtools harness generate all` and re-read `dev modules`.

One decision in this phase is *not* a module, because it is this template's own
wiring rather than a subject lup ships. **Commit loop** (auto-commit in `environment/cli/__main__.py`) — keep only if each run yields a data artifact worth versioning. Session data is gitignored by default (the `notes/*` lines in `.gitignore`), so traces and outputs stay local; keeping this pattern means removing the `notes/*` and `!notes/.gitkeep` pair so session data can be committed. The `notes/harness/` line under them is not part of that decision and stays either way — a launch transcript is one native CLI session in full, redacted for portability rather than for publication. When deleting the pattern, leave every ignore line in place.

The customization steps below apply only to what you kept.

## Phase 1.6: Settle the Seams

A seam is a place the library holds an opinion this domain is meant to overrule, and every one of them ships at a default. **A default nobody was shown is not a decision** — so put each of them to the user rather than letting the scaffold's answer become theirs by silence.

Run `uv run lup-devtools dev seams`. It prints each seam, what it currently holds, and where it is written. Take them one at a time:

- **Who owns which files.** A human-owned file surfaces every change as an approval and the agent does not write it — it proposes the edit instead. `README.md` ships owned, which is right for a scaffold whose README describes the scaffold and often wrong for a domain whose README is the one file it most wants written for it. Ask; `dev seams --disown README.md` or `--own <path>` writes the answer.
- **Which trees an edit needs approval into.** What ships answers for a framework that generates its own plugin trees and carries its own policy. A domain whose sensitive files are a data directory, a migration set or a deployment manifest says so instead.
- **What each tree is for.** A role is how every gate tells a fixture from production and a build product from work, so a data directory, a notebook tree or a generated client belongs here — once, where all of them read it.
- **Which scan rules this domain holds itself to.** A convention is a judgement, and a repository that settled one differently is not defective there. Offer three answers and mean all three: keep them, drop a named few (`dev seams --retire <rule-id>`), or **drop the family outright** (`dev seams --retire-all`). Dropping the family is a legitimate answer given once here, rather than thirty retirements discovered one denial at a time.

Every one of these is also a `# lup: template:` marker in the catalog, so `dev todos` lists any left standing and Phase 4 meets them again. Answering here is what keeps that list from being the first time anyone sees the choice.

Each answer edits the declaration; **regenerate afterwards** with `uv run lup-devtools harness generate all`, because the compiled plugin trees are what the gates actually read.

## Phase 2: Rename Package

Run the devtool to rename the package. Preview first with `--dry-run`, then execute:

```bash
uv run lup-devtools dev init rename-package <project> --dry-run
uv run lup-devtools dev init rename-package <project>
```

This handles directory rename (`src/lup_template/` -> `src/<project>/`), import updates, pyproject.toml entry points, CLI app name, and the plugin marketplace name -- all in one shot. The marketplace registration in each tree ({{ marketplace_path }}) is named `<project>` so it doesn't collide in the global marketplace namespace, while the plugin entry stays `lup` (so `{{ skill_pattern }}` is identical everywhere). Framework vocabulary (`lup_tool`, `lup-devtools`, `.lup/`, etc.) is preserved automatically.

### After renaming:

#### 1. Declare how the project obtains lup

The template ships the library vendored under `packages/lup/`, which makes the
project a fork of it. The rename is what allows leaving that mode: `dev library`
refuses to un-vendor while `src/lup_template/` is present, because an
uninitialized template and the lup repository are the same bytes and nothing
else separates them.

