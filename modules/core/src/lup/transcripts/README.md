# Transcripts

Every session's record on the machine, every project's, on both runtimes, read where the runtimes keep it, indexed with what the operator said through lup, and searched. A session reads there what the operator said and what they were answering, which is where the reasons for the work's shape are: mostly an agent does, asked to know where an idea came from and what was already proposed. It's a module of its own among lup's default modules (`Transcripts`, `module.py`).

## What it reads

- **The runtimes' records, in place** (`lup/runtimes/README.md`, *Records*): the rooms' history homes (`~/.local/share/lup/homes`, every project's), which keep their records for good, and the operator's own runtime directories (each runtime's `Records.own`), which a runtime cleans up: Claude Code deletes a record 30 days after it was last used. So the operator's own are copied into the part's data as they grow (`copied`), and read from there once the runtime has deleted them. A conversation in several homes is read from one, the original while it's there.
- **The second lup's copies** (`~/.local/share/lup/modules/transcripts`), read and never written: the only record of sessions from before the rooms kept theirs for good.
- **The second lup's ledger** (`ledger.py`): the operator's reviews, answers, messages and comments, and agents' questions and turns' ends, from a copy of its database, read again whenever it changed. A review is kept there once for each conversation it reached, so each comment is read once, from the copy that reached the conversation it's on, with the passage it quoted.
- **This lup's inbox,** through its `said` service: every item since the last read, each with what it's on.

A record is the room's to write, so it's read in a container, never on the machine itself.

## The index

One SQLite database in the part's data (`index.py`), with SQLite's full-text index over every step's text and every item's: words, calls and what they returned. It's caught up before each answer: each record from where its last read stopped, so a record that didn't change costs a `stat`, and one that grew what it added. The first catch-up reads everything. Each of the operator's words keeps the agent's last words before them, and each of the agent's whether it ended a turn.

## Reading it

`lup transcripts …`, its views, each a command printing the same blocks an agent reads:
- `search <words>`: each time all of them were said, a word matching any word it starts, the latest first, `--limit` of them (20) and how many more. The operator's words by default, typed or through lup, each under what it answered: the agent's last words before it, or the passage of the item it's on. `--by agent` searches agents' proposals (their items) and last words of each turn, `--by lup` lup's, `--by tools` calls and what they returned, `--by any` everything; `--under`, `--since` and `--until` narrow it, and `--whole` shows all of what each hit answered.
- `show <session>`: by the start of its id or its name, the operator's words, each under what they answered, through lup among them; `--at <step>` what was said around a hit, the agent's words mid-turn and calls left out unless `--whole`, which shows every step.
- `sessions`: every conversation kept, the latest first: its name, when it last moved, where it ran, and how often the operator spoke in it.

What a session is told of it is its own part's (`Telling`), since a part holding something tells nothing.
