# A worktree's links, verified before the host runs git

**One sentence:** before a launch starts and before any host-side git runs, the host checks that each worktree's link files name the repository's own git directory and nothing else, and refuses and tells the operator where one points away, so a room can't make the host's git read a git directory the room wrote (#54).

This designs the check the operator decided on (2026-10-16), to be built next. The full fix is spawn's: worktrees created and removed through the host, each worktree's link files mounted read-only (`DESIGN.md`, *Open questions*, isolation; *Modules*, `spawn`). Until that lands, and as a check that stays after it, the host verifies the links. The note states spawn's part only as far as the check needs it. It rests on #54 and its comment, `docs/field-notes.md` (*Host-side git in a repository the room writes*), and scratch checks for this note on the room's git 2.55.0, the `commondir` redirect repeated by the session that reviewed it (*Checks owed*: the host's 2.56.0 still owed). The operator took every lean below on 2026-10-16, and had the pin on each host-side git that names the git directory land first, ahead of the check.

## Why the host is exposed today

A room mounts the repository's git directory read-write, except `config` and `hooks/` (`docs/launch.md`, *The mounts*). Two kinds of file decide which git directory, and so which `config`, git uses for a linked worktree, and both are room-writable:
- a worktree's own `.git` file, holding `gitdir: <path>`;
- `<git dir>/worktrees/<name>/commondir` (with `gitdir` beside it), holding the path back to the common directory.

A room points either at a git directory it wrote, whose `config` sets `core.sshCommand`, `core.fsmonitor`, `core.hooksPath`, a pager or a filter driver. The next host git that finds the repository from that worktree runs the room's command with the operator's hands: the operator's own `git status`, an editor's git integration, or lup's own host git (the inventory below). `safe.directory` is no backstop: under `--userns=keep-id` the room's files are the operator's (`docs/field-notes.md`).

**Beyond #54's two files (found for this note, benign probe on git 2.55.0):** naming the common git directory explicitly is not by itself enough. A room-planted file `<git dir>/commondir` — a file a bare common directory never has — turns that directory into a linked-worktree pointer, and `git --git-dir=<git dir>`, `git -C <git dir>` and `GIT_DIR=<git dir>` all follow it to the git directory `commondir` names and read its `config`. Only `GIT_DIR` **and** `GIT_COMMON_DIR` set together resist it. So `remote/protocol.py`'s host git, which names `--git-dir=<common>` (and sets `core.fsmonitor`/`core.hooksPath` off but not `core.sshCommand`), is still exposed through `<git dir>/commondir`; and `git.py`'s runner, which turns off `core.fsmonitor` and hooks but not `core.sshCommand`, a pager or filters, reads a redirected directory's `config` whenever it discovers the directory from a worktree.

## The inventory: where lup runs git on the host

Every host-side git goes through `Git` (`git.py`), which runs `git -c core.fsmonitor=false -c core.hooksPath=/dev/null …` with `cwd` set and `arguments` (which git directory) prepended, or through `Remotes.git` (`remote/protocol.py`). A place that **names** the git directory explicitly is safe only against a worktree `.git` file; a place that lets git **discover** it from a worktree is exposed today, as is a named common directory holding a planted `commondir`.

| Place | Names or discovers | Exposed today |
|---|---|---|
| `launch/trust.py` (`repository`, `zone`, `tool`, `named`, `fingerprint`, `change`, `export`) | discovers from the launched worktree (`Git(cwd=root)`, `rev-parse --git-common-dir`) | yes — a redirected worktree `.git` makes trust read and approve the wrong repository |
| `cli.py` `launched` (line 709) | discovers from the worktree (`rev-parse --git-common-dir`) | yes — the result feeds the registration's `repository`, used by every host git below |
| `cli.py` (`toplevel` 235, verdict 927, 1106) | discovers from cwd/worktree | yes |
| `launch/room.py` `repository`, `related`, `maintaining_room` | discovers from the worktree (`rev-parse --git-common-dir`, `worktree list`, `config --get user.*`) | yes |
| `launch/session.py` `approved_declaration` | discovers from the worktree, then `export` | yes |
| `forge/github.py` `named`/`ran` (`gh repo view`, and every GitHub tool) | runs `gh` (which runs git) in the common directory resolved at launch | the worktree `.git` vector is closed (it uses the common directory, "never from a worktree", #54); still follows a planted `<git dir>/commondir`, and inherits a tainted common directory if the launch discovery above was redirected |
| `remote/protocol.py` `Remotes.git` (push, fetch, `ls-remote`, `get-url`) | names `--git-dir=<common>` | the worktree `.git` vector is closed; still follows a planted `<git dir>/commondir`; still reads a redirected `config`'s `core.sshCommand` |
| `remote/config.py` `room_config` | `config --file <common>/config` (named file) | reads that file alone; the common directory comes from the launch discovery above |
| `policy/worktrees.py` `place` | discovers from the file's nearest directory | yes — the judge reads which repository/worktree a path is in |
| `policy/store.py` `Store.repository` (`head`, `moved`, `merges`, `committed`, …) | discovers from the worktree | yes |
| `policy/store.py` `Store.snapshots`, `ensure` | names `--git-dir=<store>` under lup's state (not room-writable), `--work-tree=<worktree>` | no — the store is lup's own |
| `policy/checkpoint.py`, `policy/holds.py` | discover from the worktree (`rev-parse --git-common-dir`) | yes |
| `remote/helper.py` | runs in the room on git's `GIT_DIR`; not host-side | n/a |

So almost every host git discovers its directory from a worktree the room writes; only the snapshot store names a directory the room can't reach. This is the evidence for where the check must run: at launch, where the discovered common directory becomes the registration all later host git trusts, and before each host git that reads a worktree.

## What "a worktree's links are right" means

**lup's layout** — a bare git directory `<git dir>` with worktrees under `<git dir>/tree/<name>` (and `<git dir>` itself the one non-linked worktree):
- `<git dir>` is a real common directory: it has no `commondir` and no `gitdir` beside its `config` (a bare common directory never does; either turns it into a linked-worktree pointer), so it resolves to itself;
- for each linked worktree `<git dir>/tree/<name>`: its `.git` is a *file* reading exactly `gitdir: <git dir>/worktrees/<name>` (an absolute path inside `<git dir>/worktrees/`); `<git dir>/worktrees/<name>/commondir` resolves to `<git dir>` (git writes `../..`); and `<git dir>/worktrees/<name>/gitdir` reads `<git dir>/tree/<name>/.git` (git's back-pointer);
- no `.git` file, and no `commondir`/`gitdir`, resolves to a path outside `<git dir>`.

**A plain clone** — whose `.git` is a *directory*:
- `<root>/.git` is a directory, the clone's real common directory (its `config` and `hooks/` are the read-only mounts), with no `commondir`/`gitdir` redirect file in it;
- the field notes measured that a clone's `.git` can be moved aside under the tree's mount (`mv .git .git-real` succeeded, a room's own `.git` put in its place) unless `.git` is mounted on its own; the check is the backstop for that: `<root>/.git` must be a directory, not a file, and be git's own common directory for the clone, not one the room substituted;
- each linked worktree's `.git` file points into `<root>/.git/worktrees/<name>`, as for lup's layout.

A link that is absent where git would keep one, or present where it shouldn't be, or resolves outside the repository's own git directory, is wrong.

## Where the check runs

- **At launch,** in trust and the launcher, before the common directory is discovered for the registration: the launcher verifies the launched worktree's links and the common directory, then registers the **verified** common directory, so every later host git (the judge, `gh`, the remote helper) is handed a directory already checked. **(decided)**
- **Before each host-side git that reads a worktree,** since a room runs between launches and can plant a link afterward: the judge's `place`/checkpoint/store, the remote helper's host handler (push, fetch, `ls-remote`), and `gh` naming and the GitHub tools verify the worktree (or the common directory) they are about to read before they run git there. lup's host git is short-lived, one process per call, so "before each" and "at launch" are the same gate applied per operation.
- **And pin the directory when running git (decided, landing first):** run every host git with `GIT_COMMON_DIR` (with `GIT_DIR`) set to the verified common directory, and extend `git.py`'s safe list to turn off `core.sshCommand`, `core.pager`, `core.fsmonitor` (already) and filter/attribute drivers it doesn't need. Pinning alone doesn't choose *which* directory to pin — a redirected worktree `.git` still misdirects the discovery of the common directory — so pinning is the belt and the link check the suspenders; neither replaces the other.
  - **Alternatives:** pin `GIT_COMMON_DIR` only, no link check — rejected: it can't decide the common directory from a poisoned worktree, and doesn't tell the operator their own shell is exposed. Check only at launch — rejected: a room plants a link after launch, before the next host git.

## When a link is wrong

- **The host git refuses to run,** and says precisely which file is wrong, what it reads, and what it should read (`<git dir>/worktrees/<name>`, or `../..`), in lup's host-error voice. At launch, the launch is refused with nothing started, as trust's refusals are (`docs/launch.md`). **(decided)**
- **The operator is told through the inbox** (`docs/host-tools.md`, *The operator's face*), with a desktop notice: a room wrote a worktree link that would have aimed the operator's git at a directory it chose. One item per repository, said once until repaired.
  - **Alternatives:** warn and proceed — rejected, that is the exposure. Repair silently — rejected, repair is the operator's to see (below). Refuse only at the gate — rejected, the harm is at the operator's next git, not at landing.

## Repairing it, without running the room's configuration

The repair must not itself run the room's `config` — so it is **not** `git` run from inside the suspect tree, which would read the planted `core.sshCommand` before it could fix anything.
- lup (or the operator) rewrites the link files with plain file writes, and removes a stray `<git dir>/commondir`/`gitdir` with a plain unlink: a worktree's `.git` back to `gitdir: <git dir>/worktrees/<name>`, `<git dir>/worktrees/<name>/commondir` back to `../..`. These are known strings; no git reads a planted config to produce them. **(decided)**
- `git worktree repair` is allowed only with `GIT_DIR` and `GIT_COMMON_DIR` pinned to the verified common directory, so it reads lup's directory and not a redirected one; absent the pin it is refused.
- **Spawn removes the need:** once worktrees are created and removed through the host with their link files mounted read-only, a room can't write them, so there is nothing to repair; the check then only confirms the mounts held.

## Between checks: the operator's own shell and editor

Nothing lup does protects a `git` the operator, or their editor's git integration, runs in a worktree between a check and the next: a running room can plant a link after lup checked, and the operator's shell reads it before lup checks again. lup tells the operator this in guidance (`docs/launch.md`, *Guidance*): lup verifies the links at launch and before its own host git, but a worktree a room is or was running in is the room's until re-checked, so treat the operator's own `git` there as the room's command until spawn mounts the link files read-only. **(decided)** A host-side wrapper over the operator's own git is out of scope; the wall is for lup's host git, and the standing fix is the read-only mount.

## Where it lives, and its public API

The wall and the limits on the operator's credentials are the environment core's (`docs/modules.md`, *The cores*; *Settled so far*, *GitHub, and git through the host*), so the check is too: a small verifier in `policy/` beside `policy/worktrees.py` (which already asks git where a path is), called by `launch/trust.py` and `cli.py` `launched` at launch, and by the judge, the remote handler and the forge before they run git. The full fix is spawn's, which owns isolation and the worktree's lifecycle (`docs/modules.md`, *Spawn and isolation*).

**Public API:** none **(decided)** — an internal check and a pinned `Git`. A module gains nothing to call. Alternative: a `Links` seam a project's module could extend, deferred until a second judging module needs it (`DESIGN.md`, *Modules*, nothing built in).

## Tests

Stubbed, no real clock, no agent and no network (`AGENTS.md`, *Tests*):
- scratch repositories laid out like lup's (a bare `<git dir>` with a worktree under `tree/`) and a plain clone, on the host's git: a correct layout passes;
- each wrong link refused and said, and the operator's inbox item written: a worktree `.git` redirected to another git directory; `<git dir>/worktrees/<name>/commondir` redirected; a stray `<git dir>/commondir` (and `gitdir`) planted in the bare common directory; a clone's `.git` replaced by a directory of the room's; a link resolving outside the repository;
- the launch refused when the launched worktree's links are wrong, with nothing registered;
- repair restores the correct strings and removes a stray link without running git from the suspect tree, and the repaired layout then passes;
- a host git run with `GIT_COMMON_DIR` pinned reads lup's common directory even with a planted `<git dir>/commondir` present (the regression this closes).

## Checks owed

- **git 2.56.0 on the host:** the `<git dir>/commondir` redirect of `--git-dir`/`-C`/`GIT_DIR`, and that `GIT_DIR`+`GIT_COMMON_DIR` resists it, were checked here on git 2.55.0 only; the host's git review (`docs/field-notes.md`) ran on 2.56.0, so confirm the redirect and the defence there.
- that pinning `GIT_COMMON_DIR` on `Remotes.git` and `gh`'s git leaves push, fetch, `ls-remote` and `gh repo view` working against lup's own remote behind its SSH alias;
- that extending `git.py`'s safe list (`core.sshCommand`, pager, filters off) changes nothing lup's host git relies on.

## Decisions

All six answered by the operator on 2026-10-16: each lean taken as stated.

1. **What "right" requires, and the stray `commondir`.** Lean: check #54's two files **and** refuse a `commondir`/`gitdir` in a bare common directory (and a clone's `.git` being a file, not a directory), since a planted `<git dir>/commondir` redirects even an explicitly-named git directory (found for this note, git 2.55.0). Alternative: only the worktree `.git` and `worktrees/<name>/commondir` the issue names, leaving the common-directory redirect to the `GIT_COMMON_DIR` pin alone.
2. **Where it runs.** Lean: at launch (feeding the registration a verified common directory) and before each host git that reads a worktree, **and** pin `GIT_COMMON_DIR` on every host git. Alternative: pin only (can't decide the directory from a poisoned worktree); or check only at launch (leaves the window to the next room).
3. **On a wrong link.** Lean: refuse the host git, say which file and what it should read, tell the operator through the inbox, and refuse the launch at launch. Alternative: warn and proceed (rejected), or auto-repair silently (rejected).
4. **Repair.** Lean: rewrite the link files and unlink a stray with plain file writes, never `git` from the suspect tree; `git worktree repair` only with the common directory pinned. Alternative: `git worktree repair` unpinned (reads a planted config — rejected).
5. **Where it lives and its API.** Lean: the environment core, in `policy/` beside `policy/worktrees.py`, called by launch and the host-git places; public API none, the full fix spawn's. Alternative: a public `Links` seam, deferred.
6. **Between checks.** Lean: state the window in guidance — the operator's own shell and editor are unprotected between checks, so treat a room-touched worktree as the room's until re-checked — and close it in spawn with read-only link mounts. Alternative: a host-side wrapper over the operator's git (out of scope).
