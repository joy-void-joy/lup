# Install Lup into Target Repo

Install the lup plugin, hooks, and useful scaffolding into an existing repository. Unlike `{{ init_skill }}` (which customizes the template for a new domain), this command ports lup capabilities into a repo that already has its own structure and conventions.

## Your Task

**Arguments provided**: {{ arguments }}

### Parse Arguments

- **target-repo**: Path to the target repository (default: `..`). Resolve relative paths from the current working directory.
- **--interactive**: If present, put each porting decision to the user as a choice. If absent, be conservative — modify as few files as possible.

### The source repository is read-only

You are running *inside* the source. Every write this command makes belongs to
the target, and nothing it does may change the checkout it runs from — not a
file, not a git ref, and not a piece of local state.

The failure is quiet rather than loud, which is why it is stated here: a
`lup-devtools` command run without a working directory acts on the current one,
so it lands in the source and looks like it worked. Two habits prevent it:

- Give every command the target explicitly — `git -C <target> …`, and
  `uv run --directory <target> lup-devtools …` for anything that reads or
  writes its state. `--directory` is the flag that changes the working
  directory; `--project` only discovers a manifest and leaves you in the source.
- Write files by absolute path under the target, never by a path relative to
  where you are standing.

Before reporting success, run `git -C <source> status --short` and confirm it
is clean. If the source changed, say so in the report rather than reverting
silently — something wrote where it should not have, and which command did it
is the useful part.

That rule is about *accidental* writes — a command that acted on the wrong
working directory. It does not forbid a deliberate contribution back. When the
target's fork carries code that passes the library placement test — would
another project built on lup want this? — folding it into the source is the
correct outcome rather than a violation. Raise it as a decision; once the user
approves, the source is writable for exactly that change, and the report names
the commits you made to it alongside the ones you made to the target.

### The source branch is part of what you install

Every phase below reads the source checkout as it stands, so the branch you are
standing on *is* the release you are about to install — a feature branch ports
unmerged work, and nothing downstream announces that. Resolve both before
Phase 1:


<!-- passage: analyze-the-source -->
Every later phase reads this checkout, and step 9 baselines the target's sync
checkpoint at its HEAD. Nothing here may move it, so if the answer was the
stable branch it is standing on the wrong one: stop and say so, and let the
work be re-run from a checkout of that branch rather than installing one branch
while recording another.

If `{{ arguments }}` is empty, use defaults: target=`..`, non-interactive.

## Phase 1: Analyze Source Repo (Lup Template)

Inventory what the lup plugin offers. Read these key files in the **current** repo (`.`):

### Plugin Structure

One declaration set renders into every harness tree the repo commits, so each
capability below exists once per tree:

| Capability | Where it lands |
| --- | --- |
| Plugin identity | {{ manifest_path }} |
| Hook definitions, dispatcher, and hermetic policy runtime | {{ hooks_path }} |
| Skills | {{ skills_path }} |
| Agents | {{ agents_path }} |
| Guidance template | {{ guidance_template_path }} |

### Reusable Library Code

- `packages/lup/src/lup/` — utilities (trace, hooks, metrics, mcp, retry, notes, history, paths)
- `lup.workspace.paths.agent_version()` — version tracking pattern (reads `[tool.lup] agent_version` from pyproject.toml)

### How the Target Obtains Lup


<!-- passage: seams -->
### Settle the seams the target inherits

Everything installed above ships at a default, and a handful of those defaults are places lup holds an opinion the target is meant to overrule. **A default nobody was shown is not a decision** — and it matters more here than in a fresh scaffold, because the target already has conventions of its own, which is exactly what § Guidelines means by respecting them.

Run `uv run --directory <target> lup-devtools dev seams`. It prints each seam, what it holds, and where it is written. Put each to the user:

- **Who owns which files.** A human-owned file surfaces every change as an approval and the agent proposes rather than writes it. Ask specifically about `README.md`: a target whose README is maintained by hand wants it owned, and one that wants the agent writing it says so with `dev seams --disown README.md`.
- **Which trees an edit needs approval into.** Ask what this target actually guards — a migration set, a deployment manifest, a data directory, a generated client — rather than carrying over paths that describe lup's own tree.
- **What each tree is for.** Its test roots, its build products, its scratch. Every gate reads this one answer, so a target whose layout differs and never says so is judged by lup's layout instead of its own.
- **Which scan rules it holds itself to.** The one most likely to be wrong by default: the rules encode conventions this project settled, and a target that settled one differently is not defective there. Offer keeping them, dropping named ones (`dev seams --retire <rule-id>`), or dropping the family outright (`dev seams --retire-all`), and mean all three. `docs/rules.md` in the target lists what each id refuses, so read it with them rather than asking about thirty ids blind.

Then regenerate: `uv run --directory <target> lup-devtools harness generate all`.

## Phase 7: Verify & Report

After installation:

1. **List all files created/modified** in the target repo, marking which ones generation now owns
2. **Show a summary** of what was installed and why
3. **Note what was skipped** and why (especially in non-interactive mode)
4. **Suggest next steps**:
   - Review the installed hooks and adjust patterns
   - Try `{{ meta_skill }}` to review the generated harness trees
   - Run `{{ commit_skill }}` to test the commit workflow
   - Consider `{{ update_skill }}` later for ongoing sync

## Guidelines

- **Respect the target**: Don't impose lup conventions where the target has its own. Adapt to them.
- **Minimal footprint**: In non-interactive mode, prefer doing less. The user can always run with `--interactive` later to add more.
- **No new dependencies**: Don't install anything that requires `pip install` or `npm install` unless explicitly approved in interactive mode.
- **Adapt, don't copy**: Every file needs to be reviewed and adapted for the target's ecosystem.
- **Preserve existing work**: Never overwrite files a harness tree already holds. Merge or extend.
- **Explain decisions**: For each installed item, briefly explain what it does and why it helps.
