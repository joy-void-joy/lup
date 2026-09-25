<!-- Generated from lup.harness.content.docs.trust by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Trust on launch

Launching a session runs the checkout's own code on the host before any
container exists: `uv run` syncs an environment from the checkout's
`pyproject.toml` and `uv.lock`, which can name any package or build backend,
and the launch imports the project's package to generate the trees the session
opens against. A session can change that code by editing it, by committing a
change that lands on the host at the next checkout or pull, or by editing a
sibling worktree. Whatever it changed then runs on the host at the next
launch, outside the container. `lup-launch` closes that: nothing from the
checkout runs until the operator approved exactly what will run.

## Installing and launching

The launcher is installed as a tool from a pinned lup, so it runs from its own
environment and never from the checkout's:

```bash
uv tool install 'lup[web] @ git+https://github.com/joy-void-joy/lup@<commit>#subdirectory=packages/lup'
lup-launch claude            # instead of: uv run lup-devtools harness claude
lup-launch codex --network bridge
```

Everything after the runtime is handed to the project's own `harness
<runtime>` unchanged. Launcher options go before the runtime: `--root` names
the checkout (default: the one enclosing the working directory), `--port` the
loopback port of its review inbox (default: any free one), `--no-open` keeps
the browser closed, and `--status` prints what this machine approved and
launches nothing. Without the `web` extra the launcher still works, and asks
at the terminal only.

## What is fingerprinted

The *host zone* is every path the checkout's index tracks, minus the declared
free zones, plus `sync.json.local` when it exists. That file is gitignored and
lives in the checkout, where a session can rewrite it, and it decides the next
session's mounts, devices, network, memory and permission posture — so it is
reviewed like tracked code. Content is the working tree's bytes: a symbolic
link is its target, an executable file keeps its bit, a submodule is the
commit the index records, and a tracked path missing from disk is absent.

Untracked files do not count, and that is safe because of how the launch is
handed off (below): it runs from an export of exactly the approved zone, so an
untracked module, a planted `sitecustomize` or a stale `__pycache__` in the
checkout is simply not there to import. Counting them would make every scratch
file a session leaves outside a free zone a question at the next launch, which
is how an operator learns to approve without reading.

The checkout is read through `git` with every lever that could make it run a
program disarmed — no fsmonitor, no hooks, no pager, no optional locks, none of
the caller's `GIT_*` variables — and content is hashed by the launcher itself,
so no clean filter or attribute of the checkout is ever consulted.

## Free zones

Paths a session may change without a question are declared in the checkout's
`pyproject.toml`, which the launcher can read as data before any code runs:

```toml
[tool.lup.trust]
free = ["studio/", "tmp/"]
```

What a launch uses is not this table but the list the operator last approved,
kept in the launcher's record. A change to the declaration is a change to
`pyproject.toml`, so it is reviewed like any other, and the question says how
the zones would change. Once approved, the paths newly freed stop being
reviewed from that launch on. Nothing in a free zone reaches the export, so a
free zone can never hold something the host launch runs: a project that frees
its own package finds its launch failing to import it, not running it
unreviewed.

## The question

The same tree launches at once, with one line saying so. Anything else — a
first launch, an edit, a commit checked out, a change arriving in a sibling
worktree, a rewritten machine registry — becomes a question, and nothing runs
until it is answered. Its evidence is the diff between the tree this worktree
was last launched from (else the repository's most recent approval) and the
current zone. A first launch shows the complete zone, every file as a
creation. Where the approved snapshot's objects are missing or corrupt, the
question shows the complete zone and says so. Binary content is shown as its
size and object id rather than decoded lossily, and an executable bit that
appears or changes is listed as its own entry.

The question is answered in the launcher's own review inbox — the surface `dev
questions serve` serves, run by the installed launcher's code over the
launcher's own relay, on loopback behind a capability only the printed address
carries — or at the terminal (`a` approve, `r` reject, `d` show every diff),
whichever answers first. It is never read from the checkout's
`.lup/questions.jsonl`: that file is writable from inside the container, where
no gate remains to stop a session answering its own question. A rejection ends
the launch with nothing from the checkout having run. A launch interrupted
while it waits leaves its question pending, and the next launch over the same
trees asks that question rather than a second one.

## Where the approval lives

Everything is kept under the launcher's state directory, which no container
mounts: `$XDG_STATE_HOME/lup/trust/<repository>-<digest>/` (`~/.local/state`
where the variable is unset), one directory per repository, shared by its
worktrees.

| path | holds |
| --- | --- |
| `record.json` | every approved tree, the approved free zones, and the tree each worktree last launched from |
| `objects.git` | a bare repository holding every snapshot as a git tree: `git --git-dir <it> ls-tree -r <tree>` lists one |
| `questions.jsonl` | the relay launch questions are asked and answered through |
| `exports/<tree>/` | each approved tree, materialized for a launch to run from |
| `environments/`, `pycache/` | the Python environments and bytecode the launches run with |

The snapshots are written and read by the launcher in Python rather than
through `git`, so no configuration of anybody's runs while it hashes, and every
object read is re-hashed: a corrupt or substituted one is refused rather than
shown as approved. Exports are kept; remove `exports/` between launches to
reclaim the space.

## The hand-off

Once approved, the launcher materializes the tree into `exports/<tree>/` and
replaces itself with

```bash
uv run --directory <checkout> --project <export> --frozen lup-devtools harness <runtime> ...
```

The export is the project whose code runs, and the checkout stays the
working directory the launch writes its trees into and mounts. `--frozen`
installs exactly the approved lockfile. The environment is one the launcher
keeps per worktree, because the checkout's own `.venv` is writable from inside
the container and a `.pth` file planted there runs in every interpreter
started from it; the bytecode cache is the launcher's too. `LUP_APPROVED_TREE`
names the export, and the registry readers take `sync.json` and
`sync.json.local` from there rather than from the live, session-writable
files. A symbolic link whose target lies outside the approved tree is not
created in the export, and the launcher names each one it withheld.

After a question is answered, the launcher first runs `lup-devtools harness
generate all` from the same export and records the tree that leaves as
approved too, when every file it changed is one the generator's ownership
proof vouches for with the digest now on disk. Without that step a project
whose generated trees are read-only in its sessions would be asked twice for
every change to its sources — once for the change, and again for the files
regenerating it rewrote. A change the proof does not vouch for, such as a
session writing while generation ran, is left for the next launch to ask about.

## What this does not cover

- **Repository writers that run a toolchain** in the live checkout run on the
  host with whatever sits in its ignored directories. lup's own web bundles
  are built by `bun` over `packages/lup/web/node_modules`, which a session can
  write; a project whose writers only render files is not exposed.
- **Git configuration reached around the read-only mounts.** A session cannot
  write the shared `config` or `hooks/` of a checkout it is leased, but a
  `.git` directory renamed away, a `commondir` planted beside it, or a linked
  worktree's `.git` file repointed hands the operator's next host-side `git`
  a configuration the session wrote. The launcher's own reads disarm every
  program-naming key; the operator's are protected only as far as the lease
  pins those paths.
- **Host postures.** `--sandbox inner` and `--sandbox none` open the session on
  the host, where its tool servers run checkout code by design; the check
  covers the launch, not the session. Such a session also inherits
  `LUP_APPROVED_TREE`, so a registry command it runs reads and writes the
  export rather than the checkout.
- **Anything run outside the launcher.** `uv run` in the checkout on the host
  uses the checkout's own `.venv`, and a plain `claude` or `codex` there reads
  the checkout's settings; neither passes through this check.
- **Files the application reads relative to its working directory**, such as
  settings loaded from `.env.local`, are read from the live checkout; keep
  anything that names a program out of them.
- **Commands other than the launch.** A `dev` command run through an export
  meets code that assumes its package lies under the checkout's root; the
  launcher only ever hands off `harness`.
