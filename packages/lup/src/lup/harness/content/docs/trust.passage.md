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
lup-launch run setup gemini  # instead of: uv run lup-devtools setup gemini
```

Everything after the runtime is handed to the project's own `harness
<runtime>` unchanged. `lup-launch run <command...>` hands any other
`lup-devtools` command over the same way: the same host zone, the same
question, the same recorded approval, and the command run from the approved
export with the terminal handed through, so a prompt can hide what is typed.
A rejected review runs nothing. Launcher options go before the runtime or
`run`: `--root` names the checkout (default: the one enclosing the working
directory), `--port` the loopback port of its review inbox (default: any free
one), `--no-open` keeps the browser closed and answers at the terminal, and
`--status` prints what this machine approved and launches nothing. Without
the `web` extra the launcher still works, and asks at the terminal only.

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

Before anything opens, the terminal says once why it asks: whose host code,
whether this is its first run on the machine or what changed since the last
approval — counted by top directory, not listed file by file — how the free
zones move, and what runs once approved:

```text
adlib's host code changed since your last approval on this machine (4 files):
  docs/    1 added
  src/     1 changed, 1 added
  uv.lock  1 removed
lup-devtools setup gemini runs after you approve.
```

The question is then answered in the launcher's own review inbox — the surface
`dev questions serve` serves, run by the installed launcher's code over the
launcher's own relay, on loopback behind a capability only the printed address
carries, and opened in the browser — or at the terminal (`a` approve, `r`
reject, `d` show every diff), whichever answers first. It is never read from
the checkout's `.lup/questions.jsonl`: that file is writable from inside the
container, where no gate remains to stop a session answering its own
question. A rejection ends the launch with nothing from the checkout having
run. A launch interrupted while it waits leaves its question pending, and the
next launch over the same trees asks that question rather than a second one.

The inbox serves that one question and then stops, having told its tab what
happens next. A session's launch tells the tab it opens in the terminal. A
command `lup-launch run` hands over runs beside the launcher instead, told
through `LUP_REVIEW_TAB` where to hand the first page it opens, and the tab
goes on to that page — `lup-launch run setup dashboard` continues in the tab
that approved it, rather than opening a second one — after which the inbox
stops; a command that opens no page ends the inbox when it ends. A page is
handed only this way, never opened twice: a command opens its pages through
`lup.trust.tab.shown_to_operator`, which opens a new tab wherever no review
waits — a launch that asked nothing, `--no-open`, a later page. Where the
operator closed the review's tab, the launcher opens the page itself.

## Where the approval lives

Everything is kept under the launcher's state directory, which no container
mounts: `$XDG_STATE_HOME/lup/trust/<repository>-<digest>/` (`~/.local/state`
where the variable is unset), one directory per repository, shared by its
worktrees.

| path | holds | roughly costs |
| --- | --- | --- |
| `record.json` | every approved tree, the approved free zones, the tree each worktree last launched from, and the launches still running from an export | kilobytes |
| `objects.git` | a bare repository holding every snapshot as a git tree: `git --git-dir <it> ls-tree -r <tree>` lists one | the host zone once, then only what each approval changed |
| `questions.jsonl` | the relay launch questions are asked and answered through | a line per question |
| `exports/<tree>/` | an approved tree, materialized for a launch to run from | the host zone's size each, so tens of megabytes for a sizeable project |
| `environments/<worktree>-<digest>/` | the Python environment a worktree's launches run in | a full environment each, often hundreds of megabytes |
| `pycache/` | the bytecode compiled from the exports | a fraction of an export each |

The snapshots are written and read by the launcher in Python rather than
through `git`, so no configuration of anybody's runs while it hashes, and every
object read is re-hashed: a corrupt or substituted one is refused rather than
shown as approved.

Exports are pruned whenever one is materialized, under the record's lock: what
stays is the export each existing worktree last launched from, and every
export something still runs from. The launcher leases the export it hands off
to under its own process id, which the hand-off keeps, so a session's export
stays for as long as it runs; and on Linux any process whose environment names
an export in `LUP_APPROVED_TREE` keeps it too, which is how a host companion
started beside a launch keeps its export after the launch has ended. The
bytecode compiled from a pruned export goes with it. Environments are kept, one per worktree, since syncing a fresh
one is the slow part of a launch; remove the one of a worktree that is gone
to reclaim it.

No launch mounts this directory, and a contained launch refuses one whose
mounts would carry it into the container — a registration naming the home
directory, say — since a session that could write the record could approve
its own next launch.

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

## Host-only secrets

A key a host companion calls with and no session may hold — the API key a
listener uses, say — is declared host-only twice: `Integration(host_only=True)`
for the setup wizard that asks for it, and `HostCompanion(secrets=[...])` for
the companion that uses it. The wizard keeps such keys out of `.env.local`,
which sits in the checkout every session mounts, and in the operator's host
store instead: `$XDG_CONFIG_HOME/lup/secrets/<project>.env` (`~/.config` where
the variable is unset), named by the `[project]` table of the approved
manifest. The directory and the file are their owner's alone (0700 and 0600)
from the moment they exist, and every write replaces the file whole.

Only a companion naming a key receives it, in its own environment, read from
the store when it starts — never from the launch's environment, so a key the
operator's shell exports reaches no other companion. The session receives
none: the launch takes every host-only name out of the environment it hands
the session and the container engine, a contained session is handed
variables by name alone, and a contained launch refuses a mount that would
carry the store's directory into the container. A companion naming a key the
store lacks still starts, and the banner names the command that sets it.

Set them through the launcher — `lup-launch run setup gemini`, or `lup-launch
run setup secret GEMINI_API_KEY` for a key no integration declares — never
with `uv run lup-devtools setup`. The wizard is checkout code, and the moment
it asks for a secret is the moment code a session rewrote would want to run.
Through the launcher it runs from the export the operator just approved, and
the prompt hides what is typed. `setup status` says which store each
integration keeps its keys in, and names a host-only key found in `.env.local`
with the command that moves it. Inside a container, where the image sets
`LUP_CONTAINED`, every host-only write — an integration's prompt, `setup
secret`, the move, the dashboard — is refused before anything is typed, naming
the `lup-launch run setup ...` command to run on the host. That is a hint
rather than a boundary: it turns a secret saved into the container's own
configuration into an instruction, and nothing more.

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
  covers the launch, not the session. Such a session runs as the operator,
  so it can read the host store of secrets: the store keeps them from
  contained sessions only.
- **Anything run outside the launcher.** `uv run` in the checkout on the host
  uses the checkout's own `.venv`, and a plain `claude` or `codex` there reads
  the checkout's settings; neither passes through this check.
- **Files read relative to the working directory**, such as settings loaded
  from `.env.local`, are read from the live checkout, by a launch and by a
  command `lup-launch run` hands over alike: the code is the approved copy,
  the working directory is not. Keep anything that names a program out of
  them, and any secret a session must not read, which belongs in the host
  store.
