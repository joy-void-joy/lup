# lup's docs

Each describes a module as it's built: what it's for, how to use it, and the reasons that aren't obvious. What lup is meant to be is `DESIGN.md`.

- `field-notes.md`: what was measured or read from a runtime's source, with its version and date.

Each module's doc is in its directory:
- `modules/core/README.md`: the core, every project's, and how it's laid out.
- `modules/core/src/lup/declaration/README.md`: the declaration, what a project writes to say which modules it's made of, and its grammar.
- `modules/core/src/lup/doors/README.md`: the doors a module's methods are reached through, who may call them, and a module's parts, made once where they run.
- `modules/core/src/lup/testing/README.md`: promises, what a module promises and how the gate checks it, and the harness a promise reaches lup through.
- `modules/core/src/lup/programs/README.md`: running programs, lup's one runner of them, and why its promises start real ones.
- `modules/core/src/lup/programs/git/README.md`: git's companion, where every module asks git, how git is run, and what a store a room writes is read as.
- `modules/core/src/lup/running/README.md`: running a project's modules: the plan the program on the operator's machine reads, what crosses between it and a container, and the program a container runs.
- `modules/core/src/lup/told/README.md`: guidance, each module's sections of what a session is told at its start, the door they're written behind, rendering them, and the room they may take.
- `modules/core/src/lup/shell/README.md`: the shell, the view door, the blocks a view answers and the kinds a module declares for them.
- `modules/core/src/lup/hosting/README.md`: what runs on the operator's machine, and who may call it.
- `modules/core/src/lup/command_line/README.md`: the command line, `lup <module> <name>`, the answerer its calls go through, and a project's own command.
- `modules/core/src/lup/setup/README.md`: setting a repository up for lup, `lup init` and `lup new`, and what they write.
- `modules/core/src/lup/store/README.md`: the store, the records modules keep their state as, and the database keeping them.
- `modules/core/src/lup/inbox/README.md`: the inbox, parties, concerns and piles, what's said between them, and where each stands.
- `modules/core/src/lup/runtimes/README.md`: the runtimes lup holds sessions on, behind one interface, and reading each one's records of its conversations as lup's model of one.
- `modules/core/src/lup/gate/README.md`: the gate, the steps every module declares, run on a worktree's files, and a pass recorded by the files it passed on.
- `modules/core/src/lup/landing/README.md`: landing a branch, the operator's review, what's on trial in what their lup runs, and accepting it onto the integration branch.
