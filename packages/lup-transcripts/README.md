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
- `conversation <runtime> <session> [--agent <id>]`, the drawer under each agent's banner (`v`): its summary counting the steps and those new to the operator (`conversation · 312 steps · 12 new`), what they've read folded under one line (`▸ 41 earlier steps`) and everything after it open, but for at most the agent's last 20 words with what follows them, what came before those folded too under one line saying how many steps and items and how many of them are new (`▸ 412 earlier steps, 3 items, 30 new`), each earlier exchange folded under their words that opened it (`e`, opening one at a time, the latest first), each run of three calls or more under one line saying how many of which (`k`), each call a line saying what it did with its input and output under it (`d`), and each item of lup's inbox the conversation sent or was sent a line where it happened, its text under it (`m`);
- `exchange <runtime> <session> [--step <n>] [--through <n>] [--until-last <n>]`, one earlier exchange, or what the operator had read of the latest, up to a step, or what came in one before the agent's last words that many, which its fold reads as it opens, kept the same way, so each fold opened brings in 20 more of the agent's words and the drawer's answer stays small however long a session driven from the dashboard runs; answered again, shown, as the drawer is;
- `call <runtime> <session> <id>`, one call read whole, as its fold opens, and answered again while it's open and shown as a call of the agent's finishes, so one still running shows what it returned once it has.

The layout is `environment/conversation.py`: pure, from the record's steps and the items the core keeps (`self.exchanges`), each block's id naming what it shows so it stays from one answer to the next. Each item comes with its line made by the core, for this conversation, in its kind's own words and the core's around them (`docs/inbox.md`, *A conversation's items in its view*), so the module names no kind of item: it places the line, in its tone, sent or received, its text folded under it. Each conversation a line names is said by its path, else by its runtime's ids, in a span referring to it by those ids (`Span.conversation`), which a rename never changes. The module declares its fold kinds and tones (`folds`, `tones`).

**What the operator has read** is the drawer's review mark (`docs/dashboard.md`, *Review marks*), read through the module's context (`self.marks`), keyed by the conversation's runtime's ids, which a rename never changes, or their own last words typed to it, whichever is later: words typed in its terminal count as reading what came before them. Space `d` on the drawer's line marks it read up to its last step shown, the drawer offering it while anything came after (`ReviewMarks.offer`), applied as the reply is sent. What they've read folds under one line, the fold named by the last step it holds (`exchange 12 through 40`), so it stays as the agent speaks; the latest exchange is split at the mark, the earlier ones read whole. Each view that read the mark is answered again as it moves. A command in a room reads the same mark, so an agent's text form folds where the operator's page does.

**How many of the agent's words stay open** is its fold kind of what came earlier's setting (`EARLIER_KIND.keeps_open`, 20; `lup.FoldKind.keeps_open`), which only the agent's words count, never its calls, folded anyway. A person's layer keeps more or fewer, or everything open with `None`:

```python
from lup_dev import Modules, Project
from lup_dev.declaration.kinds import Folds
from lup_transcripts.environment.conversation import EARLIER_KIND
from lup_transcripts.environment.module import Transcripts

project = Project(
    modules=Modules().edit(
        Transcripts(
            folds=Folds().replace(
                "earlier", EARLIER_KIND.model_copy(update={"keeps_open": 40})
            )
        )
    )
)
```

## Layout

The module is a distribution of its own, `lup-transcripts`, in lup's uv workspace:
- **`src/lup_transcripts/`, its library side:** what code calling agents may import: the module's root error alone, `LupTranscriptsError`, which every error it raises descends from.
- **`src/lup_transcripts/environment/`, its environment side:** the module, what it serves (its hooks, commands and views), the conversation's layout and its guidance section, all of which import `lup_dev`, and write `lup`'s front door (`@lup.on`, `@lup.view`) as a project's module does. Two import contracts of the module's own, in the root `pyproject.toml`, hold it apart: the library side never imports `lup_dev` or `lup_dashboard`, and only `lup_dev` imports the environment side.
- **The extra `lup-transcripts[environment]`** brings `lup-dev`, so code using the library side alone doesn't pull in the environment. `lup-dev` depends on `lup-transcripts` itself, without the extra, since `Transcripts` is one of its default modules and `lup-dev` is the environment the extra would bring. The only cycle goes through the extra. Trust installs it with the `lup-dev` it approves, as a workspace package `lup-dev` needs (`docs/trust.md`, *The host zone*).
- **`tests/`:** run by the gate with every package's tests (`packages/*/tests`). The module's commands and views are tested here; how a module's commands reach the command line is `lup-dev`'s (`lup_dev/commanding.py`), tested there.
