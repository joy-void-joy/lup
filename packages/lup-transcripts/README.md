# Transcripts: every session's record, kept and read

`Transcripts` keeps every session of a repository: each runtime's record of it, copied out of reach of the runtime's cleanup, mounted read-only in every room, and read with `lup-dev transcripts`. A later session reads there what the operator said and what they were answering, which is where the reasons for a design are. It's one of lup's default modules (`docs/declaration.md`, *lup's modules*).

## Keeping

- **When:** as a launch opens and once it has stopped (`TranscriptsServing.keep`, on `Launched` and `Stopped`). A runtime only adds to its records, so the copy made as a launch opens catches what an earlier launch left if it never stopped.
- **Which:** the records the launch's runtime says are the repository's sessions' (`Records.kept`), from the directories they ran in: the repository's git directory and each of its worktrees. How each runtime lays them out is in `docs/field-notes.md`, *Where each runtime keeps its sessions' records*.
- **Where:** the module's data directory for the repository, under the runtime's name, laid out as the runtime lays out its own. A file is copied where the copy is missing or differs from it in size or time, so only what was added or grew is read again.
- **Mounted** read-only in every room at its host path (`Mounted(always=True)`). A project or a person's layer that keeps it out writes `Transcripts(data=Mounted(always=False))`, and a launch then lends it with `--mount transcripts`. The guidance section `transcripts` says where the copies are, only where they're mounted.

## Reading them

`lup-dev transcripts`, the module's commands (`docs/declaration.md`, *Commands*), through each runtime's reading of its records (`Reader`, in its adapter):
- `list`: every kept session, newest first: when it started, its name and id, how many times the operator spoke, and where it ran;
- `show <session>`, chosen by its id, the start of its id or its name: the operator's words, each after what the agent last said before it, or with `--all` the whole conversation, each run of tool calls folded to a line. Where lup's inbox holds the session's exchange with the operator, which the record doesn't, the last line says how many items and the command that reads them;
- `search <words>`: each time the operator said all of them, in any case, with the first line of what they answered, or with `--whole` all of it.

The operator's words come first, since a past session is read for what they said and what they were answering.

## The conversation, live

Each agent's conversation is a view (`docs/declaration.md`, *Views and blocks*), read from the runtime's own record as it grows, not the copies, and each record read again only once it changed (`Recording`):
- `conversation <runtime> <session> [--agent <id>]`, the drawer under each agent's banner (`v`): its summary counting the steps, everything since the operator's last words open, each earlier exchange folded under their words that opened it (`e`, opening one at a time, the latest first), each run of three calls or more under one line saying how many of which (`k`), each call a line saying what it did with its input and output under it (`d`), and each item of lup's inbox the conversation sent or was sent a line where it happened, its text under it (`m`);
- `exchange <runtime> <session> [--step <n>]`, one earlier exchange, which its fold reads as it opens, so the drawer's answer stays small;
- `call <runtime> <session> <id>`, one call read whole, as its fold opens.

The layout is `environment/conversation.py`: pure, from the record's steps and the items the core keeps (`self.exchanges`), each block's id naming what it shows so it stays from one answer to the next. The module declares its fold kinds and tones (`folds`, `tones`).

## Layout

The module is a distribution of its own, `lup-transcripts`, in lup's uv workspace:
- **`src/lup_transcripts/`, its library side:** what code calling agents may import: the module's root error alone, `LupTranscriptsError`, which every error it raises descends from.
- **`src/lup_transcripts/environment/`, its environment side:** the module, what it serves (its hooks, commands and views), the conversation's layout and its guidance section, all of which import `lup_dev`, and write `lup`'s front door (`@lup.on`, `@lup.view`) as a project's module does. Two import contracts of the module's own, in the root `pyproject.toml`, hold it apart: the library side never imports `lup_dev` or `lup_dashboard`, and only `lup_dev` imports the environment side.
- **The extra `lup-transcripts[environment]`** brings `lup-dev`, so code using the library side alone doesn't pull in the environment. `lup-dev` depends on `lup-transcripts` itself, without the extra, since `Transcripts` is one of its default modules and `lup-dev` is the environment the extra would bring. The only cycle goes through the extra. Trust installs it with the `lup-dev` it approves, as a workspace package `lup-dev` needs (`docs/trust.md`, *The host zone*).
- **`tests/`:** run by the gate with every package's tests (`packages/*/tests`). The module's commands and views are tested here; how a module's commands reach the command line is `lup-dev`'s (`lup_dev/commanding.py`), tested there.
