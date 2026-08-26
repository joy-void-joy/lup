"""Canonical declaration for the init skill."""

import lup.harness.models as models
import lup_template.devtools.harness.content.provenance as provenance

SPELLING = provenance.Provenance(
    library_git="git",
    project_devtools="uv run lup-devtools",
    library_checkout="<lup-checkout>",
)
"""One checkout, unqualified: this skill turns the library's clone into the project."""

# lup: solved: Initialization never configures the seams. It interviews the domain,
# prunes scaffolding, and walks the `# lup: template:` markers, but the points a
# project is meant to settle about *itself* — the `DevProject` declaration, the
# `HookSet` in its catalog, its path roles, and above all which of the library's
# scan rules it holds itself to — are left at the library's defaults without
# ever being put to anyone. A default nobody was shown is not a decision, and
# `RuleSelection` exists precisely because a repository that settled a
# convention differently is not defective there. Add a phase that puts each seam
# to the user, and offer removing the anti-patterns altogether as one of the
# answers: a domain that does not want them should be able to say so once at
# init rather than retire thirty ids one at a time, or discover the whole family
# only when an edit is denied by a rule it never agreed to.
# lup: solved: `/lup:init` never asks who owns README.md. `human_owned_files` in
# src/lup_template/devtools/harness/catalog.py locks it, so an initialized
# domain inherits an approval gate on the one file it most wants the agent to
# write, and no phase surfaces the choice. Ask it here alongside the other
# ownership decisions, and make unlocking a `lup-devtools` command that edits
# the declaration and regenerates — not a hand edit of the catalog.
# lup: solved: that branch answers the ownership seam a
# second way, with `dev init ownership --lock/--unlock`, and rewrote these same
# two claims into `solved:` by way of it. So merging conflicts exactly here,
# which is the right place for the collision to surface — but the standing
# merge guidance biases toward inclusion, and inclusion is the wrong answer to
# a duplicate. `dev seams` is the one to keep: it settles all four seams rather
# than ownership alone, it sits in the library where every adopter reaches it
# rather than in this application, and it wires install as well as init. Drop
# `dev init ownership` from src/lup_template/devtools/dev/init.py and its
# command in that package's app.py when the branch merges, leaving one
# `solved:` pair here rather than two.
SKILL = models.Skill(
    id="skill.init",
    name="init",
    description="Initialize the self-improvement loop for a specific domain",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv sync:*, uv run pyright:*, uv run ruff:*, uv run pytest:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
    ],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=r"""# Initialize Self-Improvement Loop

This command sets up the project identity, renames the source package, and customizes the feedback collection, metrics, and trace analysis for your specific agent domain.

**This project builds on an agent SDK, not raw model API calls.** The SDK is the default and expected framework. If the user wants bare API calls instead, ask them to explain why -- the SDK provides structured outputs, tool use, subagents, and hooks out of the box.

## Your Task

Interview the user about their domain, rename the source package, and generate the appropriate scaffolding.

### The branch you start from is the library you get

This checkout is a clone of lup, so the branch it stands on *is* the library
version the project begins at: `packages/lup/` is that branch's code, and the
acquisition mode settled in Phase 2 pins that same ref. A feature branch
carries work the stable branch has not reviewed, and nothing downstream
announces that. Resolve both before Phase 0, while `origin` still points at lup
rather than at the project's own repository:

"""
            ),
            *provenance.branch_probes(SPELLING),
            models.TextPart(
                text=r"""This checkout is the one supplying the library, and `packages/lup/` is whatever
branch is checked out — so if the answer was the stable branch, `git switch` to
it now, before Phase 0 reads anything.

## Phase 0: Check for DESIGN.md

Before starting the interview, check if `DESIGN.md` exists in the project root. If it does:

1. Read it thoroughly
2. Use it as context for the entire init process -- it contains design decisions from a `"""
            ),
            models.SkillInvocation(plugin="lup", skill="brainstorm"),
            models.TextPart(
                text=r"""` session
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
resolves later — decides which files exist at the end. """
            ),
            models.AskUser(
                question="each identity answer that decides what gets generated, "
                "with the reading you would pick offered first"
            ),
            models.TextPart(
                text=r""" rather than leaving it in prose the user has to notice and correct.

## Phase 1.5: Prune Scaffolding

Before customizing, decide which optional patterns this domain actually needs. The template ships them all wired; most domains use a subset, and **deleting the rest is the goal, not a failure** (see the guidance file's § Scaffolding Is a Menu, Not a Mandate). From the interview answers, classify each as KEEP-and-customize or DELETE-the-files:

- **Reflection** (`agent/tools/reflect.py` + the gate wiring in `core.py`) — keep only if the agent commits a consequential, judgment-bearing output where self-critique helps.
- **Realtime / persistent mode** (`agent/tools/realtime.py`, `lup.realtime*`, the Stop-hook/sleep-wake wiring) — keep only for agents that live over time (chat, monitoring, games); delete for one-shot agents.
- **Feedback loop** (the `feedback` sub-app this project inherits from `lup.devtools`, and the feedback-loop skill) — keep only if ground truth or a feedback signal resolves over time. Dropping it is a line in `devtools/subapps.py`, not a directory to delete: the commands are the library's.
- **Commit loop** (auto-commit in `environment/cli/__main__.py`) — keep only if each run yields a data artifact worth versioning. Session data is gitignored by default (the `notes/*` lines in `.gitignore`), so traces and outputs stay local; keeping this pattern means removing the `notes/*` and `!notes/.gitkeep` pair so session data can be committed. The `notes/harness/` line under them is not part of that decision and stays either way — a launch transcript is one native CLI session in full, redacted for portability rather than for publication. When deleting the pattern, leave every ignore line in place.

"""
            ),
            models.AskUser(
                question="which of these four patterns this domain keeps, "
                "one option per pattern"
            ),
            models.TextPart(
                text=r""" — deleting is the expected answer for most of them, so say which you would
delete and why. Then **delete the files and their wiring** for everything not
kept before proceeding. The customization steps below apply only to what you kept.

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

This handles directory rename (`src/lup_template/` -> `src/<project>/`), import updates, pyproject.toml entry points, CLI app name, and the plugin marketplace name -- all in one shot. The marketplace registration in each tree ("""
            ),
            models.NativePath(location="marketplace", scope="every_tree"),
            models.TextPart(
                text=r""") is named `<project>` so it doesn't collide in the global marketplace namespace, while the plugin entry stays `lup` (so `"""
            ),
            models.SkillPattern(plugin="lup", placeholder="*"),
            models.TextPart(
                text=r"""` is identical everywhere). Framework vocabulary (`lup_tool`, `lup-devtools`, `.lup/`, etc.) is preserved automatically.

### After renaming:

#### 1. Declare how the project obtains lup

The template ships the library vendored under `packages/lup/`, which makes the
project a fork of it. The rename is what allows leaving that mode: `dev library`
refuses to un-vendor while `src/lup_template/` is present, because an
uninitialized template and the lup repository are the same bytes and nothing
else separates them.

"""
            ),
            *provenance.acquisition(SPELLING),
            models.TextPart(
                text=r"""The command prints the `uv sync` and the regeneration it wants next. Run both
before anything reads the project's types.

#### 2. Merge the guidance template into the guidance declaration

The merge lands in `src/<project>/devtools/harness/content/guidance.py`, never in a tree's guidance file ("""
            ),
            models.NativePath(location="guidance_file", scope="every_tree"),
            models.TextPart(
                text=r"""): those are generation's outputs, and an edit made directly to one is undone the next time the harness runs. Take the sections from that tree's template flavor ("""
            ),
            models.PluginPath(
                plugin="lup", location="guidance_template", scope="every_tree"
            ),
            models.TextPart(
                text=r"""), covering every tree the project commits:

1. Read the template and replace `<project>` placeholders with the actual project name
2. Read the existing declaration
3. Use the `<!-- section: ... -->` markers in the template to identify independent merge units
4. Compare sections: for each marked section, check whether the declaration already composes it (by heading match)
5. Add missing sections to the declaration
6. Leave existing sections untouched -- don't overwrite content the project already has
7. Regenerate with `uv run lup-devtools harness generate all`, which is what carries the merged sections into every tree

The template is a menu, not a document to adopt whole. Guidance is loaded on
every turn and is held to a byte budget for a reason a reader never sees
otherwise: a runtime that caps how much project documentation it will load
stops adding at the cap, so an over-budget guidance file is not an error, it is
silent truncation. Generation enforces that ceiling and refuses the merged
declaration, naming the overage — so take the sections this domain will act on,
and leave the rest to the pages under `docs/` that already carry them.

Clearing the scaffold flag is also what hands this domain its room. While the
flag stood, the template was held to a *smaller* ceiling than the runtime's,
holding roughly 12 KiB back on purpose — so what you inherit is a deliberately
lean document with space to say what is true of this domain, not a full budget
already spent on somebody else's conventions. `dev guidance` reports what each
section costs, and after adoption only the runtime ceiling applies.

Which runtimes the project carries is not a choice made here: every tree
arrives with the clone, and generation writes each one it finds. Dropping a
runtime is a later removal somebody decides on its own terms.

#### 3. Initialize upstream sync

"""
            ),
            *provenance.sync_baseline(SPELLING),
            models.TextPart(
                text=r"""That checkout is one you provide: clone the library beside the project, then
`git switch --detach <commit>` it to the recorded commit. Not this project's
own checkout — it stands at that commit too, and naming it makes the review
read the project's own history as upstream work. The linked mode's checkout can
serve when it already stands there, but it is someone's working checkout and is
not yours to move.

A recorded path is read in place and never fetched, so whichever checkout you
name is the one to update before a review. The branch may also have advanced
since this project was cloned, and a checkpoint taken from its tip marks the
commits in between as already reviewed when the project does not carry them.

#### 4. Verify

```bash
uv sync
uv run pyright
uv run ruff check .
uv run pytest
<project> --help
```

## Phase 2.5: Settle the Seams

Everything above customizes what the project *is*. This phase settles what it
holds *itself* to, and it exists because a default nobody was shown is not a
decision. The library ships each of these as a starting point, and a domain
that would have answered differently never finds out it could until an edit is
denied by a rule it never agreed to.

Put each one to the user rather than letting the default stand by silence.

### 1. Which rules this domain holds itself to

`RuleSelection` names which of the rules the library ships this project keeps.
Its own docstring is the point: a rule is a convention written down and a
convention is a judgement, so a repository that settled one differently "is not
answering it wrongly — it is answering a question this library had no standing
to close." The selection is subtractive, so a project that disagrees with three
rules names those three rather than restating the thirty it keeps.

Show the families before asking — `uv run lup-devtools dev rules` writes the
generated index, and every rule in it carries the shape it matches and the
diagnostic it prints. Then """
            ),
            models.AskUser(
                question="which rule families this domain keeps, "
                "with retiring the anti-pattern family altogether as one answer"
            ),
            models.TextPart(
                text=r""". Offer the whole-family answer explicitly: a domain that does not want the
anti-pattern rules should be able to say so once, here, rather than retire
thirty ids one at a time as it meets them.

### 2. Who owns which files

A human-owned file surfaces every agent edit as an approval, so the agent
proposes rather than writes. The template ships `README.md` that way, which is
right for a file whose words are the author's and wrong for a project that
wants its README kept current by the agent.

```bash
uv run lup-devtools dev init ownership
```

"""
            ),
            models.AskUser(
                question="which files the human author owns, "
                "starting from whether README.md stays locked"
            ),
            models.TextPart(
                text=r""" — then apply the answer with `--lock` / `--unlock` on that same command,
which rewrites the declaration and regenerates the native trees. Never
hand-edit `human_owned_files` in the catalog.

### 3. What each path role means here

`HookPathRole` says which roots are scratch, which are source, and which are
tests. The template's roles describe the template's own tree, and a domain that
keeps its data somewhere else, or vendors a dependency, has roots the shipped
list does not mention. Read the declared roles, then """
            ),
            models.AskUser(
                question="whether any root this domain adds needs a path role, "
                "and which"
            ),
            models.TextPart(
                text=r""".

### 4. Whether tests are held still

An **acceptance guard** asks an ordinary session before it edits a test and
refuses an autonomous one outright, because for an autonomous worker those
tests are the specification it implements against. It is worth having exactly
when this domain will run unattended sessions against a test suite it must not
rewrite, and worth skipping when it will not. """
            ),
            models.AskUser(
                question="whether this domain declares an acceptance guard "
                "over its test roots"
            ),
            models.TextPart(
                text=r"""

Record each answer in the catalog, then regenerate and confirm the trees moved:

```bash
uv run lup-devtools harness generate all
```

An answer left at the default is fine — but it should be an answer, not a
silence. Where the user defers one, say which default now stands.

## Phase 3: Generate Scaffolding

**Start by gathering every customization point.** Each decision the template leaves to a domain carries a `# lup: template:` marker with a one-line description of the decision. Collect them all:

```bash
uv run lup-devtools dev todos --json
```

Walk the collected decision points one by one — each entry gives the file, line, decision text, and surrounding context. For every marker, either customize the code it points at and remove the marker, or delete it along with scaffolding pruned in Phase 1.5. The numbered steps below give domain guidance for the major ones, but the gathered list is the source of truth: a marker you never reach is a decision silently defaulted.

Based on the answers from Phase 1, generate or modify:

### 1. `src/<project>/agent/models.py`

Customize AgentOutput for the domain:

- Add domain-specific fields (probability, move, response, etc.)

### 2. `src/<project>/agent/prompts.py`

Update the system prompt template for the domain. Focus on what the agent does and how to reason -- tools self-document via their descriptions, so listing them in the prompt creates a second source of truth that drifts as tools change.

### 3. `src/<project>/agent/subagents.py`

Create domain-appropriate subagents (researcher, analyzer, etc.)

### 4. `src/<project>/environment/cli/__main__.py`

Customize the CLI for the domain's task format:

- Update the `loop` command to accept domain-specific task inputs
- Customize `_commit_results()` message format (e.g., `data(forecasts):` instead of `data(sessions):`)
- Configure auto-commit behavior: enable/disable by default, target branch (main for data-only commits, or a dedicated branch) — requires the `notes/` ignore lines removed in Phase 1.5
- Add domain-specific CLI commands if needed

### 5. Agent Version

Set `agent_version` under `[tool.lup]` in `pyproject.toml` and explain bump rules for this domain.

### 6. Reflection (only if kept in Phase 1.5)

If this domain has no consequential, judgment-bearing output, you already deleted `reflect.py` and its gate — skip this step. Otherwise customize `src/<project>/agent/tools/reflect.py`:

- Extend `ReflectInput` with domain-specific fields (factor analysis, move evaluation, etc.)
- Customize the reviewer prompt for the domain's common failure modes
- The reviewer runs on the strongest aux model available (see the guidance file's § Model Selection); pass `skip_reviewer=True` per call for speed-sensitive or trivial tasks

The reflection gate (`lup.reflect`) is domain-neutral and doesn't need modification. Only the tool and its input model are domain-specific.

### 7. `devtools/feedback/state.py`

The feedback collection module (exposed via `uv run lup-devtools feedback collect`). Customize `load_outcomes()` and `compute_metrics()` for the domain's ground truth type.

### 8. Update the guidance

Edit `src/<project>/devtools/harness/content/guidance.py`, then regenerate with `uv run lup-devtools harness generate all` -- """
            ),
            models.NativePath(location="guidance_file", scope="every_tree"),
            models.TextPart(
                text=r""" are its outputs, and editing them directly is undone by the next generation.

The guidance should already carry the template sections from the Phase 2 merge. Now add domain-specific content based on the interview answers:

- Fill in the Project Overview placeholder with the domain description
- Add domain-specific commands and examples
- Add metrics and feedback collection instructions relevant to this domain
- Add any domain-specific context sections (Important Context, data sources, constraints)

### 9. Tool Description Standards

The agent discovers tools through their descriptions -- a terse description means the agent can't tell when or why to use it. Each description should answer:

1. **What** -- What does this tool do? (concrete behavior, not vague summary)
2. **When** -- When should the agent reach for this tool? (triggers, conditions)
3. **Why** -- Why does this tool exist? (what problem it solves, what gap it fills)

See `src/<project>/agent/tools/example.py` for the pattern.

### 10. Setup Wizard (`src/<project>/devtools/setup.py`)

Customize the interactive setup wizard for the domain's integrations:

- Replace the template integrations (Slack, Google, Notion, Example API) with the domain's actual services
- Update the `INTEGRATIONS` list — each entry is an `Integration(name, env_keys, setup_func, status_func)`
- Add corresponding `@app.command()` subcommands for individual integration setup
- Update env var names in `config.py` to match what the setup wizard writes to `.env.local`
- Verify `lup-devtools dashboard` exposes the same registry: declarative fields become browser forms, while bespoke flows link back to their CLI command

The framework (env helpers, status table, mask, clipboard, browser open, wizard flow) is reusable — only the integration functions and registry need customization.

The registry is a list of services, and which ones this domain has is the
domain's answer rather than a guess from the code — so """
            ),
            models.AskUser(
                question="which external services the agent uses, "
                "and for each whether it authenticates by OAuth flow, "
                "API key, or a credentials file"
            ),
            models.TextPart(
                text=r""" before rewriting `INTEGRATIONS`.

### 11. Update `feedback-loop.md`

Customize the feedback loop command for the domain's specific:

- Ground truth type
- Metrics to analyze
- Trace inspection approach

## Phase 4: Verify Setup

After generating files:

1. Run `uv run lup-devtools dev todos` -- any remaining `# lup: template:` marker is a decision not yet made; resolve or consciously defer each one. Resolving one means writing this domain's code where the placeholder stood and deleting the marker: it is not feedback, so it takes no `solved:` claim. Renaming the package cleared `[tool.lup] template`, so from here on `dev check` lists every marker still standing -- park one you mean to leave with `# lup: defer:` rather than letting it sit unexplained
2. Run the pre-flight bar, which is ruff, pyright and the suite in one pass and
   reports as it goes:

"""
            ),
            models.WatchOutput(command="uv run lup-devtools dev check"),
            models.TextPart(
                text=r"""

3. Run `uv run lup --help` to verify CLI
4. Verify the feedback loop command references the right scripts
5. Regenerate both harnesses and check that the rendered guidance accurately describes the domain

## After Initialization

Once the scaffolding is generated, guide the user to:

1. Run a few sessions: `uv run lup loop "task1" "task2"`
2. Review traces in `notes/traces/`
3. Use `"""
            ),
            models.SkillInvocation(plugin="lup", skill="feedback-loop"),
            models.TextPart(
                text=r"""` to analyze and improve
4. Iterate on the feedback collection as patterns emerge

## Key Files to Customize

`docs/template.md` answers this from the checkout rather than from a list that
has to be maintained: it draws the package as it actually stands, captions each
module with its own docstring, and carries a table of what to adapt in each.

The order they usually get touched in: `agent/models.py` for the result the
domain produces, `agent/prompts.py` for what the agent is told, then
`agent/toolsets.py` and `agent/tools/` for what it can do.
"""
            ),
        ],
    ),
)
