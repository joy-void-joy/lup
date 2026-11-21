# The core

The module every project holds: what every project has, packaged as submodules, which a project changes or replaces as it would any module but can't drop (`DESIGN.md`, *Modules*). Its distribution is `lup-core`, and it imports as `lup`.

## Layout

- **`lup`**, the front door: the bases every model starts from (`lup.types`), the root of lup's errors (`lup.errors`), `Core`, and each submodule's library side re-exported, running programs under its own name (`lup.programs`). A project's declaration and a module's code import it, and nothing else of the core but the harness (`lup.testing`), which promises import.
- **`Core`** (`lup.core`), the module itself, listing its submodules' promises in its `parts`. `lup` imports it when it's first used, since its promises import `lup`.
- **One directory per submodule** under `src/lup/`, each with its own `README.md`: its library side at its top, its promises in its `promises.py`, its environment side under `lup.environment`, named after it. An import contract in `pyproject.toml` holds every library side away from `lup.environment`, and another holds promises to `lup` and `lup.testing`.

lup declares itself as any project does, in `lup_declaration.py` at the repository's root, and its gate checks the promises of the modules that resolves to.

## Submodules

- **The declaration** (`lup/declaration/`, `lup.environment.declaration`): what a project writes to say which modules it's made of, the grammar every module's parts are written in, and loading and resolving it. `README.md` there.
- **The doors** (`lup/doors/`, `lup.environment.doors`): what a module's methods are reached through (`@lup.tool`, `@lup.service`, `@lup.command`, `@lup.on`), the parties who may call them, the parts a module is made of, each made once where it runs, holding what it holds, and starting, calling and stopping them. `README.md` there.
- **Running** (`lup/running/`, `lup.environment.running`): a declaration's plan, which the program on the operator's machine reads rather than running it, what crosses between it and a container, and the program a container runs. `README.md` there.
- **Hosting** (`lup/hosting/`), a module of its own the home repository selects: the parts that run on the operator's machine, starting every container behind the same walls, and, as they're built, carrying calls, keeping approvals and secrets, and brokering credentials. `README.md` there.
- **Promises** (`lup/testing/`, `lup.environment.testing`): what a module promises (`@lup.promise`, a law or a scenario), the harness a promise reaches lup through, and checking them, with the pytest plugin the gate runs them through. `README.md` there.
- **Programs** (`lup/programs/`): running a program, lup's one runner of them, which every module's code uses: to its end, on an event loop, or beside its caller; and its companion for git (`lup/programs/git/`), which every module asks git through, each question a method reading git's answer into a model. `README.md` in each.
- **Guidance** (`lup/told/`, `lup.environment.told`): the guidance door (`@lup.guidance`), each module's sections of what a session is told at its start, written in Python, rendering them in the declaration's order, and the room they may take under the smallest runtime's ceiling. `README.md` there.
- **The shell** (`lup/shell/`, `lup.environment.shell`): the view door (`@lup.view`), the blocks a view answers, the kinds a module declares for them, and answering a view; the dashboard's page that draws them. `README.md` there.
- **The command line** (`lup/command_line/`, `lup.environment.command_line`): `lup <module> <name>`, running a module's tools, commands and views by name as whoever types it may, the answerer its calls go through, and a project's own command. `README.md` there.
- **Setting a repository up** (`lup/setup/`): `lup init`, setting lup up in a repository that exists, and `lup new <name>`, making one with a module of its own, the operator's commands at `lup`'s top level, run where they're typed. `README.md` there.
- **The store** (`lup/store/`): the records every module keeps its state as, the kinds a module declares them in (`Recorded`), and the database keeping them. `README.md` there.
- **The inbox** (`lup/inbox/`): parties, the concerns they hold, what's said between them, and where each stands, kept in the store. `README.md` there.
- **The runtimes** (`lup/runtimes/`): Claude Code and Codex behind one interface, and reading each one's records of its conversations as lup's model of one, which the dashboard's buffer and transcripts read. `README.md` there.
- **The gate** (`lup/gate/`), a module of its own among lup's default modules: the steps every module declares, run on a worktree's files where `lup gate check` is typed, and a pass recorded by the files it passed on. `README.md` there.
- **Landing** (`lup/landing/`), a module of its own among lup's default modules, needing the gate: an agent landing their branch for the operator's review, what's on trial in what the operator's lup runs, computed on the machine, and accepting a branch onto the integration branch. `README.md` there.
- **The code rules** (`lup/code_rules/`), a module of its own a project adds, not among lup's default modules: patterns rarely the right choice, read with pyright's own tree through an engine built where it first runs, told after each write in a session's room and checked by the gate's `rules` step with pyright's and ruff's findings, and the `# lup:` comments every module reads. `README.md` there.
