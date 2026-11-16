# The core

The module every project holds: what every project has, packaged as submodules, which a project changes or replaces as it would any module but can't drop (`DESIGN.md`, *Modules*). Its distribution is `lup-core`, and it imports as `lup`.

## Layout

- **`lup`**, the front door: the bases every model starts from (`lup.types`), the root of lup's errors (`lup.errors`), and each submodule's library side re-exported. A project's declaration and a module's code import it.
- **One directory per submodule** under `src/lup/`, each with its own `README.md`: its library side at its top, its environment side under `lup.environment`, named after it. An import contract in `pyproject.toml` holds every library side away from `lup.environment`.

## Submodules

- **The declaration** (`lup/declaration/`, `lup.environment.declaration`): what a project writes to say which modules it's made of, the grammar every module's parts are written in, and loading and resolving it. `README.md` there.
