# Sessions

Every session is started and held by lup itself (`DESIGN.md`, *Sessions*), each in a room of its own (`lup/rooms/README.md`), on Claude Code or Codex behind one interface (`lup/runtimes/`). You talk with a session in its buffer in the dashboard. A terminal takes it over and gives it back. `Sessions` is a module of the machine's own parts, which the home repository selects beside `Hosting`: `Held`, which holds every session, and `Rooms`, which makes their rooms. Its library side is the session's events (`events.py`) and what crosses between the machine, a session's holder and its room (`held.py`, `said.py`).

## Starting, and what's kept

`lup sessions start` takes a project that's running (`lup hosting open`), a runtime, a name, a worktree and the first words, and starts a session. A session is kept for good once started: its project, its runtime, lup's id for it (a UUID, its own agent's, `lup.Agent.of`) and the runtime's own, its worktree and its name. A session that's ended is still kept, and a reply starts it again with its whole conversation. `lup sessions interrupt` ends the turn under way. `lup sessions end` lets the turn finish, then ends its runtime and its room.

At most 32 sessions run at once, 16 of one repository (`Sessions.most`, `most_per_repository`). That's against a loop of spawns, not a budget.

## Holding

Something has to keep a runtime's process alive, write the operator's words into it as turns, and read what it says. Whatever does can speak to the agent as the operator, and the machine is replaced whenever the operator approves a new commit of lup. So each session has a holder: a process of its own on the operator's machine, started by the machine (`python -m lup.environment.sessions.holder start`, with the machine's own Python, so a holder is always the code of the machine that starts it), that outlives the machine. It's the machine's own code, from the commit the operator approved.

A holder listens on two sockets:
- **One in the room's own directory** (`/run/lup/session.sock` in the room). The room's first program connects to it and runs the runtime on that one connection (`lup.environment.sessions.connected`). The holder then closes the socket. Another process of the operator's can reopen a pipe through `/proc/<pid>/fd/0` and write a turn, but not a socket. Since the room's first program connects before anything else in the room runs, nothing in the room can type a turn as the operator (`docs/field-notes.md`, *A session held with no terminal*).
- **One only the machine reaches,** in its own directory in memory. There the machine tells the holder to start a turn, interrupt, end, or say where its session stands (`Order`, `Standing`).

The holder speaks the runtime's own protocol (`Holding`): Claude Code's stream-json, or Codex's `app-server`. It ends once its runtime closes the connection.

## Hooks and tools

A session's runtime runs lup's hook command at each of its hooks (`lup.environment.sessions.hook`), and lup's tool server over MCP (`lup.environment.sessions.tools`). Both run in the room from the machine's own lup, mounted read-only, and both call out through the room's socket, which vouches for the session's agent (`lup/hosting/README.md`, *Carrying*). So they behave the same whether lup holds the session or a terminal does.

The hook command reads nothing of its payload. The machine reads it with the session's runtime as one of lup's events (`hooked`) and answers what the runtime prints. A subagent's call to lup's own tools is stamped at its start with their conversation, which the tool server takes out and sends as the call's `conversation`. Every tool also has its command line, `lup <module> <tool>`, through the same socket.

## Events

A session's runtime's hooks are lup's events (`events.py`): a session started, resumed, forked, cleared or compacted (`SessionStarted`); a turn started; a call about to run (`CallStarting`), which lists the files a file tool writes; a call finished; a turn ended; a subagent started or ended; the session ended. Each carries the agent whose conversation it's of. A module's methods hear them through `@lup.on`, each imported from the package's front door (`from lup.sessions import CallFinished`), which a promise may import.

Each reaches every part of the project whose methods run at it (`@lup.on`), wherever it runs: in the project's containers, and, for a part run in the room (`Part, room=True`), in the session's own room, whose first program starts them from the worktree's own code beside the runtime (`Carrying.heard`). At a session's start, a turn's start, a call's start and a call's end, what they answer is told the agent beside the hook, with what waits for them in the inbox; at a call's start, a refusal refuses the call.

## Idle, and starting again

A sweep looks at each session running every two seconds (`swept`):
- one whose holder is gone is taken for stopped, its room stopped;
- one idle past `Sessions.idle` (an hour, about as long as the runtime's prompt cache) is ended.

## Promises

`promises.py`, through the harness, the holder and podman stood in for as each promise scripts them.
