# Related repositories, read-only in a room

A person names, in their own uncommitted layer of the declaration, the other repositories their sessions may read, each saying what it is. A launched room mounts each one whole and read-only at its host path, the guidance lists them, and lup's two GitHub tools that read reach any repository the operator's login can read.

## What we have

Paths are under `packages/lup-dev/src/lup_dev/` unless they name another package.

| Where | What it holds |
|---|---|
| `declaration/kinds.py` | `Repository` and `Repositories`, a `Named` selection any module may hold; `Core` holds none. |
| `declaration/resolve.py` | `neighbours`: every module's entries merged by name into `Resolved.repositories`. |
| `launch/room.py` | `related`, each entry found on the host (`RelatedRepository`); `maintaining_room` mounting them, `apart` refusing an overlap. |
| `cli.py` (`launched`) | Each missing one said. |
| `launch/guidance.py` | `repositories`, the guidance's *Other repositories*. |
| `packages/lup/src/lup/github/tools.py` | `read_issue` and `find_issues`, taking `repository`. |
| `declaration/load.py`, `launch/trust.py`, `approval.py`, `launch/session.py` | The person's own layer: found, loaded on top of the declaration, approved by its content. |

### An entry

```python
Repository(
    name="other-project",
    path=Path("other-project.git"),
    about="the service this project talks to: read its API, never change it",
    github="someone/other-project",
)
```

`path` is a bare repository's git directory, with its worktrees under it, or a clone's working tree, with its `.git`. A relative path is from the directory holding the project's own repository (the parent of a bare repository's git directory, or of a clone's working tree), so where a person keeps their repositories side by side under one directory, the entry holds on any machine laid out the same; an absolute one works too, a leading `~` the operator's home. `about` is one line on what it is and what it's for here, which sessions read in the guidance. `github` is optional, and lets a session read the repository's issues. An entry with no name, no path or no `about`, or a `github` that isn't `owner/name`, fails the load naming it; so does one name given two paths by two modules, where the same name and path from two is one repository.

### In the room

Each one found is mounted whole, read-only, at its host path, so a session reads its files as they stand and its history through git, at the paths the guidance gives. Its own `config` and `hooks/` are read-only with the rest, so nothing in the room changes how the operator's git runs there. Mounted whole means a worktree's untracked files (an `.env`) are readable by anything running in the room, which open egress could send out: naming a repository is choosing to expose it to its rooms.

One that isn't on the host is said once at launch and passed over, and the guidance marks it missing; nothing is cloned for it. One that overlaps the room's own mounts is refused, inside one (the project itself) or holding one, since mounted read-only it would sit over or under what the room writes.

In the guidance, after lup's tools, *Other repositories* lists each by its name, its `about`, its path, whether it's mounted or missing on this machine, and its GitHub identity, under a line saying each mounted one is read-only and how to read its issues.

### GitHub's read tools

`read_issue` and `find_issues` take an optional `repository`, `owner/name`, any repository the operator's `gh` login can read; without it, the launch's own. Reading stays within the declaration's limits (`read-issues`). The tools that write (`file_issue`, `comment`, `draft_pull_request`) act on the launch's own repository alone. `find_issues` leaves out matches GitHub returns from other repositories than the one searched, saying how many.

### A person's own layer

Which repositories a person relates, and what each is, are theirs: they go in `lup_project.local.py`, never in a committed declaration or on GitHub. Any other part of the declaration a person changes for themselves goes there too.

- **One per repository,** in its main worktree, a clone's root or a bare repository's own directory (`person_layer`, through `Git.main_worktree`), so every worktree shares it, one added later included, which git gives no ignored file.
- **Kept out of git and guarded:** ignored by the repository's `.gitignore`, and a protected path (`catalog/paths.py`), as `AGENTS.local.md` is, so a write to it asks the operator.
- **The same grammar:** it binds `project`, a `Project` written as a layer on the project's, so `Project(modules=Modules().add(Mine()))` adds a module of the person's, applied as a module layers (`applied`). It runs after the declaration in the same import, from its path since its name holds a dot (`load`, `executed`; `Declared.local` names it), so it can import the project's own modules and edit them.

### Trusted by its content

It's Python the host runs, and a room writes the worktree, so an edit made in a room must not run unseen. Git holds none of it, so trust on launch puts it in the host zone by its content (`Zone.local`), with what it imports of the commit:
- unchanged, it asks nothing; changed, created or removed, its diff is in the summary itself, git's own over the two copies (`compared`, `git diff --no-index`), since git's count of the zone can't show a file git doesn't hold;
- the approved copy is kept whole in the approval (`Approval.local`). The judge and a launch read that copy, written beside the commit's export (`Layout.exported`, one export per copy; `approved_declaration`), never the worktree's; every export leaves out a layer a commit holds anyway (`read_by_import`), which would run unapproved;
- approved where only the layer changed, nothing is installed and no service restarts (`Trusted.installed`): the judge reads the layer from the approval at each hook.

The gate reads the layer as it stands, as it reads the worktree's declaration.
