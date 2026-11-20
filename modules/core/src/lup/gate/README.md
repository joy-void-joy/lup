# The gate

What a branch passes before it lands: the steps every module declares, run on the files of a worktree, every one even after one fails, and a pass recorded by the files it passed on. `Gate` is a module of its own among lup's default modules, so a room that leaves the code's checks out, a playground's, drops it. Its library side (`lup.gate`, `Step` and `Steps` re-exported by `lup`) is what a module declaring a step imports.

```python
from lup import Module, Step, Steps


class Notes(Module):
    """Notes that must hold together."""

    name = "notes"
    steps: Steps = Steps.of(Step(name="notes", command=["notes", "check"], together=True))
```

## Steps

A step is a program and its arguments (`command`), run from the worktree's root in the environment the gate runs in, passing where it ends with status 0. It may say:
- `fix`: what `--fix` runs first, before any step checks, rewriting the files it would fail on;
- `together`: it only reads the worktree, so it runs at once with the steps beside it that say so too. A step that writes what another reads, as one building a file does, runs alone. Every step's line is still reported in the declaration's order;
- `tells`: what it prints is told even where it passes, as a step listing what's due without failing does. Otherwise a step's output is told only where it fails.

Any module declares its own as a field of `Steps`, and the gate runs every module's, each module's in its order, in the order of the modules (`Declared`, `lup/doors/README.md`). A project drops, edits or replaces one as it would any selection: lup's own declaration runs `promises` on twelve workers, and adds the dashboard page's step, which only lup's repository has, since a project installs the page built.

`Gate`'s own steps check what every project lup sets up has:
- `format`: ruff's formatter, which its fix runs;
- `promises`: pytest, the promises of the modules the declaration resolves to and the examples in docstrings (`lup/testing/README.md`);
- `imports`: the project's import contracts, through import-linter.

## `lup gate check`

It runs where it's typed (`@lup.command(here=True)`, `lup/command_line/README.md`): a branch's own checks, its tests among them, run in the room it's typed in, over that worktree's declaration and environment. Carried to where the project runs, it would check the commit the operator approved, never the worktree. `--directory` checks another worktree than the one it's typed in.

Every step runs, even after one fails, and the report says how each ended and how long it took, then what a failing step printed. A step's program that can't be run fails the step, saying why. Where any fails, the check is refused, so the command ends failed.

## A pass

A pass is recorded by the files it passed on: the tree git would commit the worktree as, every change and every file it doesn't ignore added, read through an index of the gate's own so the worktree's stays as it is; and what crosses into a check from outside those files, the repository's own layer of the declaration and the machine's, which change what runs. It's kept in the repository's git directory, the one every worktree and room shares (`GateLayout`), so a check on the same files runs nothing, wherever they're checked out, a landing among them; `--again` runs every step anyway. With `--fix`, the fixes run first and the pass is looked for on the files as they left them.

Only the whole tree keys a pass, never the files a step says it reads: the second lup's page step, keyed on its own list of sources, passed a model it never saw change.

## Promises

`promises.py`, through the harness, on a worktree in a temporary directory, git and each step's program stood in for (git answering as a repository there would, ruff laying out what it's given): every module's steps run from the root, every one even where another fails, and a failure refuses the check; a pass runs nothing again on the same files, unless asked, and a changed file or local layer runs every step; fixes run before any check; outside a worktree, nothing runs.
