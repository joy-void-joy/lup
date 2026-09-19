- `{{ library_git }} rev-parse --abbrev-ref HEAD` — the branch the library would come from
- `{{ library_git }} symbolic-ref --short refs/remotes/origin/HEAD` — what the remote treats as stable

When they differ, {{ ask }}

Record the branch and the commit the answer settles on. Everything below is
about that commit — the acquisition mode pins its branch and the upstream
checkpoint is taken at it — so the checkout supplying the library has to be
standing there before you go on.


<!-- passage: library-as-a-package -->
A project depends on `lup` as a package rather than keeping a copy of the
library's source. Half the answer is a fact to look up rather than a
preference — whether a release exists at all, and which:

```
{{ project_devtools }} dev library release
```

It reports the released version, or that none is published yet, and prints the
command that declares what it found — so the release number is read from the
index rather than guessed at.

The other half is a judgement about what this project is to lup, and the
look-up does not make it. Ask the user which of these describes them:

| Mode | The project it is for | Command |
| --- | --- | --- |
| published | A consumer of the library: it takes releases and upgrades on its own schedule | `{{ celled }} dev library use published --version <release>` |
| **git** | Either nothing is published yet, or the project works *on* lup as well as with it — running a branch to dogfood it and sending changes back | `{{ celled }} dev library git --branch <branch>` |

A project developing lup alongside its own work takes git mode as well, pinned
at the branch carrying its changes: the library then moves when a command moves
it, and `uv.lock` records the commit it moved to — which is what lets
`{{ celled }} dev update` hold the library, the generated trees and the copied half
at one upstream commit.

With nothing published, git is the only mode that resolves, so the look-up
settles it. Once a release exists, published is the quieter default and git
stays a live choice: a project that reads the library's own diffs, or that
expects to send work back, is better served by the branch it is improving than
by the last release cut from it. Both hand the project a real package, so
its `packages/lup/` stays absent and nothing has to be merged later. Vendoring
is not on this list — a vendored copy is a fork with all the reconciliation
that implies, and is only right for a project that genuinely intends to modify
library source.

The git mode resolves `subdirectory = "packages/lup"`, because the distribution sits inside the repository rather than at its root, and pins whichever ref you name. **The ref resolves against the remote, not against any checkout on disk**: uv fetches the branch as the remote has it, so work the remote has not seen is not in what you pinned. Before declaring a git source, read what the remote's branch actually resolves to — `{{ library_git }} ls-remote origin <branch>` names that tip — and if it is not the recorded commit, say so rather than pinning a dependency whose contents you have not accounted for.

The extras come from what the project runs: `claude` and/or `codex` for the
adapters it drives, `docker` for the code-execution sandbox, `web` for the
session API. Name them in the requirement (`lup[claude,codex,docker]`).


<!-- passage: upstream-checkpoint -->
Baseline the upstream checkpoint at *the recorded commit*, not at whatever the
remote's default branch points to. `--synced` reads the checkpoint from the
named checkout's HEAD, so that checkout has to be standing at the recorded
commit when this runs:

```
{{ project_devtools }} sync setup lup {{ library_checkout }} --branch <branch> --synced
```

`setup` records that checkout, the branch settled on above, and its HEAD as the checkpoint, so `{{ update_skill }}` only shows commits that land afterward. Plain `sync mark-synced lup` is wrong here: the shipped `sync.json` entry carries a URL and no branch, so it clones the remote's default branch and checkpoints *that* HEAD — so every commit the project already carries comes back as unported work once the branch merges.

A project that already consumed the library, and knows which commit it took, names it rather than moving a checkout to stand on it:

```
{{ project_devtools }} sync mark-synced lup --at <commit>
```

That is the case an adoption mid-stream is always in — the code is already here, and what is missing is only the record of how far it reached. Without the commit, marking synced claims every commit that landed afterward as reviewed, which is the one thing the checkpoint exists to prevent.

