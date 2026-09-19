That checkout is one you provide: clone the library beside the project, then
`git switch --detach <commit>` it to the recorded commit. Not this project's
own checkout — it stands at that commit too, and naming it makes the review
read the project's own history as upstream work. Any clone standing at that
commit serves, as long as it is not one somebody is working in: a checkout
that moves under the review is one whose history the review misreads.

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
diagnostic it prints. Then {{ ask }}. Offer the whole-family answer explicitly: a domain that does not want the
anti-pattern rules should be able to say so once, here, rather than retire
thirty ids one at a time as it meets them.

### 2. Who owns which files

A human-owned file surfaces every agent edit as an approval, so the agent
proposes rather than writes. The template ships `README.md` that way, which is
right for a file whose words are the author's and wrong for a project that
wants its README kept current by the agent.

{{ ask_2 }} — then apply the answer with `--lock` / `--unlock` on that same command,
which rewrites the declaration and regenerates the native trees. Never
hand-edit `human_owned_files` in the catalog.

### 3. What each path role means here

`HookPathRole` says which roots are scratch, which are source, and which are
tests. The template's roles describe the template's own tree, and a domain that
keeps its data somewhere else, or vendors a dependency, has roots the shipped
list does not mention. Read the declared roles, then {{ ask_3 }}.

### 4. Whether tests are held still

An **acceptance guard** asks an ordinary session before it edits a test and
refuses an autonomous one outright, because for an autonomous worker those
tests are the specification it implements against. It is worth having exactly
when this domain will run unattended sessions against a test suite it must not
rewrite, and worth skipping when it will not. {{ ask_4 }}

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

Walk the collected decision points one by one — each entry gives the file, line, decision text, and surrounding context. For every marker, either customize the code it points at and remove the marker, or delete it along with whatever Phase 1.5 declined. The numbered steps below give domain guidance for the major ones, but the gathered list is the source of truth: a marker you never reach is a decision silently defaulted.

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

### 6. Reflection (only if the `reflection` module was taken in Phase 1.5)

If this domain has no consequential, judgment-bearing output, `reflection` is in `DECLINED` and its tool group never reaches a session — skip this step. Otherwise customize `src/<project>/agent/tools/reflect.py`:

- Extend `ReflectInput` with domain-specific fields (factor analysis, move evaluation, etc.)
- Customize the reviewer prompt for the domain's common failure modes
- The reviewer runs on the strongest aux model available (see the guidance file's § Model Selection); pass `skip_reviewer=True` per call for speed-sensitive or trivial tasks

The reflection gate (`lup.orchestration.reflection`) is domain-neutral and doesn't need modification. Only the tool and its input model are domain-specific.

### 7. `devtools/feedback/state.py`

The feedback collection module (exposed via `uv run lup-devtools feedback collect`). Customize `load_outcomes()` and `compute_metrics()` for the domain's ground truth type.

### 8. Update the guidance

Edit `src/<project>/harness/content/guidance.py`, then regenerate with `uv run lup-devtools harness generate all` -- {{ guidance_file_path }} are its outputs, and editing them directly is undone by the next generation.

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
- Verify `lup-devtools setup dashboard` exposes the same registry: declarative fields become browser forms, while bespoke flows link back to their CLI command

The framework (env helpers, status table, mask, clipboard, browser open, wizard flow) is reusable — only the integration functions and registry need customization.

The registry is a list of services, and which ones this domain has is the
domain's answer rather than a guess from the code — so {{ ask_5 }} before rewriting `INTEGRATIONS`.

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

{{ watch }}

3. Run `uv run lup --help` to verify CLI
4. Verify the feedback loop command references the right scripts
5. Regenerate both harnesses and check that the rendered guidance accurately describes the domain

## After Initialization

Once the scaffolding is generated, guide the user to:

1. Run a few sessions: `uv run lup loop "task1" "task2"`
2. Review traces in `notes/traces/`
3. Use `{{ feedback_loop_skill }}` to analyze and improve
4. Iterate on the feedback collection as patterns emerge

## Key Files to Customize

`docs/template.md` answers this from the checkout rather than from a list that
has to be maintained: it draws the package as it actually stands, captions each
module with its own docstring, and carries a table of what to adapt in each.

The order they usually get touched in: `agent/models.py` for the result the
domain produces, `agent/prompts.py` for what the agent is told, then
`agent/toolsets.py` and `agent/tools/` for what it can do.
