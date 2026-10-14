# Related repositories, read-only in a room

**One sentence:** a person declares, in their own uncommitted layer of the declaration, the other repositories their sessions may read, each saying what it is, and a launched room mounts each one read-only, while lup's GitHub read tools take any repository the operator's login can read.

The operator's request (2026-10-14): "all of our repositories [should be] easily [read-only] accessible", each declared explicitly, "what project is what". It builds on piece 2 (`docs/host-tools.md`): the room's mounts (`docs/launch.md`, *The mounts*), lup's GitHub tools, and the guidance a launch renders.

## Decisions

All answered by the operator on 2026-10-14: each lean below taken as stated.

1. **GitHub's read tools reach any repository** (decided by the operator): `read_issue` and `find_issues` take an optional `repository` (`owner/name`), any the operator's `gh` login can read; without it, the session's own. The write tools (`file_issue`, `comment`, `draft_pull_request`) stay on the session's own repository, within its limits.
2. **A `Repositories` part of the declaration** (decided: declared explicitly), each entry a `Repository` naming what it is: **(leaning)** any module may hold one, merged by name as `Packages` are, so `Core` holds none and a project's own module lists its neighbours.
3. **What an entry says (leaning):**
   - `name`, how sessions and the guidance call it;
   - `path`, the repository on the host (a bare repository's git directory, or a clone's working tree with its `.git`), relative to the directory holding the project's own repository (so `"lup-legacy.git"` beside `lup.git`), or absolute, `~` expanded: lup's repositories sit side by side under one directory, so a relative path holds on any machine laid out the same;
   - `about`, one line on what it is and what it's for here (for lup's first version: "the first lup: evidence of how things behaved, never code to copy");
   - `github`, its `owner/name` where it has one, which the guidance gives so a session reaches its issues through the read tools.
4. **Mounted whole, read-only, at its host path (leaning):** the git directory and, for a bare repository with worktrees under it (lup's layout, `tree/<branch>`), its worktrees too, so a session reads files as they stand and history through git. Declaring a repository is the choice to expose it to its rooms: a worktree's untracked files (an `.env`) become readable by anything running there, which open egress could send out. The alternative: committed content only, the worktrees hidden under an empty tmpfs as `docs/field-notes.md` (*Rooms*) measured, reading code through `git show` and `git grep <rev>` alone.
5. **A declared repository missing on the host (leaning):** the launch says so in one line and goes on, the guidance marking it unavailable; no clone is made for it. The alternative: a read-only clone kept in lup's cache from its `github`, fetched at each launch with the operator's credentials, a later step if a machine needs it.
6. **The guidance lists them,** after lup's tools: each repository's name, path, what it is, and its GitHub identity.
7. **A person's own layer, `lup_project.local.py`** (the operator's): which repositories a person relates, and what each is, are theirs, never committed or on GitHub. They go in the person's own declaration, at the root beside `lup_project.py`, gitignored and protected as `AGENTS.local.md` is, in the same grammar, layered on top of the project's: the per-person layer the session settings' order left for later (`docs/launch.md`, *The settings compiled for each runtime*: the runtime's default, lup's defaults, the person's runtime settings, the project's declaration, then the person's own). Repositories are its first use; any part of the declaration a person changes for themselves goes there too.
8. **Trust on launch covers it** (the operator's): it's Python run on the host, and a room writes the worktree, so an edit made in a room must not run unseen. It joins the host zone by its content, since git holds none of it: approved with the rest, an unchanged file asks nothing, a changed one shows its diff in the trust summary, and nothing new of it runs until approved. The judge reads the approved copy, kept with the approval, as it reads the project's declaration at the approved commit.

## What's built

- **The declaration** (`declaration/kinds.py`): `Repository` (`name`, `path`, `about`, `github`), `Repositories` (a `Named` selection), resolved with the rest at the approved commit; a path that's neither relative nor absolute, or two entries of one name with different paths, fails the load naming them.
- **The room** (`launch/room.py`): each resolved repository that exists mounted read-only at its host path, after the project's own; one that's missing said once; a repository already inside the project's own mounts (the project itself) refused, naming it. A mounted repository's own `config` and `hooks/` are read-only with the rest, so nothing in the room changes how the operator's git runs there.
- **The GitHub tools** (`forge/tools.py`): `read_issue` and `find_issues` gain `repository`; `find_issues` keeps dropping results from other repositories than the one asked.
- **The guidance** (`launch/guidance.py`): the list, with each repository's state (mounted, or missing).
- **The person's layer** (`declaration/load.py`, `launch/trust.py`, `approval.py`): `lup_project.local.py` found beside the declaration, loaded after it and layered on top, gitignored (the repository's `.gitignore`) and a protected path (`catalog/paths.py`); its content in the host zone, its approved copy kept with the approval and read by the judge and the launch.

## Tests

- The declaration: an entry resolved, layered by name, refused when malformed; paths relative and absolute.
- The room: a declared repository mounted read-only at its host path, a missing one said, the project itself refused.
- The GitHub tools: a `repository` passed to `gh` as `--repo`, through the stand-in `gh`.
- The guidance: the list rendered.
- The person's layer: layered over the project's declaration; absent, nothing changes; its edit shown and asked at the next launch's trust, unchanged asking nothing; the judge reading the approved copy, not the edited file.

## Checks owed

- In a room on each runtime: a session reading a related repository's file, and its history with `git log` and `git show`, read-only (a write refused by the mount).
