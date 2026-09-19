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

