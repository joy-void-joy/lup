# Setting a repository up

`lup init` sets lup up in a repository that exists; `lup new <name>` makes one, set up for lup, with a module of its own. Both are the core's commands, typed at `lup`'s top level, the operator's alone, served by the core's part `Setup` (`part.py`); the files they write are `skeleton.py`'s. Nothing of lup is copied into a project: it depends on lup's core, and its declaration selects lup's modules and its own.

## Where they run

They're lup's own program acting on the operator's machine, writing their files and running their git and uv, never a project's code. So `lup` answers them in the process it's typed in, as the operator, over lup's default modules alone, before it reads any declaration or reaches lup's program on the machine (`lup.environment.command_line.main`), and they read nothing of a repository's declaration but whether its file is there.

Each takes everything as arguments, where it's typed unless `--directory` says otherwise, and answers what it did as a model (`SetUp`), which the command line prints as JSON: the worktree's root, the declaration written, whether the gitignore line was added, the dependency on lup's core, the project's own module where one was made, the programs lup's other parts run that aren't there, and whether the operator's lup was told of the repository, and why not.

## `lup init`

In the worktree of a repository (`RepositoryLayout.located`, git finding its root from the directory):
1. **lup's core, as the project's dependency,** added by `uv add`, never by editing its `pyproject.toml`, locked and synced into no environment (`--no-sync`): uv would otherwise sync the one `UV_PROJECT_ENVIRONMENT` names, which, under `uv run`, is the environment `lup` runs in, not the project's, whose first `uv run` makes its own; where it has none, `uv init --bare` writes one first, holding nothing else, so nothing lands among the project's own files. It's added first, since uv may refuse it (a project on an older Python), and then nothing else is written.
2. **Its declaration,** `lup_project.py` at the root, or the file `[tool.lup]` names, binding lup's default modules (`Project()`). A declaration already there is never overwritten: `init` refuses, writing nothing.
3. **The line ignoring its local layer** (`/lup_project.local.py`, named after the declaration) in `.gitignore`, added only where no line there names it.

It makes no module of the project's own.

Until lup's releases are published (#23), the dependency is the core from GitHub at the commit of the lup running `init`: the commit an install from git records (`direct_url.json`, PEP 610), or, where the core is installed from a directory, as lup's own workspace installs it, that checkout's `HEAD`, which git gives. An install from an index records no commit, and `init` refuses.

Once the repository is set up, `lup` registers it with the operator's lup, so the dashboard lists it: it sends `hosting register` (the repository named after its main worktree, its shared git directory, its declaration) to lup's program on the machine, over the socket `LUP_CALLING` names, else the machine's own, started first where nothing answers there (`lup.environment.setup`). That's `lup`'s, on the environment side, not the part's: a part's code reaches no command of the machine's. Without podman no machine runs, and nothing is registered; the answer says whether it was, and why not (`registered`, `unregistered`).

## `lup new <name>`

Makes `<name>`'s directory, then:
1. a git repository there (`git init`), its own even inside another's worktree;
2. a uv workspace (`uv init --bare --no-workspace`), its root named `<name>-workspace`, holding no code of its own, the Python versions lup's core runs on;
3. its own module, `modules/<name>/`, laid out as lup's own modules are (`modules/core/` is the model): a `pyproject.toml` naming the distribution `<name>`, depending on lup's core; its package under `src/`, `<name>` with each `-` a `_`, its `Module` subclass at the top (`story-reader`'s is `StoryReader`), with the docstring lup shows it by; its promises in `promises.py`, one scenario; and its `README.md`;
4. what `init` writes, its declaration selecting lup's default modules and its own;
5. the module as a member of the workspace (`uv add --workspace`), and the dev group checking its promises: `pytest`, and lup's core with what checking promises needs (`lup-core[environment,dashboard]`, the harness importing the dashboard's server), so `uv run pytest` checks them from the first day.

A name is lowercase letters and digits, words joined by `-`. It's refused, with nothing written, where it would shadow: the core's, one of the core's tools, commands and views (`lup` would type the module and the command alike), a Python keyword, or a package Python finds already. A directory there already is refused too. A step failing after the directory is made removes it.

Which demo templates `new` offers beside this skeleton is open, with room left for a `--template` option.

## What they need

`Setup` declares git and uv as programs (`Program`), with what lup runs each for and how to install it, and runs them through those fields, so a promise stands each in. Both are optional, so a project's container without them still starts its other parts: where either isn't there, `Setup` isn't made, and `init` and `new` are refused before anything runs or is written, saying how to install it (`Program.checked`, before a part starts). Both also check the programs lup's other parts run, the core's and the machine's, and say which aren't there or aren't at a version they take (`missing`): podman, which runs a project's parts in containers, among them. None of those stops `init` or `new`.

## Promises

`promises.py`, through the harness, each in a temporary directory, git and uv stood in for: `init` writes a declaration that loads and resolves to lup's defaults, and adds the core pinned to a commit; never overwrites a declaration; leaves one gitignore line for the local layer; writes nothing where uv refuses the core; says which optional programs are missing; `new` makes a project whose every Python file compiles and TOML file reads, whose declaration loads and selects its own module, a member of its workspace; a name `new` can't take, and a missing git or uv, refuse with nothing run or written.
