# lup's docs

Each describes a piece as it's built: what it's for, how to use it, and the reasons that aren't obvious. What lup is meant to be is `DESIGN.md`.

- `declaration.md`: what a project declares in `lup_project.py`, its modules, the person's own layer, and their profiles.
- `launch.md`: `lup-dev launch`, the room a session runs in, the settings compiled for each runtime, and the guidance.
- `trust.md`: approving the code the host runs, before it runs.
- `host.md`: the host service, how a room reaches it, the one hook, and restarts.
- `inbox.md`: lup's tools in a session, and the inbox between a session and the operator.
- `credentials.md`: the operator's credentials used on the host: git through a remote helper, git run safely on the host, and GitHub.
- `judging-writes.md`: the judge, what each write gets, and the gate.
- `conventions.md`: the reasons behind lup's code rules; `rules.md`, generated from the engine's table, gives each rule with its examples.
- `private.md`: keeping the operator's machine out of what's published.
- `library.md`: asking an agent from code.
- `dashboard.md`: where the operator works.
- `field-notes.md`: what was measured or read from a runtime's source, with its version and date.

A module in a distribution of its own has its doc in its directory:
- `packages/lup-transcripts/README.md`: `Transcripts`, every session's record kept, and read with `lup-dev transcripts`.
