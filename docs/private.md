# Private: nothing of the operator's machine leaves under their name

A room mounts everything at the host's real paths (`docs/launch.md`, *The mounts*), so every session sees the operator's home path, user name and directory layout, and those details have reached commits, docs and GitHub issues of public repositories. `Private`, one of lup's default modules, keeps a list of what never leaves (the details lup reads on the host, and the person's own values) and checks what's about to: a push or a post carrying one is refused, a write carrying one is told and flagged, and the gate fails on one. The code is `packages/lup-dev/src/lup_dev/private/`.

## What's on the list

Built on the host by each launch, from the declaration at the approved commit (`building.py`, `withheld.py`; `docs/launch.md`, *The command*), and kept in the module's own data directory for the repository, which no room mounts. Where none is kept, as for a launch started before `Private` was approved, the host builds it the same way the first time the door, the judge or the gate's handler needs it, and keeps it; only where it can't be built does the door refuse, saying why. The project's own paths are its git directory and each worktree's root.

| Detail | Read on the host as |
|---|---|
| `home` | the operator's home, from the account database, and where it resolves where that differs |
| `user` | their user name |
| `hostname` | the machine's name |
| `alias` | each host in the URLs of the repository's remotes (`git url-parse -c host`) that `ssh -G` resolves to another name |
| `repository-path` | the project's own repository (its git directory and each worktree's root) and each related repository, each also as `~/…` |
| `private-repository` | each related repository GitHub says is private or internal (`gh repo view --json visibility`), or that has no copy there, by its name, `owner/name` and GitHub name |

GitHub is asked at each launch; where it can't answer, its answer at the last launch stands, and a repository it never answered for is left out, the launch saying so. The project's own name is never on the list: a private project names itself.

**Values are found** literally, ignoring case, never inside a longer word (a user name `op` is found in `op@host` and `-home-op-src-`, not in `operator`), the longest of overlapping ones (`found.py`). A value escaped, encoded or split across lines isn't found.

## How a project and a person use it

It's on by default. A project that doesn't want it drops it visibly, with its reason:

```python
project = Project(modules=Modules.default().drop("private", why="a scratch project nobody publishes"))
```

A person's own values are plain strings in their own layer, `lup_project.local.py`, which git ignores, and a detail that's an ordinary word on their machine is dropped there too:

```python
project = Project(modules=Modules().edit(Private(
    values=Values().add("Kestrel Labs", "gannet"),
    details=Details().drop("hostname", why="my hostname is `desktop`"),
)))
```

A value written in the committed `lup_project.py` would be published by its commit, so the commit's push would be refused for it.

## Where it's checked

- **The door, the guarantee.** lup's `Publishing` event comes before a push through its remote helper and a post through its GitHub tools (`docs/declaration.md`, *The doors*), and `Private`'s hook there refuses one carrying a value (`serving.py`, `refusing.py`). A push is read commit by commit beyond what the remote lists: each message, each path added or changed, each line added against every parent (a merge's resolution, not what a parent brought), a file that isn't text by its occurrences, and each ref's name (`history.py`). Where the list can't be built, nothing leaves, saying why.
- **At a write.** A value on a line the write touches, in any path git doesn't ignore (docs, tests and data included), is a finding told right after the write, and the write is flagged for the operator (`private` in `Project.flagged`; `docs/judging-writes.md`). It's never refused there: the write lands.
- **The gate's `private` step** (`lup-dev private check`) reads every file and `HEAD`'s commits the remotes lack, catching what the shell wrote and what a commit's message says, before the branch lands. In a room it asks the host through the module's request (`serving.py`, `Scanning`). Where the list can't be built it fails, saying why; it passes, saying so, only where the host can't be reached from a room, or, outside one, where no launch was approved on the machine, as in CI, since a CI runner's user name, `runner`, is an ordinary word.

## What a room is told

A kind and a place, never the value: the room never sees the list, so a value of the person's own stays out of the agent's screen and transcript. A path naming a value is shown masked. A push's refusal, on git's standard error:

```
lup refused to publish this push to `refs/heads/feat`: a module's check at `Publishing` found what isn't published, at each place below.
  4e1f2a3 docs/notes.md:2:5 - the operator's home path
      steer: write it as `~`, or a path in the repository from its root
A push sends every commit the remote lacks, so rewrite the commit that carries it (amend it, or rebase) and push again: a commit on top leaves it in what's pushed.
```

A room can still confirm a value it already guesses whole, by writing it and reading the place; it can't read the list. Nothing in a room lets a value through: the operator publishes what they mean to from their own terminal, where neither the helper nor lup's tools run.

## What it doesn't cover

What leaves through the room's open network, the commits' author and committer, an annotated tag's message (tags are protected by default), and what's published already.
