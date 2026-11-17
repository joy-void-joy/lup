# Programs

lup's one runner of programs, which every other module's code uses: the code rules steer each process call here (`subprocess`). It's a library side alone, `lup.programs`, which `lup` re-exports under that name (`lup.programs.run`), since alone its names would read as lup's own.

```python
from lup.programs import awaited, detached, run, started

ran = run("git", "status", "--porcelain", cwd=root)
ran.text()                                    # what it printed
run("gh", "auth", "status", checked=False).status
run("uv", "tool", "install", package, shown=True)
ran = await awaited("gh", "api", "--input=-", stdin=body, within=timedelta(minutes=1))
batch = await started("git", "cat-file", "--batch")
batch.input.write(b"HEAD\n")
await batch.output.readline()
await batch.ended()
detached("uv", "run", "serve", log=log)
```

| | Its caller | Its input | What it prints and says | It ends |
|---|---|---|---|---|
| `run` → `Ran` | waits | `stdin`, or nothing | kept, apart or `merged`; or `shown` on the terminal | by itself, or killed past `within` |
| `await awaited` → `Ran` | goes on, on its event loop | `stdin`, or nothing | as `run`'s, or at most `limit`, its end `kept`, or `discarded` | by itself, or killed with its group past `within` or `limit`, or as the wait is cancelled |
| `await started` → `Running` | talks to it while it runs | a pipe, the caller's | its output a pipe, the caller's; what it says, the caller's own | once `ended` closes its input, or killed past the time `ended` gives it |
| `await spawned` → `Child` | goes on, and `waited` waits | nothing | the caller's own | by itself, or as `terminate` or `kill` ends it |
| `detached` → `Apart` | goes on, and may end before it | nothing | appended to `log` | by itself, or as `end` ends it |

A program ending with a status its caller doesn't accept raises `ProgramFailedError`, carrying how it ended (`ran`); one that can't be started raises `ProgramMissingError`, one past its time `ProgramOverdueError`, and one printing past its limit `ProgramOverflowError`, each a `ProgramError`, a `LupError`.

## Why it runs them as it does

- **A program's arguments are a list, never a line a shell reads,** so a value holding a quote, a `$` or a `;` reaches the program as written.
- **A program is started from C, as `subprocess` and asyncio do, never by forking Python:** a process whose other threads hold locks can fork into a child that never gets them back, which Python warns of, and which `filelock` refuses outright.
- **`within` is the longest a program may run.** One reading what someone else writes can wait for good: git reading a ref a room made a FIFO nothing writes waits in `open` until it's killed (`docs/field-notes.md`, *Host-side git in a repository the room writes*).
- **`awaited` kills a process group, not a program.** It reads what a program prints to its end before it answers, and that end comes only once every process holding the pipe has closed it: a child left holding one, as git leaves `ssh` for a push, would hold the call past the program's own end. So each program starts as the leader of a process group of its own, and where it's killed, the group is. A process that left the group, which the kill doesn't reach, is given up on past `letting`, its pipes left to it. `run` kills the program alone, and returns at once: `subprocess` waits for the program, not for its pipes.
- **`awaited` holds no thread,** for an event loop that goes on serving while a program runs, and kills its program where the wait is cancelled, so nothing runs on past the caller's interest in it.

## Its promises

Unlike every other promise, they start real programs, since what they promise is how the system's processes are started, fed, read, timed and killed, which nothing in the process checking them can stand in for. The harness's loop starts no process (`lup/testing/README.md`, *Time and order*), so a promise about `awaited`, `started` or `spawned` runs on an event loop of asyncio's own, in a thread of its own.

Their verdicts are as repeatable as the others': each program is a small one every room has (`sh`, `cat`, `printf`, `true`, `false`, `setsid`), and either ends as told or never ends by itself, waiting to open a named pipe nothing writes, so a time limit always fires on it whatever the machine's load. A promise waits on what a program says through another named pipe, never on a sleep, and asserts nothing of how long a call took: one that never answers is ended by the gate's limit on a check, and fails it.
