# lup's docs

Each describes a module as it's built: what it's for, how to use it, and the reasons that aren't obvious. What lup is meant to be is `DESIGN.md`.

- `field-notes.md`: what was measured or read from a runtime's source, with its version and date.

Each module's doc is in its directory:
- `modules/core/README.md`: the core, every project's, and how it's laid out.
- `modules/core/src/lup/declaration/README.md`: the declaration, what a project writes to say which modules it's made of, and its grammar.
- `modules/core/src/lup/doors/README.md`: the doors a module's methods are reached through, who may call them, and how a module serves them.
- `modules/core/src/lup/testing/README.md`: promises, what a module promises and how the gate checks it, and the harness a promise reaches lup through.
- `modules/core/src/lup/programs/README.md`: running programs, lup's one runner of them, and why its promises start real ones.
