# Contributing

This page is for a contributor arriving cold. It covers getting a working
checkout, deciding where a change belongs, and what has to be green before it
lands. The component guides — [library.md](library.md),
[template.md](template.md), [harness.md](harness.md) — cover *how* to make a
change once you know where it goes.

## Getting set up

```bash
uv sync                                    # both workspace packages
{{ setup }}uv run lup-devtools dev check --changed     # ruff + pyright on what you changed
uv run lup-devtools dev test <paths>       # while iterating: only these files
uv run lup-devtools dev check              # the local pre-flight bar
```

Three commands, because they answer different questions. `dev check` puts both
test suites, pyright and ruff on the machine at once and costs whichever of
them finishes last — a couple of minutes — and it is what has to be green
before a commit. The gate reports what each of its checks cost, so a run that
felt slow can be read rather than guessed at.

The other two are the loop while a change is still moving. `dev check
--changed` runs ruff and pyright over the Python files changed since the
integration branch, in seconds — those are the two checks a scope narrows
*exactly*, because each answers about the files it is handed and Pyright
resolves their imports itself. It runs **no tests**, and says so every time.
`dev test` runs the test files you name, in the suite that installs each.

Which tests reach a change is deliberately left to you. It is a question about
the import graph, and modules reached through `importlib` are invisible to any
static reading of it — so a suite narrowed automatically could report green
while skipping the one test the change breaks. A gate that is trusted and
wrong costs more than one that is slow.

Run one at a time. Two gates at once are slower than the same two in
sequence, because each already spreads itself across every core the machine
has — and a suite reading a repository whose branches another command is
moving fails on that rather than on the code.

`uv` is the package manager: use `uv add <package>`, never edit
`pyproject.toml` by hand. Secrets go in `.env.local`, which is gitignored;
`.env` holds template defaults. `uv run lup-devtools --help` is the full
command tree.

To launch the repository as a native agent plugin:

```bash
uv run lup-devtools harness claude          # generate, then launch
uv run lup-devtools harness codex
```

## Where does my change go?

| If you are changing… | It belongs in | And you should read |
| --- | --- | --- |
| Anything another project built on lup would want | `packages/lup/` | [library.md](library.md) |
| Anything only this application needs | {{ project_directory }} | [template.md](template.md) |
| A skill, agent, guidance, permission policy, or a page under `docs/` | `packages/lup/src/lup/harness/content/` where the library owns the subject, {{ harness_content_directory }} where only this application does | [harness.md](harness.md) |
| Repeated shell incantations | a new `lup-devtools` command | [template.md](template.md) |
| A one-off computation | a new `lup-devtools` command | below |

The placement question between the first two rows is the one that matters, and
it has a single test: *would another project built on lup want this?* If yes,
it goes in the library even if only this application uses it today. The
library never imports the application, so a utility placed wrongly in
{{ project_directory }} is unreachable from the library and will have to move
later.

`tmp/` is scratch: gitignored, so nothing written there reaches a diff, a
reviewer, or a human — which is why it does not execute. One-off work takes
the first of these that fits:

1. To read code rather than run it: `py info`, `py source`, `py search`, `py text`,
   `py imports`, and the codeintel tools. Resolve names with `py search` or
   codeintel; find literal text in explicitly scoped Python paths with `py text`.
2. To compute something once: a script under `tmp/`, run directly. It imports
   this checkout the way any other module does, and the session it runs in is
   itself contained, so what used to be the objection — an unreviewable thing
   executing outside any boundary — is now only the first half. A one-off
   nobody will read again costs a reviewer nothing.
3. For anything you will want twice: a new `lup-devtools` command, which
   lands in the diff and can be run again by name rather than rewritten. The
   policy counts how often each script runs and says so when one has passed
   what a one-off is for — advice riding along with a verdict that already
   allowed the command, not a gate. It arrives at the fifth run and then
   every tenth, because a session that was mid-thought at the first one has
   to hear it again, and one that hears it every run stops reading it.
4. As a last resort, an inline heredoc behind an escalation marker
   ([permissions.md](permissions.md)).

A rung that evaluated an expression inside its own container used to sit
between the first two, and was removed with that container. The agent session
is contained now, so a second boundary within it bought no isolation — and the
one it had actively got in the way, since the tool could not import the very
checkout it was asked about.

The argument is reviewability, not power: an agent may already edit
`devtools/` and run it.

A result too large to return does not come back at all: the runtime persists
it to a file and returns a short preview naming that file. Hand the file to a
reader that takes a file whole. `cat`-ing it is another result too large to
return, persisted to another file, and `cat`-ing that one repeats it — a
regress whose every step looks like the command having worked.

Never create a tracking file. A `TODO.md`, backlog, or roadmap parks a
decision where no workflow surfaces it again. Deferred work lives as a
`# lup: defer: <text>` note at the site it concerns — where `dev comments`
lists it in its own parked section and `dev check` keeps it visible until
somebody wakes it. That bare spelling is the
default, and a bracketed `defer[<gate>]: <text>` states a real,
externally-checkable gate — never a restatement that this code might change
again.

Some gates this checkout can resolve, and those it does. `dev check` asks them
every run, reports them among the other deferrals while the answer is no, and
fails the run the answer turns yes. `defer[gone:<path>]` wakes once that path
stops existing.

`defer[branch:<name>]` wakes for whoever is standing on that branch, and again
if the branch lands with nobody having acted. The first is the point. A note
about a branch is written by somebody standing somewhere else, and the person
it concerns is on the branch it names, in a checkout that carries no copy of
it — so the check reads the integration branch as well as the working tree,
for the notes naming the branch in hand. Write one where you are, aimed at the
branch that has to act, and it reaches them without waiting for a merge.

Landing wakes it even where the branch was deleted in the same sweep, because
`git delete` judges containment off the ref it is about to remove and records
that verdict beside the branch. A checkout that never deleted it holds no such
record and stays quiet — which is what keeps a clone that merely never fetched
the branch, every CI job among them, from waking every gate in the repository.

A gate the checkout cannot see — "until the v2 API ships" — stays prose and
stays advisory, which is the whole of what a stated gate ever did before.
Prefer a resolvable spelling where one fits, because a deferral is dormant
exactly as long as nobody has reason to read it, and the moment it stops being
dormant is the moment nothing else announces.

A note is right when the subject is the code: a bug worth remarking on, an
idea for a feature, anything the site it concerns can hold. Work whose
subject is the tooling misbehaving — friction, a command that half-completes,
a classifier reporting a failed probe as fact — has no site to sit at, and
becomes a GitHub issue instead. When whether to defer at all is the open
question, it becomes a question to the user rather than any note.

## Git workflow

Development happens in **worktrees**, not branches switched in place, so
several changes can be in flight at once:

```bash
uv run lup-devtools git worktree create feat-name
```

The worktree is created as a sibling under `tree/`. Never nest one inside
another checkout. `git checkout -b` would make a branch and switch the
current directory in place; `git worktree add` gives the branch a directory
of its own, which is what keeps several live at once. `worktrees/` and
`refs/` are gitignored, the latter holding symlinks to the projects this
repository tracks.

Those symlinks resolve inside a contained session only for a project whose
registration in `sync.json.local` carries a `"mount"` of `"rw"` or `"ro"` —
`dev sync setup <name> <path> --mount rw` writes one, and `dev sync status`
shows which projects have it. A mounted project is leased whole: its
checkout at that mode, its shared git directory with it, and its own sibling
worktrees read-only, which is what lets a session commit in it. Without the
key the project is tracked for review and nothing more, and the symlink
dangles inside the container the way an unmounted path does. The key is why
`sync.json.local` is a protected edit root: writing one widens the boundary.
For a folder one session needs without a standing registration, the launchers
take `--mount <dir>` and `--mount-ro <dir>` (repeatable): the same lease, the
same widening in every posture, lasting exactly one launch.

A host device — a GPU — is granted on the same terms and from the same file.
`sync grant nvidia.com/gpu=all` writes the name into `sync.json.local` after
starting a throwaway container with it, so a grant nobody's engine can honour
is refused where it is made; `sync revoke` takes it back, `sync status` shows
each grant beside whether a spec still names it, and the launchers take
`--device <name>` (repeatable) for one launch. The name is the Container
Device Interface's, `vendor/class=device`; the nodes under `/dev` and the
driver libraries beside them are the registered spec's to inject, so nothing
here enumerates either, and nothing committed names one: which GPU a machine
holds is that machine's fact. Every launch reads `/etc/cdi` and
`/var/run/cdi` on the host, hands the engine what a spec there names, and
withholds the rest with one line, because `/var/run/cdi` empties at boot and
a driver update regenerates a spec. A spec is written by the vendor's
toolkit — `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` for
NVIDIA — and Docker reads the registry from 28.3 (an older daemon needs
`"features": {"cdi": true}`; podman always has). What was granted is written
to `.lup/boundary.json` beside the mount table, so a run's provenance says
which devices its container held, and `harness requirements` re-exercises
every grant it finds.

A registration naming only a URL is mounted on the same terms, because it is
materialized into the same shape: a full bare clone under
`~/.cache/lup/sync/<name>.git` with a worktree attached at `tree/<branch>`,
and the worktree is what the lease binds. Commit in it, cut branches in it,
push from it — the remotes of every mounted checkout are rewritten onto the
transport this session can reach, not just the one it was launched from. A
review never moves a branch there: `sync` reads the upstream's commits from
its remote-tracking ref, so refreshing is a fetch and nothing in the clone is
reset over.

The base the branch is cut from is recorded against it, because topology
cannot recover a creation point once the parent has merged on. It is read
from the checkout you run in, so a detached HEAD has nothing to read: rather
than record nothing and let a later reader guess, creation refuses and asks
for `--base <branch>`, or `--no-record` to say deliberately that this branch
has no base worth keeping.

The command prints the path and does not move whoever ran it. **Launch a
session rooted at that path**; do not relocate a running one. The difference
is not style. A runtime that can move a running session arms its own
worktree isolation when it does — a check on command *shape*, separate from
this project's policy and owned by nobody here, which refuses a command
carrying any of fifteen shell words as an argv element in any position:

    eval  source  .  fc  coproc  trap  enable  mapfile  readarray
    hash  bind  complete  compgen  alias  let

Only `.` is gated to first position; the other fourteen match anywhere, and
none of them is gated on the command being a git command. So an isolated
session loses `grep -c hash` and `rg complete src/` — read-only commands with
no git in them — for as long as it lasts, and no approval marker reaches the
refusal.
Relocation is bounded as well as expensive: `git worktree create` cuts under
a sibling `tree/`, outside the `.claude/worktrees/` a relocating tool
switches within, so such a path is taken only as a session's first entry from
the directory it launched in. A session already sitting in one worktree is
refused a second switch by the tool itself, whatever this project decides, so
stacking a branch means a launch or absolute paths either way.
A session launched already rooted in the worktree is never isolated and
keeps all of them, which is why the workflow asks for a launch. Staying put
and editing through absolute paths works too, but only into a worktree that
is writable, and which those are is the lease's to say (`lup.sandbox.rail`):
an operator's contained session holds every checkout of its repository
writable, so that route reaches any sibling; a resolver worker's lease holds
every sibling that existed when the worker started read-only, so there the
route reaches a filesystem refusing every write, and only a worktree the
worker cut itself takes edits. The isolation is measured against Claude Code
2.1.237; `docs/native-capabilities.md` carries the evidence.

Commit early, commit often, and keep commits atomic — if the message needs an
"and", it is two commits. The format is `type(scope): description`:

