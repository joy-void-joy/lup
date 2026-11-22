# Private

What never leaves under the operator's name: details of their machine that agents see in every room, since a room mounts the repository at its real path, and values of their own. A push or a post holding one is refused, saying where, never what, and the gate fails on one. `Private` is one of lup's default modules; a project drops it with its reason.

## What's withheld

The list is the machine's alone, built for each project by `Withholding`, a part holding the machine, and never lent to any container, `Private`'s own included, nor shown to a room:
- **what lup finds** (`Private.details`, each kept unless a layer drops it): the operator's home path, their user name, the machine's name, each host of the project's remotes their ssh configuration resolves to another name (an alias), and the project's own path, each path also as `~/…`;
- **their own values** (`Private.values`), set in the machine's layer, `~/.config/lup/lup_project.local.py`, which applies to every project and which no room mounts, where they list their name, a client's, their hardware: what they mean, rather than what lup would guess;
- **an inbox item's number** (`@1505`, a part's `@1505.3`) in prose, a commit's message or a post's part, read as Markdown (`cited.py`, markdown-it), so never in code, after a backslash, in an address, or running on into a word or a version: on GitHub it mentions a user, and the number means nothing there.

```python
# ~/.config/lup/lup_project.local.py
from lup import Modules, Project
from lup.private.module import Details, Private, Values

project = Project(
    modules=Modules().edit(
        Private(
            values=Values().add("Kestrel Labs", "RTX 4090"),
            details=Details().drop("hostname", why="my machine is called `desktop`"),
        )
    )
)
```

## How a value is found

Literally, ignoring case, never inside a longer word (a user name `op` is found in `op@host` and `/home/op/x`, not in `operator`), the longest of overlapping ones (the project's path, not the home holding it as well); a file that isn't text, as bytes, ignoring ASCII case (`found.py`). A value escaped, encoded or split across lines isn't found.

## Where it's refused

- **At `Publishing`** (`lup/publishing/README.md`): each project's `Guard` hears what's about to leave (a push's ref, each commit the remote lacks with its message, its paths and its added lines, or a post's parts) and asks `Withholding`, which says where it found something, by its kind and with how to write it instead. Found, nothing leaves, and the agent is told each place; a push's refusal says to rewrite the commit that carries it, since a push sends every commit the remote lacks.
- **At the gate** (`lup private check`, the `private` step): the worktree's files git would commit, and the messages of the commits its remotes lack, checked the same way, by the machine, through the room's socket.
- Where the list can't be built (no `git` or no `ssh` on the machine), nothing is checked, so nothing leaves: a refusal says why.

A project the machine doesn't run, as lup answering in a process of its own has none, has no path or remotes to withhold; the rest is.

## What it doesn't cover

What leaves through a room's own network, a commit's author and committer, an annotated tag's message, a write that carries one (flagged with the findings told after each write, #9), and what's published already: an edit keeps GitHub's history, which only the operator clears.

## Promises

`promises.py`, through the harness, `Withholding` started in the promise's process, git run for real and ssh stood in for: a value of the operator's machine layer is found however cased and never inside a longer word, and named by its kind, never said; an item's number is found in prose, never in code, after a backslash or in a file; a post holding a value withheld never reaches GitHub.
