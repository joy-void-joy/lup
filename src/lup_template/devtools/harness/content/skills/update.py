"""Canonical declaration for the update skill."""

import lup.harness.models as models
import lup_template.devtools.harness.content.provenance as provenance

SPELLING = provenance.Provenance(
    library_git="git -C <lup-checkout>",
    project_devtools="uv run lup-devtools",
    library_checkout="<lup-checkout>",
)
"""This skill stands in the project and reads a library checkout beside it."""

SKILL = models.Skill(
    id="skill.update",
    name="update",
    description="Upgrade the lup dependency, then review upstream commits and apply improvements",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv sync:*, uv lock:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="[focus area]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=r"""# Update from Upstream

Bringing a project up to date with lup is two separate jobs, and only one of
them is about reading commits.

**The dependency** is the library this project runs on. Upgrading it is a
version change plus a regeneration, and it is where almost all of upstream's
work arrives — every fix to the runtime, the policy kernel, the resolver, and
the shipped skills reaches this project by taking a newer `lup`, not by being
copied in. Do this first, because everything the review step reads is measured
against the version now installed.

**The scaffolding** is what this project forked rather than imported: its
prompts, its tools, its models, its own half of the harness declarations. No
version bump touches those, so patterns that emerged downstream have to be
read, generalized, and applied by hand. That is the second half.

**Optional focus argument:** When a focus area is provided (e.g., `"""
            ),
            models.SkillInvocation(plugin="lup", skill="update"),
            models.TextPart(text=" hooks`, `"),
            models.SkillInvocation(plugin="lup", skill="update"),
            models.TextPart(
                text=" lib/cache`), only review and port commits that touch the specified area. **Do not mark as synced** — the sync pointer stays unchanged so a future `"
            ),
            models.SkillInvocation(plugin="lup", skill="update"),
            models.TextPart(
                text=r"""` (without args) still reviews all commits from the same checkpoint.

## 1. Commit pending changes

Invoke `"""
            ),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(
                text=r"""` to commit any uncommitted work first. Both halves below rewrite files, and a dirty tree makes it impossible to tell what this run changed.

## 2. Upgrade the lup dependency

Read how this project obtains the library before changing anything — the
upgrade is a different command in each mode, and one of the four is not an
upgrade at all:

```
uv run lup-devtools dev library status
```

| Mode | What "up to date" means | How |
| --- | --- | --- |
| published | The newest release on the index | `uv run lup-devtools dev library release` to read what is published, then `uv lock --upgrade-package lup` |
| git | The tip of the ref it pins | `uv lock --upgrade-package lup` re-resolves the same ref; `dev library git --branch <branch>` moves to a different one |
| linked | Whatever the linked checkout holds | Pull in that checkout; the editable install follows it |
| local | Nothing — `packages/lup/` is a fork of the library, so upstream arrives through the commit review below rather than through a version | — |

`dev library release` asks the index rather than guessing, and reports one of
three answers: a released version, that none is published yet, or that it
could not reach the index. Treat the third as an answer about the probe and
not about the world — a look-up that did not land settles nothing, so retry or
proceed in the mode this project already knows it wants, rather than re-pinning
on a dropped connection.

Then, in every mode that changed anything:

```
uv sync
uv run lup-devtools harness generate all
```

The regeneration is not optional. A newer lup ships newer skill, agent, and
policy declarations, and this project's native trees are compiled from them —
so until it runs, the upgrade is installed but not in effect, and `harness
check all` will say the trees are stale.

Report the version moved from and to, then """
            ),
            models.AskUser(
                question="whether to continue into the commit review, "
                "given what the upgrade already brought in"
            ),
            models.TextPart(
                text=r""" — for a project that only consumes the library, the dependency bump is frequently the whole update, and reading downstream commits afterward is work with nothing to find.

## 3. Set up the tracked repositories

This half reviews commits from repositories registered in `sync.json`. If none
is registered, set one up now. Never modify the committed `sync.json` — it is
template scaffold, and every personal registration belongs in the gitignored
`sync.json.local`.

**Self-referencing repos:** When the current repo IS the upstream (e.g., the lup template itself), set `"ignore": true` in `sync.json.local` to skip it during updates. The committed `sync.json` still ships the URL so downstream users can sync from it.

"""
            ),
            *provenance.sync_baseline(SPELLING),
            models.TextPart(
                text=r"""## 4. Check for new commits

`status` reads what is already cached, so fetch before trusting it or a quiet
answer may only mean nothing new has been downloaded:

```bash
uv run lup-devtools sync fetch
uv run lup-devtools sync status
```

If no projects have new commits, report that everything is up to date and stop.

## 5. Read all diffs and build inventory

For each project with new commits:

```bash
uv run lup-devtools sync log <project>
```

Skip **data-only** commits (`data(outputs):`, `data(scores):`). For every other commit, read the **complete** diff — never truncate with `head` or skim large outputs:

```bash
uv run lup-devtools sync diff <project> <sha>
```

After reading each diff, produce an **inventory**: list every new function, class, CLI command, model, and pattern added. The inventory is purely descriptive — what was added, not whether it's useful. This prevents whole-commit dismissal: you can't skip what you've already enumerated.

Do not classify during this step. Cross-commit patterns only become visible after reading all diffs.

**If a focus area was provided:** Also skip commits whose messages clearly don't relate to the focus area. But when in doubt, keep them — the diff might touch relevant code.

## 6. Classify inventory

For each item in the inventory, ask: **"What would this look like with a generic data source?"** If you can describe a generic version, it's portable. If the item IS the domain data (model fields, API-specific calls, scoring formulas), it's domain-specific.

**Do not confuse the data a tool operates on with the tool itself.** Visualization commands, CLI watch modes, analysis pipelines, and formatting utilities are infrastructure — portable even when they currently display domain-specific data. The data source is a parameter; the infrastructure is the portable piece.

**Ask where each portable piece belongs.** A piece that any project on lup would want belongs to the library, and a library this project does not vendor is one it cannot edit here — that piece becomes a change sent upstream rather than applied locally. `dev library status` already said which mode this is. Only what is genuinely this project's own is applied in this checkout.

Classify as:

- **Portable as-is**: Improvements that apply directly without modification
  - `lup` library utilities (e.g., better `print_block`, new retry patterns, caching improvements)
  - `devtools/` CLI improvements (new subcommands, better output formatting, new analysis tools)
  - Hook logic improvements (new permission patterns, better auto-allow rules)
  - Build/config improvements that generalize
  - **Guidance improvements** (coding standards, workflow tips, new guidelines)

- **Portable as scaffold**: Domain-specific implementations that represent a generalizable _pattern_. These get ported with domain details replaced by template placeholders.
  - **New agents/subagents** — A "version-reviewer" that uses Brier scores becomes a scaffold version-reviewer that uses generic outcome metrics. A "forecast reviewer" nested agent becomes a generic "reviewer" scaffold that critiques agent output.
  - **New tools or tool patterns** — A domain-specific reflection tool becomes a scaffold for structured self-assessment tools. A tool that runs a nested agent internally is a reusable pattern.
  - **New commands** — A "leak-investigator" for retrodiction becomes a scaffold for investigator-style commands
  - **Workflow improvements** — Offline mode for a specific API becomes a general "graceful degradation" pattern
  - **Reusable lib patterns** — A "response collector" that prints+logs SDK blocks is a general utility. A JSON pretty-printer for tool results belongs in lib.
  - **Feedback loop updates** — Version-scoped analysis, new analysis phases, better templates
  - **Agent SDK usage patterns** (hooks, session config, structured output, tool patterns)
  - **Agent core improvements** that generalize (error handling, log management, config patterns)
  - **Scoring/metrics improvements** (new columns, aggregation methods, visualization commands)

Examples of what gets missed when you classify by domain keywords instead of by function:
- A "forge image mounting" commit also adds `save_images()` — a general utility for writing clipboard image data to disk. The forge wiring is domain-specific; the utility function is portable.
- A "REPL upgrade" commit adds prompt_toolkit, clipboard paste, *and* container orchestration changes. The REPL UX is portable; the container setup is not.
- A "sandbox tools" commit adds `run_code` *and* a new error-handling pattern in the tool wrapper. The tool is domain-specific; the error-handling pattern is portable.
- A "score visualization" commit adds strip plots, trend charts, color selection, and watch mode. The scoring formula is domain-specific; the visualization pipeline is portable devtools infrastructure.

## 7. Present improvements

Present every extracted portable piece, one decision each. For each, give the upstream commit(s) it comes from, what the piece is, where it maps to in this project, and whether it can be applied here or has to go upstream. Group related pieces when they form a logical unit (e.g. strip plot + trend plot + watch mode = "devtools visualization scaffold"), then """
            ),
            models.AskUser(
                question="which of the extracted pieces to apply, "
                "one option per piece or group"
            ),
            models.TextPart(
                text=r""".

**Default: present.** When uncertain whether something is portable, present it with your reasoning and let the user decide. The user can always say "skip" — but you cannot un-skip something you never showed them.

## 8. Apply selected changes

For approved improvements:

1. Read the full changed files in both repos to understand context
2. Apply the changes, adapting as needed:
   - Adapt Python import paths between upstream and current project package names (`from lup.*` ↔ `from <project>.*`)
   - Framework vocabulary stays as `lup` in both directions — do not rename `lup_tool`, `LupMcpTool`, `lup-devtools`, `.lup/`, `lup-tools`, `lup-sandbox-*`, etc.
   - Keep the current project's coding conventions
3. **Wire new utilities into consumers.** When porting a library function, don't stop at the function itself — also wire it into the devtools commands, hooks, or agents that should use it. A utility without consumers is dead code.
4. **Regenerate if a declaration moved.** Anything ported into `harness/content/` is a source that compiles into the native trees, so it does not take effect until:

```bash
uv run lup-devtools harness generate all
```

5. Verify:

"""
            ),
            models.WatchOutput(command="uv run lup-devtools dev check"),
            models.TextPart(
                text=r"""

It runs ruff, pyright, and the test suite, and it reports as it goes rather than only at the end.

## 9. Mark as synced

**Skip this step if a focus area was provided** — the sync pointer must stay unchanged so unreviewed commits are still visible in the next full `"""
            ),
            models.SkillInvocation(plugin="lup", skill="update"),
            models.TextPart(
                text=r"""`.

After a full review is complete (whether or not changes were applied):

```bash
uv run lup-devtools sync mark-synced <project>
```

## 10. Optionally commit

If changes were applied, offer to commit them. Keep the dependency upgrade and
the ported scaffolding as separate commits — they are separate claims, and a
reader bisecting a regression needs to know which one carried it.

## Guidelines

- **The dependency first** — a piece ported by hand that the newer library already ships is work spent to produce a conflict.
- **Commit-level review preserves intent** — review commits, not flat diffs, so you understand why each change was made
- **File diffs provide context** — use full file diffs alongside commit diffs to understand how changes fit into the codebase
- **Generalize, don't dismiss** — when a downstream repo adds something domain-specific, ask "what pattern does this represent?" and port the pattern as scaffold. A forecasting-specific agent becomes a domain-neutral agent scaffold.
- **Ask, don't skip** — when uncertain about a change, present it to the user with your reasoning and let them decide
- **Adapt, don't copy** — downstream code uses domain-specific naming, paths, and models. Replace these with template-appropriate equivalents (`lup` package paths, generic metrics, placeholder descriptions).
- **Re-evaluate file placement** — after generalizing, re-check: can this module be used as-is without templating or source modification? If yes, it belongs to the library rather than to the application. A quick proxy: does it import from `agent/`? Downstream repos may have had domain-specific reasons for a different placement.
- **Mark synced even if nothing applied** — this advances the sync pointer so you don't re-review the same commits next time
"""
            ),
        ],
    ),
)
