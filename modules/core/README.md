# The core

The module every project holds: what every project has, packaged as submodules, which a project changes or replaces as it would any module but can't drop (`DESIGN.md`, *Modules*). Its distribution is `lup-core`, and it imports as `lup`.

## Layout

- **`lup`**, the front door: the bases every model starts from (`lup.types`), the root of lup's errors (`lup.errors`), `Core`, and each submodule's library side re-exported, running programs under its own name (`lup.programs`). A project's declaration and a module's code import it, and nothing else of the core but the harness (`lup.testing`), which promises import.
- **`Core`** (`lup.core`), the module itself, listing its submodules' promises in its `parts`. `lup` imports it when it's first used, since its promises import `lup`.
- **One directory per submodule** under `src/lup/`, each with its own `README.md`: its library side at its top, its promises in its `promises.py`, its environment side under `lup.environment`, named after it. An import contract in `pyproject.toml` holds every library side away from `lup.environment`, and another holds promises to `lup` and `lup.testing`.

lup declares itself as any project does, in `lup_declaration.py` at the repository's root, and its gate checks the promises of the modules that resolves to.

## Submodules

- **The declaration** (`lup/declaration/`, `lup.environment.declaration`): what a project writes to say which modules it's made of, the grammar every module's parts are written in, and loading and resolving it. `README.md` there.
- **The doors** (`lup/doors/`, `lup.environment.doors`): what a module's methods are reached through (`@lup.tool`, `@lup.service`, `@lup.action`, `@lup.command`, `@lup.on`), the parties who may call them, the parts a module is made of, each made once where it runs, holding what it holds, and starting, calling and stopping them. `README.md` there.
- **Promises** (`lup/testing/`, `lup.environment.testing`): what a module promises (`@lup.promise`, a law or a scenario), the harness a promise reaches lup through, and checking them, with the pytest plugin the gate runs them through. `README.md` there.
- **Programs** (`lup/programs/`): running a program, lup's one runner of them, which every module's code uses: to its end, on an event loop, or beside its caller. `README.md` there.
