# lup's docs

Each describes a module as it's built: what it's for, how to use it, and the reasons that aren't obvious. What lup is meant to be is `DESIGN.md`.

- `field-notes.md`: what was measured or read from a runtime's source, with its version and date.

Each module's doc is in its directory:
- `modules/core/README.md`: the core, every project's, and how it's laid out.
- `modules/core/src/lup/declaration/README.md`: the declaration, what a project writes to say which modules it's made of, and its grammar.
- `modules/core/src/lup/doors/README.md`: the doors a module's methods are reached through, who may call them, and a module's parts, made once where they run.
- `modules/core/src/lup/testing/README.md`: promises, what a module promises and how the gate checks it, and the harness a promise reaches lup through.
- `modules/core/src/lup/running/README.md`: running a project's modules: the plan the program on the operator's machine reads, what crosses between it and a container, and the program a container runs.
- `modules/core/src/lup/shell/README.md`: the shell, the view door, the blocks a view answers and the kinds a module declares for them.
- `modules/core/src/lup/hosting/README.md`: what runs on the operator's machine, and who may call it.
