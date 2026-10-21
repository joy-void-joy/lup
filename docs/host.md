# The host service

One program per user on the operator's machine, outside every room, which rooms call for what only the host can do (`host/service.py`): the judge for each hook (`docs/judging-writes.md`), lup's tools and the inbox (`docs/inbox.md`), git and GitHub with the operator's credentials, the clipboard, and the dashboard, which it runs as its child (`docs/dashboard.md`).

## Using it

- **It starts on demand,** detached, from the first launch or command that finds none answering, and runs until it's stopped. It holds a lock for its whole life, so a second refuses.
- **`lup-dev host`** runs it in the foreground, to watch it, and **`lup-dev host stop`** stops it. A launch outlives a stop (*Restarts and the sweep*).
- **`lup-dev sessions`** lists the launches it serves, each with its conversations as a tree and its container.
- **What it prints,** started in the background, is appended to `service.log` in lup's state, which a client names when the service doesn't answer within 10 seconds; in the foreground, it prints to the terminal.

## How a room reaches it

Each launch has a socket directory of its own, mode 0700, mounted into its room at `/run/lup`. The service knows which launch speaks by the socket it hears on: under `--userns=keep-id` a room's processes have the operator's uid, so only the socket tells a room from the operator. One socket for every room would have each request name its launch, which the room would then say of itself, and HTTP on localhost would be reachable by every process on the machine.
- **`hook.sock`, the one hook.** Every hook of every runtime is one command, which pipes the runtime's payload unchanged to the socket with `socat` and prints the answer, so nothing in the room parses it (`piped`, `launch/session.py`; *The one hook*).
- **`mcp.sock`, lup's tool server.** In the room, the runtime's stdio server is lup's bridge (`packages/lup/src/lup/sessions/bridge.py`), on the room's Python and the standard library alone, carrying each line across. Each connection is one MCP session, kept while it's open so what's pushed to the session goes through it (`Pushes`, `host/pushes.py`). The server answers a probe for MCP's 2026-07-28 revision "method not found", so the runtime opens on the handshake: on that revision a server can send nothing unasked, which a push and the bridge's `list_changed` after a restart both need (`lup.tools.serving`; `docs/field-notes.md`, *Channels*).
- **`request.sock`, the room's requests:** one typed request per connection from the room's programs: git's remote helper, the gate asking an issue's state, the clipboard, and modules' handlers. Its routes are apart from the control socket's, so a room never reaches a control kind, such as answering the inbox: the first lup's sessions approved their own questions by writing to a store they could reach.
- **`messages.sock`,** Claude Code's own messaging socket, through which the service rings an idle session's doorbell where nothing can be pushed to it (`docs/inbox.md`, *How an agent is told*).

On the host alone:
- **The control socket.** One JSON request per connection, a pydantic model told apart by its `kind`, and one reply (`host/protocol.py`). Modules register the handlers for their own kinds, so a kind is added without editing the service. What the service can't carry out is replied as `Refused`, saying why.
- **Watching.** On the watch socket, a request is answered at once, then again each time its reply changes, with nothing polled (`host/watch.py`); the dashboard watches what the operator's commands fetch. A watch is asked again when the service answers a request or a hook, or writes an item of the inbox.

## The one hook

| The hook | Claude Code | Codex |
|---|---|---|
| The service's answer | the decision it holds | the decision it holds |
| The service unreachable, status 1 | a non-blocking error in the transcript; the call goes ahead | the run marked failed; the call goes on |
| The launch's judge can't answer | a file tool's write is denied, saying why; at `PostToolUse`, the agent is told beside the call's result; any other hook warns the operator | at `PostToolUse`, the agent is told beside the call's result; any other hook warns the operator |

- **Which hooks the judge reads** is each adapter's word (`heard`): every one, but on Claude Code a call's start and finish to lup's own tools or to a tool that only reads (`READING`, `adapters/claude.py`). The service answers the rest itself, in about 4.5 ms; one the judge reads where nothing changed takes 8 to 21 ms, the judgement and a hop to the launch's process (`docs/field-notes.md`, *A hook the judge doesn't read, and one it does*).
- **A hook the judge can't answer goes on,** since the judge steers and doesn't guard. Where the service is up, it refuses only a file tool's write on Claude Code, since let through unjudged it would land unseen; where the service can't be reached, even that write goes ahead, with the runtime's error shown.
- **`socat` waits 25 hours** for the answer, above a hold's day, and the hook never ends with status 2, which would block the call on both runtimes.

## Who's calling

Within a launch, each conversation has an id of lup's own, minted the first time a hook names it and kept with the launch across restarts (`Conversations`, `host/courier.py`), so lup's tools and calls name a conversation by lup's id, never a runtime's: the first lup, wired to each runtime's own, found they didn't stay uniform. The hook on a call to one of lup's tools rewrites its input to carry `caller` and `call`, the runtime's id for the call, which the server takes out before the tool sees its arguments (`stamp`, `host/rooms.py`). `call` anchors the item the call makes in the conversation's record. A process in the room could write another conversation's id into a call, but only within its own launch.

## Each launch's judge and modules

- **Each launch is judged by its repository's own approved copy** (`docs/trust.md`), in a process of the launch's own, `<copy>/bin/lup-dev worker`, started when the launch opens and stopped when it ends (`host/workers.py`, `lup_dev/worker.py`). It stays running and answers each hook the judge reads as `lup-dev hook <runtime>` would, so a hook costs the judgement alone, where a process started for each hook would spend about 0.7 s starting Python and importing `lup-dev` before judging anything.
- **The same process runs the launch's modules:** their tools, their answers to the room's requests, and their hooks at lup's moments (`docs/declaration.md`, *What a module serves a launch*). Where they can't be loaded, it says why in the service's output and answers the judge's hooks alone, as the judge has a stand-in for a declaration that can't load.
- **Hooks at once.** Each hook runs in a thread of its own, never a pool's, so hooks that parallel calls and subagents fire together are judged together, and a hold waiting a day for the operator delays no other. What judging keeps between hooks is on disk under `filelock`'s locks, which exclude a thread as they do a process; what it reaches, the engine, ruff, the clock and the inbox, holds no state and is made once for the process.
- **An approval switches cleanly.** The launch's judge is its repository's command, a link to the copy approved last (`docs/trust.md`, *Each repository's own judge*), which the service follows at each request. Where it names another copy than the process runs, a process of that copy starts and answers from then on, and the one before finishes what it was asked, a hold among it, then ends: the launch is judged and served by the approved code from its next hook, with no relaunch, and no hook meets a copy half installed. The tools and the kinds of request its session was offered stay those of the copy it opened with: one the new copy dropped is answered as one no module serves.
- **A failure.** A process that dies is started again at the next request, and a hook it was answering gets the runtime's answer for a judge that couldn't (*The one hook*), with why.
- **The programs it runs for a room are spawned through asyncio** and awaited on its event loop: git, `gh`, the clipboard's programs and the launches' processes. So a hold in a launch's process holds a thread there and nothing of the service's. podman, renaming a container or sweeping, runs in a thread. None is forked through `sh`, which runs Python in the child before the program starts and can deadlock a process with threads (#23).

**Why the judge is on the host:** not to guard it, since the judge steers. It asks a warm engine per worktree, a pyright process shared with the operator's own gate runs, where a cold one in each room would make the first edit wait for the whole project to type-check. The copy the operator approved is the one that judges, where in the room a branch reshaping the judge would judge its own edits. And holds wait for the operator's answer, which comes from the host.

## Restarts and the sweep

- **A launch outlives a restart of the service.** Each launch is recorded beside its sockets, and a service started after one stopped binds them again in the directory the room mounted, and brings the room's programs up to its own copy. The hook goes on at the next call. Neither runtime starts a stdio server again, so the bridge keeps the runtime's side open across the gap: a call made meanwhile waits up to a minute; one that was being answered gets an error saying its answer is lost and it may have been carried out; and once the service is back, the bridge replays the runtime's MCP `initialize` and tells it to list the tools again.
- **A launch whose launcher died is swept.** Its launcher holds a lock the OS frees when it dies, and the sweep ends each launch whose lock it can take and whose container podman no longer has. It takes both, since either alone ends a live launch: a container appears moments after its registration, and a launcher killed with its terminal can leave its room running on. The sweep runs before each launch registers, and every 30 seconds beside the service.
- **A copy nothing runs is removed.** The sweep beside the service also removes each repository's approved copy that its link doesn't name and no launch's process runs, never one being installed (`lup_dev/copies.py`). It chooses them on the service's event loop, beside the processes starting, so it never chooses a copy as one starts from it.
