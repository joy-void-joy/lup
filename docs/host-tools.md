# lup's tools in a launched session: the inbox, and the operator's credentials on the host

**One sentence:** a launched session gets lup's tools from an MCP server the host service runs for its launch, so the agent can ask and tell the operator through an inbox they answer with `lup-dev inbox`, and can push, fetch and reach GitHub through the host with the operator's credentials, within limits the project's declaration sets.

This is the second of #56's four pieces (`docs/launch.md`): lup's MCP server in a launched session, the inbox and `lup inbox`, and the credential actions (git through a remote helper, GitHub through lup's tools). Until it lands, a launched session can't push or reach GitHub, so lup's own sessions move onto launch with it (*lup's own sessions move onto launch*). It builds on piece 1 as landed: the room, the compiled settings, the one hook and the host service (`docs/launch.md`). It takes from `DESIGN.md`'s build step 6 the host service's inbox and the tools between an agent and the operator, but not `propose` or `spawn`.

The facts it rests on were read or measured for it on 2026-10-13: Claude Code's docs and its 2.1.296 binary (a byte search, no model called), Codex's source at `rust-v0.162.1`, git 2.56.0's man pages and a logging remote helper run on the host and in the room's image, and the first lup's history. Each is cited where it's used; they go into `docs/field-notes.md` with the first branch (*Building it*). A choice the operator hasn't confirmed is marked **(leaning)**.

What it leaves to other pieces:
- **`propose` and holds** (piece 3), which replace the drafts flow (`docs/review-flow.md`), the checkpoint and its mail; the judge's own tellings then become inbox items. #66 (another session's writes under an open hold) is piece 3's, decided with holds; the inbox is how the session whose edit a decline puts back would be told.
- **The dependency guard** (piece 4).
- **Spawn,** and with it messages between agents, the roster, and the native `Agent` denied by default.
- **The dashboard,** whose inbox view `lup-dev inbox` is the command-line counterpart of; reminders and follow-ups; notification channels beyond the desktop's.
- **Asking the operator for an action beyond the limits:** refused in this piece, saying why; asking is a proposal, piece 3's.
- **Transcripts** (#65): lup's own copy of each launched session's record is a neighbour. It files each copy under the same identity the inbox keys a party on (a session, and a conversation in it), so the two agree from the start.
- **The clipboard,** devices and a browser in the room, budgets and `accounts`, as `docs/launch.md` leaves them.

## Decisions for the operator

Each is answerable "leaning", "undecided" or "leave open"; the section holding it says more.

1. **The tools a launched session gets** (*lup's tools*): `report`, `note`, `ask`, `message`, `wait`, and five GitHub tools; not `propose` (piece 3) or `spawn`. **Lean: these.** They overlap: `report` and `note` say what `message` says with the kind `problem` or `note` (`report` also stops the work). The alternative is `message` arriving with spawn, when there's a party besides the operator to address, so each thing has one way to be said here. `message`'s kinds leave out `question`, which is `ask`'s.
2. **Always loaded, and results as text** (*lup's tools*): Claude Code's `alwaysLoad`, Codex's `omit_tools_from = ["deferred"]`; each result as `content`, never `structuredContent`. **Lean: yes.**
3. **The server runs in the host service, on a socket per launch** (*The server*): `mcp.sock` in the launch's socket directory, bridged in the room by `socat` on Claude Code and by Codex's own `codex stdio-to-uds`. A service restart stops lup's tools in running sessions until `/mcp` reconnects (Claude Code) or the session is resumed in a launch of its own (Codex); the hook goes on delivering meanwhile. **Lean: yes.** Alternative for Codex: `socat` too, since `stdio-to-uds` is marked "Internal" in its help and a launch fetches the latest CLI.
4. **A third socket, `request.sock`, for the room's programs** (*The room's requests*), with its own routes, so a room never reaches the control socket's kinds. **Lean: yes.**
5. **Who's calling is read from each call's `_meta`** (*Who's calling*): each conversation, a session's main one or a subagent's, is a party with its own inbox, and an item for a conversation that has ended goes to its session's main conversation. **Lean: yes.**
6. **Claude Code hooks every call and its turn's ends** (*How an agent is told*), and the service answers what the judge doesn't read without starting the judge. **Lean: yes.**
7. **The inbox lives in the host service,** durable in lup's state and never mounted, its parties keyed by session rather than by launch, so a resumed session finds what waited for it (*Parties and items*). **Lean: yes.**
8. **How an agent is told** (*How an agent is told*): at its next call, at its turn's end (holding it once), by `wait`, and when it's idle, on Claude Code through the session's own messaging socket; nothing reaches an idle Codex session, a declared gap. This answers `DESIGN.md`'s open question 7 for this piece. **Lean: yes.**
9. **The operator's face is `lup-dev inbox`, with desktop notices** (*The operator's face*); the dashboard later, and no bridge to the first lup's dashboard. **Lean: yes.**
10. **git through `git-remote-lup`** (*git through a remote helper*): `push` and `fetch`, run on the host by object id to the remote's own URL, the room's git configuration from `GIT_CONFIG_GLOBAL`. The helper runs on the room's bare Python, so where the standard library can't follow lup's conventions (running git without `sh`, a push's refspec read by hand) it takes an `ignore` the operator reviews. **Lean: yes.** The alternative for the helper: excluded from lup's rules, as the bridge's hooks are.
11. **The limits are a `credentials` part of `Core`** (*What the declaration allows*): the actions a selection, the protected refs a selection; by default no force push, no deletion, and no push to `main` or a tag; an action beyond them refused, saying why. They reach the host with the launch's registration. **Lean: yes.**
12. **GitHub through `gh` on the host** (*GitHub through `gh`*), the repository named once from its own remote, never from the worktree. **Lean: yes.**
13. **Where the code goes** (*Modules and public API*): serving tools over one MCP connection is the library's; the inbox, GitHub and git are three subsystems of `lup_dev`, just above `host`. **Lean: yes.**
14. **Trust's question stays in the terminal, summary first** (*Trust on launch: the summary first*). **Lean: in the terminal this piece.** This changes `docs/launch.md` (*Trust on launch*: "In the terminal until piece 2 brings the inbox") and `DESIGN.md` (*Policy*: "in the terminal until the inbox, then wherever the inbox is answered"). The alternative: an inbox item too, now.
15. **lup's own sessions move onto launch once this lands,** with the protected-path change the operator makes (*lup's own sessions move onto launch*). **Lean: yes.**

## lup's tools

### What a launched session gets

| Tool | Input | What it does | The item it makes |
|---|---|---|---|
| `report` | `problem` | Says what's wrong when the work can't go on; its answer tells the agent to end its turn | a message to the operator, kind `problem` |
| `note` | `remark` | Tells the operator an assumption, a doubt or a counterargument, and carries on | a message, kind `note` |
| `ask` | `question`, `decisions` (each with the agent's lean), `wait` | Asks the operator. With `wait`, the call holds until they answer and returns the answer; without, it returns at once and the answer reaches the agent at a later call | a question |
| `message` | `kind` (`disagreement`, `note`, `problem`), `text` | Tells the operator something; never holds, and nothing comes back | a message of that kind |
| `wait` | none | Holds until something reaches the agent's inbox, and returns all of it | none |
| `read_issue` | `number` | An issue or pull request of this repository, with its comments, and a pull request's checks | none |
| `find_issues` | `query`, `state` | Searches this repository's issues and pull requests | none |
| `file_issue` | `title`, `body` | Opens an issue | none |
| `comment` | `number`, `body` | Comments on an issue or pull request | none |
| `draft_pull_request` | `branch`, `title`, `body` | Opens a draft pull request from a pushed branch into the integration branch | none |

- **`report` and `note` are the library's speaking tools** (`lup.tools.speaking`): the same names and input models (`Problem`, `Remark`), so an agent's habit carries between an ask from code and a launched session. In a launched session whoever asked is the operator, so each lands in their inbox (`DESIGN.md`, *Sessions*: "telling them something is a message with a `kind`"). Their functions are the environment's, putting the item in the inbox; their descriptions say where it goes. `report` keeps its meaning: the agent stops and says why, and its answer tells it the report is with the operator and to end its turn.
- **`ask` takes numbered decisions,** each with the agent's lean, which the operator answers "leaning", "undecided" or "leave open" with a comment (`DESIGN.md`, *The dashboard*), or a plain question answered in words. A question's answer is told to the conversation that asked, once.
- **`wait` takes no time limit (leaning):** the runtime's limit on a call bounds it (*Holding a call*), and no loop re-enters a wait to keep the cache warm (`docs/graveyard.md`). On a Codex model in code mode, Codex has a `wait` tool of its own, which polls a running cell (`docs/library.md`, *No tools but lup's own*); whether a model tells the two apart is a check owed, and `wait_inbox` the name if it doesn't.
- **The GitHub tools** act on this repository alone (*GitHub through `gh`*). There's no merge tool, and none closes or edits an issue **(leaning)**: closing one is the operator's judgement, which a comment can ask for. `draft_pull_request` targets the integration branch, `LUP_INTEGRATION_BRANCH` (`settings.py`, `dev` by default), as trust on launch reads it.
- **Not here:** `propose` (piece 3) and `spawn` (later).

### Loaded, short, and read the same on both runtimes

- **Always loaded (leaning).** Both runtimes defer MCP tools to tool search by default: Claude Code loads only names and server instructions (its `mcp` docs, *Scale with MCP tool search*), and Codex leaves them out of the first tool list where the model supports tool search (`core/src/tools/spec_plan.rs`). The first lup found deferred tools made agents conclude a tool didn't exist, and moved to `alwaysLoad: true` (its `8827c0442`, `8f2ecbe10`); aib found "deferred tool schemas made the agent guess search terms" (`docs/field-notes.md`, *From the downstream projects*). So Claude Code's entry gets `alwaysLoad: true`, and Codex's `omit_tools_from = ["deferred"]`.
- **Short descriptions,** since loaded tools cost context in every request: one or two sentences each, the input fields described in a few words. The first lup's 14 coordination tools carried about 10 KB of descriptions alone.
- **Results as `content` only,** as the library's server answers today (`served`, `adapters/claude/runtime.py`). Codex shows the model only `structuredContent` where a result has it, dropping the content blocks (`protocol/src/models.rs`); Claude Code reads `content`. A result with both would read differently on the two runtimes.
- **A large result** is the runtime's to keep whole: Claude Code saves one past `MAX_MCP_OUTPUT_TOKENS` (25,000 by default) to a file and gives the path; Codex cuts one past about 10,000 bytes by default (`utils/output-truncation`) unless a tool's `output_token_limit` is raised. An issue thread can pass that, so `read_issue`'s limit is raised on Codex's entry **(leaning)**, and `DESIGN.md`'s large results to a file arrive with the tools slice.

### Who's calling

The launch is the socket's: the service hears a call on the launch's own `mcp.sock`, which nothing in the room names (`docs/launch.md`, *On the host: the service*). Within the launch, each call's `_meta` says which conversation is calling **(leaning)**:
- **Codex** sends `callId`, `threadId` and `sessionId` with every `tools/call`, with turn metadata naming a subagent's parent thread (`core/src/mcp_tool_call.rs`); the thread is the conversation, and the ids are the ones its hooks carry as `tool_use_id`, `agent_id` and `session_id` (`core/src/hook_runtime.rs`).
- **Claude Code** sends `"claudecode/toolUseId"` to every server (in the 2.1.296 binary: `...he&&{"claudecode/toolUseId":he}...`), and its hooks carry that id with `session_id` and, in a subagent, `agent_id`. Its `PreToolUse` hook runs before the call reaches the server, so the service records each call's conversation from the hook and finds it again by the call's id.
- `docs/field-notes.md` (*MCP servers, from the runtimes' docs*) says a Claude Code server "learns only `CLAUDE_PROJECT_DIR`, not the session or the subagent", from the docs, which don't mention `_meta`; it's corrected once the live check below confirms the id.
- **A call whose conversation can't be read** (the field missing, or a call id no hook named) is taken as the launch's main conversation, and the service's log says so.
- A process in the room could write another conversation's ids into `_meta`. It stays within its own launch, so it can only speak as another conversation of the same session.

## The server: in the host service, reached through a socket

- **A second socket per launch, `mcp.sock`,** in the launch's socket directory beside `hook.sock`, so the room sees it at `/run/lup/mcp.sock` through the directory it already mounts. Each connection is one MCP session, served by `mcp`'s low-level `Server`, as the library's server is built today, over the connection's own streams (`Server.run(read, write, …)` serves "a single connection over the given streams", `mcp` 2.3.0).
- **In the room, the stdio server is a bridge:**
  - **Claude Code:** `--mcp-config <launch>/mcp.json` with `--strict-mcp-config`, the entry a stdio server running `socat STDIO UNIX-CONNECT:/run/lup/mcp.sock` (socat is in every room, for the hook). `--strict-mcp-config` is "Only use MCP servers from `--mcp-config`, ignoring all other MCP configurations" (its `cli-reference`), managed ones included (its `managed-mcp` docs); the room loads none of the operator's today anyway, since its `~/.claude.json` is lup's and `--setting-sources user` drops `.mcp.json`.
  - **Codex:** the bundled `codex stdio-to-uds /run/lup/mcp.sock` ("Internal: relay stdio to a Unix domain socket", its help in 0.162.1), the CLI's own program as `command`, given as `mcp_servers.lup` in the same `-c` inline table that turns off each of the operator's servers: a later `-c` override of the same path replaces the earlier (`config/src/overrides.rs`), so the two can't be separate overrides. An operator's own server named `lup` is replaced by lup's.
  - **Set aside:** HTTP on the host's loopback, which every process on the machine and every room could reach, and which couldn't tell rooms apart (`docs/launch.md`, *On the host: the service*); a server process of lup's in the room, which would hold nothing the host has (the inbox, the credentials) and would need the host anyway.
- **Approval:** none asked. Claude Code under `bypassPermissions` prompts for nothing but a tool marked as requiring interaction (its `mcp` docs); Codex skips its prompt under approval `never` with full access (`codex-mcp/src/mcp/mod.rs`), which is the launch's `--dangerously-bypass-approvals-and-sandbox`, and the entry also says `default_tools_approval_mode = "approve"`.
- **Restarts.** A restart of the host service closes every `mcp.sock` connection, which ends the bridge, and neither runtime starts a stdio server again: Claude Code's "stdio servers are never reconnected automatically" (its `mcp` docs, *Automatic reconnection*), though `/mcp` reconnects one by hand; Codex reconnects only a server that failed to start, and then answers "MCP server 'lup' is not connected" (`codex-mcp/src/connection_manager.rs`, read, not probed). So lup's tools stop in every running session until `/mcp` on Claude Code, or until the session is resumed in a launch of its own on Codex. The hook isn't touched (a connection per call), so items go on being told. The service restarts when the operator approves a new copy on lup's own repository (`docs/launch.md`, *Trust on launch*), and on `lup-dev host stop`. A call held across a restart ends with an error; its item stays waiting. Set aside: a bridge of lup's own in the room that reconnects and replays MCP's handshake, a program speaking MCP in every room, with a held call still ending with its connection.

## The room's requests: `request.sock`

- **A third socket per launch,** for the room's programs rather than the agent's tools: one JSON request per connection, a pydantic model told apart by `kind`, and one JSON reply, as the control socket takes them. The service attaches the launch, which it knows by the socket, before a module's handler sees the request.
- **Its own routes.** A module registers a `RoomHandler`, answering a request with the launch it came from, through `RoomRoute.to(handler)`, apart from the control socket's `Handler`s. So a room never reaches a control kind: registering or ending a launch, stopping the service, or answering an inbox question, which the first lup's sessions did by writing its store, after which answers moved to a host store mounted read-only (its `281465e21`).
- **Its first users:** the git remote helper (*git through a remote helper*) and the gate's issue states (*The gate in a room*).
- **Set aside:** one socket for both, which would carry an MCP stream and one-shot requests on the same path, telling them apart by their first bytes.

## The inbox

The core's inbox (`DESIGN.md`, *Sessions*: "every party has one, the operator and each agent"), in the host service.

### Parties and items

- **Parties:** the operator, and each conversation of each session: a session's main conversation, or one of its subagents. A conversation is keyed by its runtime, its session's id and its own, within a repository, rather than by the launch it runs in **(leaning)**: `lup-dev launch claude --resume <id>` continues a session in a new launch, and what waited for it reaches it there. The service knows which launch each session runs in from its `session-started` hook. Whether each runtime keeps a session's id on resume is a check owed.
- **An item** has a number (one sequence per user, so the operator types `lup-dev inbox answer 12`), a reason, a sender and a recipient, its text, when it was made (through `lup_dev.clock`), and its state: waiting, told (when, and how), answered, or done. The reasons in this piece: a message, with its kind; a question, with its decisions; an answer. Proposals, workers' results, reminders and timers join them in later pieces (`DESIGN.md`, *Sessions*).
- **An item for a conversation that has ended** goes to its session's main conversation, saying whose it was **(leaning)**: a subagent that asked without waiting is usually gone by the time the operator answers. A conversation ends at its `conversation-ended` hook. A subagent resumed later finds nothing waiting; the alternative, keeping it for a conversation that may never call again, leaves the answer unread.
- **Kept in lup's state,** `$XDG_STATE_HOME/lup/inbox/`, one JSON file per item, each written whole (`stored.py`, `write_model`). The service is the only writer, on its event loop. **Never mounted into a room:** the first lup's sessions approved their own questions by appending to the relay log they could write. Set aside: one log folded on every read, the first lup's first store ("597 KB of touches and sixteen rows for two live sessions", its `docs/coordination.md`), whose trimming once deleted 121 messages (its `4d1f08f61`). Items are kept once told or answered; clearing old ones goes with lup's cleanup (`DESIGN.md`, *Footprint and cleanup*).

### How an agent is told

"Messages are received at the next tool call, through the one hook, or with a blocking wait. Each answer is told once, never again" (`DESIGN.md`, *Sessions*). Every item waiting for a conversation is told together, oldest first, by whichever of these comes first:
- **At its next call.** The `call-started` hook's answer carries them as `additionalContext`: Claude Code puts it into the conversation as a system reminder the model reads on its next request (its `hooks` docs, *Add context for Claude*); Codex collects a `PreToolUse` answer's `additionalContext` for the model, unless the answer is one it refuses, such as a plain `allow` (`hooks/src/events/pre_tool_use.rs` at `rust-v0.162.1`), owed live. Where the judge answers the same hook, the items are added to its answer.
- **At its turn's end,** where some are still waiting: the `turn-ended` or `conversation-ended` hook holds the end once, `decision: "block"` with the items as the reason, which keeps the conversation going on both runtimes (Claude Code's `hooks` docs, *Stop decision control*; Codex's, `docs/launch.md`, *The one hook*). The checkpoint's mail already holds Codex's turn's end this way.
- **When it calls `wait`,** whose result is the items.
- **When its session starts or resumes,** in the `session-started` hook's answer.
- **When it's idle,** between its turn's end and its next hook:
  - **Claude Code:** through the session's own messaging socket, put in the launch's socket directory with `--messaging-socket-path /run/lup/messages.sock` (in the 2.1.296 binary's help: "Cross-session messaging server path"), so the host reaches it at the same file. "When the receiving session is idle, Claude Code starts a new turn with the message" (its `cross-session-messaging` docs, *Message delivery*); a session that bypasses permission prompts, as a launch does, holds each incoming message for approval unless `crossSessionInbound` is `"accept"`, which the launch's settings set. The frame beyond the optional auth line is undocumented; the first lup measured one on 2.1.278 to 2.1.285 (its `coordination/wake.py`, `195ff73f3`). Owed live on 2.1.296. With `accept`, the operator's other Claude Code sessions can start a turn in the room too; they're theirs.
  - **Codex:** nothing reaches an idle session, a declared gap with its evidence: unprompted notifications from a server are only logged (`codex-mcp/src/logging_client_handler.rs`), and the app-server's `turn/start` runs inside the terminal's own process under `--no-daemon`. The item waits for the session's next call; the operator typing anything in its terminal starts one.
  - Set aside on Claude Code: its channels (a research preview, registered only through an allowed plugin or `--dangerously-load-development-channels`, whose confirmation screen is interactive), and an `asyncRewake` hook, a process held in the room per session to wake it.
  - Claude Code runs no `Stop` hook for a turn the operator interrupts ("Does not run if the stoppage occurred due to a user interrupt", its `hooks` docs), so after an interrupt the service doesn't know the session is idle, and an item waits for the next call.
- **Hooking every call on Claude Code.** Its launched hooks are `SessionStart` and `PreToolUse` on `Edit` and `Write` today; delivering at the next call needs `PreToolUse` on every call, and the turn's ends need `Stop` and `SubagentStop`. The service answers a hook the judge doesn't read (any call but the file tools' writes, and the turn's ends on Claude Code, where the room has no checkpoint) itself, without starting the judge's process: what the runtime's adapter reads of the payload says which (*Modules and public API*, the `Courier`). Such a hook costs a `socat` process in the room and a round trip on a Unix socket, measured before landing; the first lup's guard in the same place took 7.85 ms against its dispatcher's 107 ms (its `17321798b`). Codex already hooks every call, each answered by the judge.

**Told once.** An item is told when it's written into a hook's answer, a held call's result or the messaging socket, and never again. Three cases where that write might not reach the model:
- **Too long for a hook.** Claude Code caps a hook's `additionalContext` at 10,000 characters, past which it saves the text to a file with a 2,000-character preview, and "doesn't ask Claude to read the file" (its `hooks` docs); Codex spills past its `additionalContextLimit`, 2,500 tokens by default. So an item past its runtime's cap is announced in the hook (who sent it, its size) with a line saying `wait` returns it whole, and stays waiting until then **(leaning)**. Nothing is cut.
- **A held call whose turn ended while it held.** On Codex in code mode a held call is a pending cell, and the model may end its turn: seen live, "ended its turn after 7 min 49 s, the hook still waiting" (`docs/field-notes.md`, *Launch, live*). Where the service has seen the conversation's turn end while a call of its held, the answer isn't counted told by that call: the call returns a line saying the answer reaches the agent at its next call, and the item is told there **(leaning)**.
- **A held call abandoned with Esc.** Codex never sends `notifications/cancelled` (rmcp's `service.rs`, which Codex's timer doesn't use); Claude Code may (the string is in its binary), unverified. Where it does, the service drops the call and the item stays waiting. Where it doesn't, an answer written into a call nobody reads is the gap, said in that runtime's adapter once the live check settles it.

**Batching and not talking over the operator** (`DESIGN.md`, *Sessions*): in this piece every item an agent receives comes from the operator's own act (an answer, a message they send), so nothing needs holding back; a burst is told together.

### Holding a call

`ask` with `wait`, and `wait`, hold their MCP call until something arrives. Each runtime's limit on a call is set above a hold's day, 25 hours, as the hook's is:
- **Claude Code:** `"timeout": 90000000` (milliseconds) on the entry. Without it, a stdio call with no response or progress for 30 minutes aborts; the server's `timeout`, at least 1,000 ms, raises that idle limit with it, and the wall-clock limit is the same `timeout` (the 2.1.296 binary, as its `mcp` and `env-vars` docs describe). `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`, set since piece 1, keeps a held call from moving to the background after two minutes.
- **Codex:** `tool_timeout_sec = 90000` on the entry; its default is 300 s, seconds as a float with no cap, and progress doesn't extend it (`config/src/mcp_types.rs`, `codex-mcp/src/logging_client_handler.rs`). In code mode the cell yields after 30 s and the model may end its turn (above), so on those models a held call waits for the operator but the agent may not.
- A hold under an hour keeps the cache; past it, the context rebuilds (`DESIGN.md`, *Sessions*).

### The operator's face

```
lup-dev inbox                         what's waiting for you, oldest first
lup-dev inbox show <number>           one item whole
lup-dev inbox answer <number>         a question: each decision in turn, then a comment
lup-dev inbox done <number>           a message read, off the list
lup-dev inbox send <launch> <text>    a message to the session a launch runs
```

- **The command-line counterpart `DESIGN.md` asks for** (*The dashboard*: "`lup inbox` for the inbox"); its final name is the command-line piece's (`docs/declaration.md`, *The command line*), a command of `Core`'s.
- **Answering:** at a terminal, `answer` takes each numbered decision in turn, "leaning", "undecided" or "leave open", each with an optional comment, then a comment on the whole; a plain question takes a text. `--leaning 1 3`, `--undecided 2`, `--leave-open 4` and `--comment` answer without prompts **(leaning)**. The answer becomes an item for the conversation that asked.
- **`send`** names a launch by its id or its worktree, and reaches the session's main conversation.
- **Each is a request on the control socket,** the inbox's own kinds, starting the service where none runs, as a launch does. Each refuses inside an agent's session (`Runtime.inside`), as `trust` does; the room can't reach the control socket at all, and the store isn't mounted.
- **A desktop notice** when an item for the operator arrives, through `notify-send`: the repository's worktree, the kind, and the item's first line. `Notices` and `NotifySend` move out of `legacy_dashboard.py` into the inbox, which the drafts flow uses until piece 3. `notify-send` is an optional requirement of the host, said once where it's missing.
- **Set aside:** bridging into the first lup's dashboard (#56 suggested it as the inbox's first face), which `docs/review-flow.md` (*The first lup's dashboard*) shows costs a keeper re-parking every 15 seconds and a bridge loaded by path: the stopgap lup stops building on.

## Credentials on the host

`DESIGN.md` (*Policy*): "credentials (a host service doing one action without asking, within limits the declaration sets, such as no push to `main` and no force push)"; "pushes happen from the host". The room holds no SSH agent, key, token or `gh` login (`docs/launch.md`, *The mounts*), and this piece lends it none.

### What the declaration allows

**A `credentials` part of `Core` (leaning),** a `Layer` (`docs/declaration.md`, *The verbs on modules*) holding two selections:

```python
class Credentials(Layer):
    actions: Actions = Actions.default()
    """What the host does with the operator's credentials without asking."""
    protected: Refs = Refs.of("refs/heads/main", "refs/tags/*")
    """Refs no push updates."""

# a project whose feature branches are rebased before review, and whose release branches are the operator's:
.edit(Core(credentials=Credentials(
    actions=Actions().add("force-push"),
    protected=Refs().add("refs/heads/release/*"),
)), why="feature branches are rebased before review; release branches are the operator's")
```

- **Actions** are names from a fixed set, each a handler lup carries out: `fetch`, `push`, `force-push`, `delete-ref`, `read-issues`, `file-issue`, `comment`, `draft-pull-request`. `Actions.all()` is all of them; `Actions.default()` leaves out `force-push` and `delete-ref`, each with its reason, as `catalog/rules.py` leaves rules out. A name that isn't an action fails the load, naming those that are.
- **Protected refs** are patterns over full ref names. lup's default: `main`, after `DESIGN.md`'s own example and `AGENTS.md` ("Never merge into `main` or push to it yourself"), and tags, since a tag marks a release, the operator's **(leaning)**.
- **Everything is a selection** (`DESIGN.md`, *The environment: core and modules*), so allowing force pushes is an `.add` with its reason rather than a switch.
- **Beyond the limits, refused, saying why (leaning):** that the project's declaration doesn't allow it (`Core.credentials`), and that it's the operator's. Asking instead, an action held for the operator's answer, is a proposal, piece 3's.
- **How the host knows them (leaning):** the launch resolves `Core.credentials` from the declaration at the approved commit, as it does the session settings, and sends them with the registration as plain data (`Register.limits`), beside the judge's command; the service records them with the launch, so a restarted service keeps them. Set aside: the service loading a project's declaration itself, which would run the project's code in the per-user service; and asking the repository's judge copy at each action, a second way for the host to read a declaration.

### git through a remote helper

**In the room.**
- **`git-remote-lup`,** a small script using only Python's standard library, shipped in `lup_dev` (`remote/helper.py`, held to ruff, pyright and lup's rules as any production file, an import contract keeping it on the standard library) and written by the launch into its directory as `<launch>/bin/git-remote-lup`, which the room already mounts read-only, that directory on the room's `PATH`; the room's `python` runs it. git sets `GIT_DIR` for it, which the `git` it runs inherits. git runs it for a URL of the form `lup::<address>`: "a URL of the form `<transport>::<address>` explicitly instructs Git to invoke `git remote-<transport>`", the first argument the remote's name where it's a configured remote (`gitremote-helpers(7)`). A custom transport is allowed by git's default policy (`protocol.allow`, `user`).
- **It advertises `push`, `fetch` and `option`,** and turns each batch git sends into one typed request on `/run/lup/request.sock`, printing the host's answer in git's terms:
  - `list` and `list for-push`: the remote's refs, from the host;
  - `push`: each `<src>` resolved in the room first with `git rev-parse --verify`, since git hands the helper the revision as written (`HEAD~1`, measured), and sent as an object id with its destination, whether it's forced (`+`) and the options git set (`force`, `cas` for `--force-with-lease`, `dry-run`, `atomic`, `push-option`); an empty `<src>` is a deletion;
  - `fetch <oid> <name>`: the objects fetched on the host into the repository's own store, which the room shares; the room's git then writes its own refs.
- **Where the standard library can't follow lup's conventions.** git's helper protocol is lines of words (read with `.split()`), but a push's refspec is `[+]<src>:<dst>`, read by its last `:` (a destination is a full ref name, which can't hold one, `git-check-ref-format(1)`; a source can, as in `HEAD:path`); and `git rev-parse` runs through `subprocess`, since `sh` isn't there. The room's bare Python has no library for either, so each place takes an `ignore` saying so, which the operator reviews. Its requests are the host's models written as JSON by hand, so a test runs the script and validates what it sends as those models, keeping the two in step. The alternative: the file excluded from lup's rules, as the bridge's hooks are (`lup_project.py`), one decision instead of several, at the cost of nothing checking it.
- **The room's git configuration,** `GIT_CONFIG_GLOBAL=<launch>/gitconfig`, since the repository's `config` is read-only in the room and its home has no `~/.gitconfig` (`docs/launch.md`, *The mounts*); "if `GIT_CONFIG_GLOBAL` is set, neither `$HOME/.gitconfig` nor `$XDG_CONFIG_HOME/git/config` will be read" (`git(1)`). It holds:
  - for each of the repository's remotes, `url."lup::<url>".insteadOf = <url>`, its push URL too where it has one: a rewrite given outside the repository's config applies to a URL the repository's config names, for push and fetch alike (measured, git 2.56.0 on the host and 2.55.0 in the room). Fetching needs it as much as pushing: lup's own remote is `jvj:joy-void-joy/lup`, an alias from the operator's `~/.ssh/config`, which the room can't resolve. `pushInsteadOf` would leave fetches failing, and is ignored for a remote with its own push URL;
  - `branch.autoSetupMerge = false` and `push.default = current`, as the first lup set for the same read-only config (its `7d64da189`). `git push -u` in the room pushed, failed twice to write the upstream ("Device or resource busy"), then printed "branch 'feat' set up to track 'origin/feat'." and exited 0 (measured): nothing records an upstream in the room, so a branch's push names its remote, or relies on `push.default`, and the guidance says so.

**On the host,** the remote module's `RoomHandler`:
- **Where it pushes is the repository's word, never the room's.** It runs git in the repository's own git directory, which the launcher found on the host before the room started and the registration carries (`Register.repository`), never a path the room names; it takes the remote's URL from that repository's `config` by the remote's name (`git remote get-url --push <name>`), which the room can't write. A URL that isn't one of the repository's remotes is refused: otherwise a room could point the helper at anything the operator's credentials reach.
- **It checks each update against the limits:** a force (`+`, `option force`, `option cas`), a deletion (an empty source), a protected destination. git's own non-fast-forward refusal comes before the helper hears anything, from the refs `list for-push` reported (measured), and a room can speak to the socket directly, so the host checks all three itself.
- **It pushes by object id,** `git push <url> <oid>:<dst>`, one update at a time, never with `--force`, so the forge refuses a non-fast-forward too; each update's `ok <dst>` or `error <dst> <why>` carries git's own words. The objects are already in the repository, since it's the host's, mounted, so nothing crosses the socket but ids.
- **`list`** is `git ls-remote <url>`, read word by word. **`fetch`** is `git fetch --no-write-fetch-head <url> <name>`, after which the object asked for must be there; no ref is written on the host.
- **The operator's credentials** are the service's environment: their SSH agent and git's credential helpers as the terminal had them when a launch started the service. A push failing on them says git's own error; `lup-dev host stop` and the next launch start the service from a terminal that has them.
- **git and `gh` are spawned through asyncio** and awaited on the service's event loop, as each judge is, for the same reason: `sh` forks in a process with threads (#23), and would hold a thread per call. The `ignore` there grows to say so.
- **Every push and fetch is said in the service's log:** the launch, the remote, each ref and object, and the outcome.
- **#13 stays open.** A push through the helper still moves the room's remote-tracking ref (measured: with a fetch refspec, `refs/remotes/origin/main` moved, its reflog "update by push"), so the checkpoint can still set a pushed write aside as pulled. Piece 3 removes the per-call checkpoint the issue is about. lup's own repository has no fetch refspec, so no remote-tracking refs, and isn't affected meanwhile.

**Set aside:**
- **Lending credentials into the room,** the first lup's ladder: a forwarded SSH agent, which "can sign anything that key can sign, for every host it reaches" (its `2026479aa`), a copy of the keys, a token over HTTPS. Its own docstring: "The agent can read whatever it is lent". Nothing would hold a push to the declaration's limits.
- **`connect`, or git's `ext::` helper,** which pipe git's pack protocol to the forge: fetching needs no policy there, but holding a push to the limits means reading the ref updates inside the protocol's packets, and telling a force from their old and new ids; `ext::` is also off by git's default policy ("known-dangerous protocols (ext) have a default policy of never").
- **A dumb pipe in the room** like the hook's, with the host reading git's protocol and resolving each `<src>` in the worktree's git directory: the host would then run git in a directory the room writes (below).

**Running git on the host in a repository the room writes: a check owed before building.** The room can't write `config` or `hooks/` (read-only mounts), but it writes the rest of the git directory: refs, `packed-refs`, `objects/` and `objects/info/alternates`, `info/`, `shallow`, each worktree's directory. Each, and what the host does about it:
- **`objects/info/alternates`** would let host git read objects of any repository on the machine, so a push could carry another repository's history to this remote: the host refuses to push or fetch while it names a directory outside the repository;
- **replace refs** (`refs/replace/`, which the room can write) could change what an object id reads as: host git runs with `GIT_NO_REPLACE_OBJECTS=1`;
- **refs and `packed-refs`:** pushing by object id, with destinations checked against the limits and the remote's refs from `ls-remote`, reads no local ref;
- **a worktree's directory** (`commondir`, `HEAD`, `index`, `config.worktree`): host git runs in the repository's common git directory alone, never a worktree's; `config.worktree` is read only with `extensions.worktreeConfig`, which only the read-only `config` could set;
- **`info/attributes` and `info/exclude`:** a push and a fetch check nothing out, and an attribute's driver is defined only in `config`;
- **`shallow`:** a `shallow` file the room writes can only make host git send less history than the forge needs, which the forge refuses; nothing leaves that shouldn't;
- **`config`'s includes:** an `include.path` or `includeIf` naming a file the room can write would make the read-only `config` writable in effect, for the operator's own git commands too: the launch refuses a repository whose `config` includes a file inside the room's mounts, a check that belongs to piece 1's room as much as to this;
- **automatic maintenance:** a fetch on the host could start `gc --auto` in a repository the room is using, so host git runs with `gc.auto=0` and `maintenance.auto=false`.

### GitHub through `gh`

- **From the host, through `gh`** (2.102.0 on this machine, logged in as the operator), already lup's through `sh` for issue states (`codescan/directives.py`, `GitHubIssues`), each answer read with `--json` into a pydantic model.
- **The repository is named once,** when the launch registers, from the repository's own remote, read in its git directory (`gh repo view --json nameWithOwner` there), and passed to every call as `--repo`. A worktree's `.git` file is the room's to write (#54), so resolving the repository from the worktree would let a room choose which repository the operator's login acts on.
- **Each tool's action is checked against the limits** (`read-issues`, `file-issue`, `comment`, `draft-pull-request`) before `gh` runs.
- **`draft_pull_request`** runs `gh pr create --draft --base <integration branch> --head <branch>`; the branch must already be on the remote, pushed through the helper, or the tool says so.
- **Bodies go on `gh`'s standard input,** never through a shell.
- **`gh` missing or logged out on the host:** each tool answers why (`gh auth status`'s outcome, as `GitHubIssues.unreachable` says it today), and the launch says it once. `gh` is an optional requirement of the host.
- **Set aside:** GitHubKit (typed models from GitHub's schema, a new dependency, and a token held in the service); `gh` in the room with `http_unix_socket` pointed at a host socket adding the operator's token, which puts github-cli back in the image and the policy on HTTP requests, and whether `gh` speaks TLS over that socket is unverified.

### The gate in a room

The gate checks each `defer(issue=…)`'s issue is still open, through `gh` (`Issues`, `codescan/directives.py`). In a room it crashed on `CommandNotFound: gh`, and since then leaves those issues unchecked there and says why (`docs/field-notes.md`, *Launch, live*). **`HostIssues`,** an `Issues` asking the host for an issue's state over `request.sock` (`IssueState`), answered by the forge's handler with `gh`, is the gate's choice wherever `/run/lup/request.sock` is there; elsewhere `GitHubIssues`, as today. So `uv run lup-dev check` in a room checks deferrals again. The gate runs the project's own `lup-dev` against the per-user service, so a kind the service doesn't know is refused with its name, and the gate says the issue went unchecked and why.

## Trust on launch: the summary first

The first approval on lup's own repository showed its whole host zone, about 110 files and 24,000 lines (`docs/launch.md`, *Trust on launch*), which the operator found unusable. The question becomes, in order **(leaning)**:
1. **What's approved, and why it runs on the host:** "The host runs this repository's declaration and this `lup-dev` outside every room: they judge its sessions' writes, and carry out their pushes and GitHub actions with your credentials." Then the commits: the copy approved before, and the tip.
2. **One line per file:** git's own `--stat`, each file with its lines changed and a bar of those added and removed, a file created or removed marked (`--compact-summary`), and the totals, shown as git prints it, coloured, nothing of it parsed. A release's change is said by its versions, as now.
3. **"Show the whole diff?",** no by default; yes opens it in the pager as today.
4. **"Approve?",** no by default.

`Asker`'s `show` and `ask` (`launch/trust.py`) are enough for it; only the flow changes.

**It stays in the terminal in this piece (leaning):** the operator is at that terminal when launching, and the launch can't go on until it's answered. `DESIGN.md` (*Policy*) and `docs/launch.md` (*Trust on launch*) move it to the inbox with this piece; taking this lean changes a line in each. The alternative, an inbox item too, would let the operator answer from another terminal while the launch waits.

## lup's own sessions move onto launch

Once this piece lands and passes its live checks, lup's own sessions run in rooms (`docs/launch.md`, *Building it*):
- **`Core`'s guidance section** (`declaration/modules/guidance/core.md`): "Pushing and GitHub aren't reachable from the room yet" gives way to what this piece makes true: `git push` and `git fetch` work as usual, through the operator's credentials on the host and within the project's limits, which say what's refused and why; `git push -u` records no upstream, and `git push` pushes the current branch; GitHub is reached through lup's tools; and how to speak to the operator, with `ask` for a decision of theirs, numbered with a lean, and `report` when the work can't go on. Reviewed after it lands, as guidance is (`DESIGN.md`, *Policy*).
- **The operator's change to protected paths:** `.claude/settings.json`, `.claude/hooks/` (the interim review hook) and `.codex/hooks.json` go, and with them `lup_project.py`'s exclusion of `.claude/hooks/**`.
- **`AGENTS.md` is the operator's:** what it says of landing ("merge the branch into `dev` … and push") holds through the helper; what it says of the judge while lup is built (*How work goes*, item 4) holds in a room, whose hook asks about a protected path in the same terminal prompt.
- **`Project.asks`** stays until the judge's asks become proposals (piece 3).

## Modules and public API

### The library

Serving tools over one MCP connection is the library's: a room from code, which `docs/launch.md` leaves to its own slice, will serve its tools to a CLI in a container the same way, and the library already serves `submit` and the speaking tools to Claude Code through `mcp`'s low-level `Server`. What it serves becomes a seam, so the one-turn `Toolbox` is one implementation of it and a launch's tools another.

```python
from lup.tools.serving import Toolset, serve

class LaunchTools(Toolset):                 # the environment's, below
    def specs(self) -> list[ToolSpec]: ...
    async def call(self, name: str, arguments: JsonValue, meta: JsonObject) -> Answer: ...

await serve(LaunchTools(...), reader, writer)   # one MCP session over one connection, until it closes
```

| File | What it's for | Public names |
|---|---|---|
| `tools/serving.py` | Serving tools over MCP: what's served, as a seam; an MCP server over it; one connection over a pair of streams, newline-delimited JSON-RPC as stdio carries it, read with `mcp`'s own message model | `Toolset` (an ABC: `specs`, `call`, which gets the call's `_meta` as the runtime sent it), `Answer` (moved from `sessions/submission.py`), `tool_server(toolset, name="lup")`, `serve(toolset, reader, writer, name="lup")` |
| `sessions/submission.py` | `Toolbox` is a `Toolset`, ignoring `_meta` | |
| `adapters/claude/runtime.py` | `served(toolbox)` gives way to `tool_server(toolbox)` | |
| `sessions/terminal.py` | What a terminal's session loads beside its hooks | `ToolServer` (`name`, `socket`, a Unix socket in the room, `timeout`), `TerminalSettings.servers`; `TerminalSettings.messages`, where the session's own messaging socket goes, none for the runtime's default |
| `adapters/claude/terminal.py` | `--mcp-config <launch>/mcp.json` and `--strict-mcp-config`, each server a stdio entry running `socat` to its socket, with `timeout` in milliseconds and `alwaysLoad: true`; `--messaging-socket-path` and `crossSessionInbound: "accept"` in the launch's settings | none beyond `terminal` |
| `adapters/codex/terminal.py` | each server in the `mcp_servers` inline table that turns the operator's off: `codex stdio-to-uds <socket>` with the CLI's own program, `tool_timeout_sec`, `omit_tools_from = ["deferred"]`, `default_tools_approval_mode = "approve"`; no messaging socket, the gap declared with its evidence | none beyond `terminal` |

- **Always loaded is lup's choice for every server it gives a terminal,** so `ToolServer` has no field for it; keeping a server out of tool search (`DESIGN.md`, *The library*) arrives with the tools slice, as a field arrives with the slice that uses it.
- **Which bridge a room runs is the adapter's,** since only it knows its runtime has one of its own; the neutral form is a server reached on a Unix socket in the room.

### The environment

| File | What it's for |
|---|---|
| `host/rooms.py` | A launch's sockets beside its hook: `mcp.sock`, lup's tools for the launch, one MCP session per connection, each call's conversation read from its `_meta` and routed to the module serving that tool (`RoomTools`: `specs`, `call` with the launch and the party); `request.sock`, one typed request per connection, the launch attached, routed to the modules' `RoomHandler`s through `RoomRoute.to`. Two modules serving one tool name, or answering one kind, are refused when the service is built |
| `host/courier.py` | What the host reads of each runtime's hooks and calls, and how it tells a conversation in a hook's answer: `Courier`, an ABC each adapter fills (`heard`: a hook's event, session, conversation, call and tool, and whether the judge reads it; `caller`: a call's conversation from its `_meta`; `told`: a hook's answer with items added), with `Heard`, `Caller` and `Party` |
| `host/service.py` | `HostService` gains `courier`, `room_routes` and `tools`; a hook the judge doesn't read is answered with what's waiting, without the judge; each launch's room sockets open and close with it |
| `host/protocol.py` | `Register` gains `repository`, the repository's git directory, and `limits`, a `Limits` of the actions allowed and the protected ref patterns |
| `host/client.py` | `RoomClient`: one typed request on `/run/lup/request.sock`, from a room's program |
| `inbox/store.py` | Items and parties, kept one file each in lup's state: `Inbox`, `Item`, `Party` (`Operator`, `Conversation`), `Question`, `Decision`, `Verdict` (`leaning`, `undecided`, `leave open`), `Answer` |
| `inbox/delivery.py` | Telling a conversation: at its next call, at its turn's end, by `wait`, at its session's start, and its wake where its runtime has one; told once; an item too long for a hook announced; an item for an ended conversation passed to its session's main one |
| `inbox/tools.py` | `report`, `note`, `ask`, `message` and `wait` in a launched session, a `RoomTools` |
| `inbox/protocol.py` | The operator's requests on the control socket (list, show, answer, done, send) and their handlers |
| `inbox/notices.py` | `Notices` and `NotifySend`, moved from `legacy_dashboard.py` |
| `forge/github.py` | GitHub through `gh --json`, on one named repository: `GitHub` |
| `forge/tools.py` | `read_issue`, `find_issues`, `file_issue`, `comment`, `draft_pull_request`, a `RoomTools` |
| `forge/protocol.py` | `IssueState`, the room's request for an issue's state, and its handler |
| `remote/helper.py` | The room's helper, `git-remote-lup`, on Python's standard library alone |
| `remote/protocol.py` | The helper's requests and replies (`Listing`, `Pushing`, `Fetching`) and their handler: the limits, the remote's URL, git run in the repository's git directory |
| `remote/config.py` | The room's git configuration from the repository's remotes (`room_config`) |
| `codescan/directives.py` | `HostIssues` beside `GitHubIssues`, sending an `IssueRef`'s repository and number as an `IssueState`; `cli.py`'s `check` picks it where the room's socket is there |
| `declaration/kinds.py`, `declaration/modules/core.py` | `Credentials` (a `Layer`), `Actions`, `Refs`; `Core.credentials` |
| `launch/session.py`, `launch/room.py` | The tool server and the messaging socket in `TerminalSettings`; the helper and `GIT_CONFIG_GLOBAL` in the room; the registration's `repository` and `limits` |
| `launch/trust.py` | The question, summary first |
| `adapters/__init__.py`, `adapters/claude.py`, `adapters/codex.py` | `Adapter` gains `heard`, `caller` and `told`, which `cli.py` builds the `Courier` from; Claude Code's launched hooks become `SessionStart`, `PreToolUse` on every call, `Stop` and `SubagentStop` |
| `layout.py` | `LaunchSockets.mcp`, `.request`, `.messages`; where the inbox is kept; the launch directory's `gitconfig` and `bin/` |
| `cli.py` | `inbox`, until the command-line piece gives each command group its file; the courier, the modules' routes and their tools handed to the service |

- **Subsystems (leaning):** `inbox/`, `forge/` and `remote/` need only the host's seams and the library, so they sit just above `host`: `adapters` > `launch` > `policy` > `codescan` > `declaration` > `catalog` > `remote` > `forge` > `inbox` > `host` in the `layers` contract, though none of the three imports another. `codescan` reaches `forge` for `HostIssues`; `launch` reaches `remote` for the room's configuration; piece 3's judge reaches `inbox`. The host service still imports none of them: `cli.py` hands it their routes and tools, as it hands it the `Answerer` today.
- **No new dependency:** `mcp` is the library's already, and git and `gh` run as programs. git and `gh` join podman among the host's requirements (`launch/room.py`, `host_needs`), `gh` and `notify-send` as optional.

## Tests

- **No agent and no network in any test.** The host service on sockets under the test's temporary directory, a stand-in `gh` (a script on the `PATH` answering recorded JSON), and git on scratch repositories, the "forge" a bare repository on disk.
- **The library's serving:** a `Toolset` served over a socket pair to `mcp`'s own client: tools listed, a call routed with its `_meta`, an invalid call refused by the tool, results as `content` only; `Toolbox` through the same path; Claude Code's in-process server unchanged in behaviour.
- **Each runtime's terminal compile,** compared whole: Claude Code's `mcp.json`, flags and settings; Codex's `mcp_servers` table holding lup's server and the operator's turned off, one of theirs named `lup` replaced.
- **The room sockets:** a call heard on one launch's `mcp.sock` reaching that launch's tools with its conversation; a request on `request.sock` with its launch attached; a control kind sent there refused; the sockets gone with the launch and served again after a restart.
- **Each adapter's `Courier`,** on recorded payloads: who's speaking, whether the judge reads it, and items added to every answer its hooks give (an empty one, the judge's allow, its refusal, a turn's end held or not).
- **The inbox:** items told at a call, at a turn's end once, by `wait`, at session start, and through a stand-in messaging socket; never twice; a long item announced and returned whole by `wait`; a held call's answer after its turn ended told at the next call; an ended subagent's item passed on; items surviving a restart; numbered decisions answered; `lup-dev inbox` refusing inside an agent's session. Time through `lup_dev.clock`.
- **git through the helper,** real git on scratch repositories: the helper run by git against a test service, pushing to a bare repository by object id; a force, a lease, a deletion and a protected ref refused with their reasons; a URL that isn't a remote refused; alternates outside the repository refused; a fetch writing no ref on the host; `git push -u` still exiting 0; the helper's requests validating as the host's models.
- **GitHub:** each tool through the stand-in `gh`, `--repo` always the registered repository; an action outside the limits refused; `gh` missing; `HostIssues` answering the gate.
- **The declaration:** `Credentials` layering across a base and a project, an unknown action refused, the limits reaching the registration.
- **Trust:** the summary, the diff only when asked, through a stub `Asker`.
- **Live, by hand, before landing,** on a scratch project and on each runtime: below.

## Checks owed

One short live room per runtime settles most of them; they're runtime behaviour, so they're checked live rather than in tests, and what they find goes into `docs/field-notes.md`.
- **Claude Code 2.1.296:**
  - `_meta["claudecode/toolUseId"]` arrives on each call and equals the `PreToolUse` hook's `tool_use_id`;
  - the `socat` bridge under `--mcp-config` and `--strict-mcp-config` in an interactive room, its tools loaded at start (`alwaysLoad`);
  - a call held past the 30-minute idle limit, and for hours, with the entry's `timeout`;
  - Esc on a held call: whether it sends `notifications/cancelled`;
  - `--messaging-socket-path` in the socket directory, `crossSessionInbound: "accept"` from `--settings` under `bypassPermissions`, the message's frame, and an idle session starting a turn;
  - `/mcp` reconnecting lup's server after a service restart;
  - what a `PreToolUse` hook on every call costs, measured;
  - that `--resume` keeps the session's id.
- **Codex 0.162.1:**
  - `_meta`'s `threadId`, `sessionId` and `callId` equal the hooks' `agent_id`, `session_id` and `tool_use_id`;
  - `codex stdio-to-uds` under `-c mcp_servers.lup=…`, and `omit_tools_from = ["deferred"]` loading lup's tools at start;
  - a call held for hours with `tool_timeout_sec`;
  - a `PreToolUse` answer's `additionalContext`, with no decision, reaching the model;
  - in code mode, the model telling lup's `wait` from Codex's own, and what it sees of a held call answered after its turn ended;
  - that resuming keeps the thread's id.
- **git, before `remote` is built:** the review of host-side git in a repository the room writes (*Running git on the host*), each response confirmed on a scratch repository; a fetch by name from GitHub through the host; the service's SSH agent when a launch started it.
- **GitHub:** `gh repo view` in a bare repository's git directory naming the repository behind an SSH alias such as `jvj:`.
- **The field note** on what a Claude Code server learns of its caller, corrected once the first check above is settled.

## Building it

Each a branch that passes the gate on its own, foundation first **(leaning)**:
1. **`feat-tool-serving`,** the library: `lup.tools.serving`, `Toolbox` and Claude Code's asks on it; `ToolServer`, `TerminalSettings.servers` and `.messages`, each adapter's compile. The research behind this note goes into `docs/field-notes.md` here.
2. **`feat-room-sockets`:** `mcp.sock` and `request.sock` per launch, `RoomHandler`, `RoomTools`, the `Courier` and each adapter's part of it, Claude Code's hooks widened, hooks the judge doesn't read answered without it; served with no module's tools yet.
3. **`feat-inbox`:** the store, delivery, the five tools, `lup-dev inbox`, the notices; the launch giving the session its tool server and messaging socket.
4. **`feat-credential-limits`:** `Credentials`, `Actions` and `Refs` on `Core`, resolved by the launch into the registration.
5. **`feat-forge`:** GitHub through `gh`, its tools, `HostIssues` for the gate in a room.
6. **`feat-remote`:** once the host-side git review is settled, the helper, the room's git configuration, and pushing and fetching on the host.
7. **`feat-trust-summary`:** the question, summary first.
8. **The live checks** on both runtimes, recorded in `docs/field-notes.md`; then `Core`'s guidance, and lup's own sessions move onto launch, the operator removing the committed runtime trees.
