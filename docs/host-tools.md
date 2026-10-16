# lup's tools in a launched session: the inbox, and the operator's credentials on the host

**One sentence:** a launched session gets lup's tools from an MCP server the host service runs for its launch, so the agent can ask and tell the operator through an inbox they answer with `lup-dev inbox`, and can push, fetch and reach GitHub through the host with the operator's credentials, within limits the project's declaration sets.

This is the second of #56's four pieces (`docs/launch.md`): lup's MCP server in a launched session, the inbox and `lup inbox`, and the credential actions (git through a remote helper, GitHub through lup's tools). Until it lands, a launched session can't push or reach GitHub, so lup's own sessions move onto launch with it (*lup's own sessions move onto launch*). It builds on piece 1 as landed: the room, the compiled settings, the one hook and the host service (`docs/launch.md`). It takes from `DESIGN.md`'s build step 6 the host service's inbox and the tools between an agent and the operator, but not `propose` or `spawn`.

The facts it rests on were read or measured for it on 2026-10-13: Claude Code's docs and its 2.1.296 binary (a byte search, no model called), Codex's source at `rust-v0.162.1`, git 2.56.0's man pages and a logging remote helper run on the host and in the room's image, and the first lup's history. Each is cited where it's used; they go into `docs/field-notes.md` with the first branch (*Building it*). A choice the operator hasn't confirmed is marked **(leaning)**.

What it leaves to other pieces:
- **`propose` and holds** (piece 3), which replace the checkpoint and its mail; the judge's own tellings then become inbox items. #66 (another session's writes under an open hold) is piece 3's, decided with holds; the inbox is how the session whose edit a decline puts back would be told.
- **The dependency guard** (piece 4).
- **Spawn,** and with it messages between agents, the roster, and the native `Agent` denied by default.
- **The dashboard,** whose inbox view `lup-dev inbox` is the command-line counterpart of; reminders and follow-ups; notification channels beyond the desktop's.
- **Asking the operator for an action beyond the limits:** refused in this piece, saying why; asking is a proposal, piece 3's.
- **Transcripts** (#65): lup's own copy of each launched session's record is a neighbour. It files each copy under the same identity the inbox keys a party on (a session, and a conversation in it), so the two agree from the start.
- **The clipboard,** devices and a browser in the room, budgets and `accounts`, as `docs/launch.md` leaves them.

## Decisions

Answered by the operator on 2026-10-14; where they left a decision to the builder, it's marked so.

1. **The tools a launched session gets** (*lup's tools*), decided: every agent has its inbox. `report`, `note`, `ask`, `send` (the general one: a message to a party, the operator in this piece, other agents with spawn), `wait_inbox`, and five GitHub tools; not `propose` (piece 3) or `spawn`. `wait_inbox` is named apart from Codex's own `wait`, which in code mode polls a running cell. **No turn that won't end:** an agent can always end its turn, and what a hold at a turn's end held it for once doesn't hold a later turn's end again (*No turn that won't end*).
2. **Found through tool search, and listed in the guidance** (*lup's tools*), decided: lup's tools stay behind each runtime's tool search, with descriptions as long as they need, and every session's guidance lists each of lup's tools by name with its summary, compiled from the tools themselves: a tool's docstring's first line, 50 characters at most, as a git commit's subject line is, the rest of the docstring its full description. Results as `content`, never `structuredContent`.
3. **The server runs in the host service, on a socket per launch** (*The server*), the builder's: `mcp.sock`, bridged in the room by `socat` on both runtimes. A service restart stops lup's tools in running sessions until `/mcp` reconnects (Claude Code) or the session is resumed (Codex); the hook goes on delivering meanwhile.
4. **A third socket, `request.sock`, for the room's programs** (*The room's requests*), the builder's, with its own routes, so a room never reaches the control socket's kinds.
5. **lup's own id for each conversation, stamped by the hook** (*Who's calling*), decided: the operator chose lup's own interface over reading each runtime's own ids at the server, which in the first lup didn't stay uniform. lup mints an id for each conversation the first time a hook names it, and the hook writes it into every call to lup's tools; the server reads only that.
6. **Claude Code hooks every call and its turn's ends** (*How an agent is told*), decided, provided its cost isn't felt: the service answers what the judge doesn't read without starting the judge, measured before landing.
7. **The inbox lives in the host service** (*Parties and items*), the builder's: durable in lup's state, never mounted, its parties keyed by session, so a resumed session finds what waited for it.
8. **How an agent is told** (*How an agent is told*), the builder's, never pinging needlessly: at its next call, at its turn's end once, by `wait_inbox`, and when it's idle on Claude Code through its own messaging socket, only for the operator's own acts and a burst once; nothing reaches an idle Codex session, a declared gap.
9. **The operator's face is `lup-dev inbox`, with desktop notices** (*The operator's face*), decided; the dashboard later, and no bridge to the first lup's dashboard.
10. **git through `git-remote-lup`** (*git through a remote helper*), the builder's: `push` and `fetch` run on the host by object id to the remote's own URL; the helper held to lup's rules, with an `ignore` where the standard library can't follow them.
11. **The limits are a `credentials` part of `Core`** (*What the declaration allows*), decided: no force push, no deletion, no push to `main` or a tag by default; beyond them, refused, saying why.
12. **GitHub through `gh` on the host** (*GitHub through `gh`*), decided, the repository named once from its own remote.
13. **Where the code goes** (*Modules and public API*), the builder's: serving tools over one MCP connection is the library's; the inbox, GitHub and git are three subsystems of `lup_dev`, just above `host`.
14. **Trust's question: an inbox item from the start, answerable at the launching terminal too** (*Trust on launch: the summary first*), decided: its destination is the inbox wherever it's answered, the dashboard in time, and building it in the terminal alone now would be rebuilt then. Set aside: in the terminal alone in this piece.
15. **lup's own sessions move onto launch once this lands** (*lup's own sessions move onto launch*), decided, with the protected-path change the operator makes.

## lup's tools

### What a launched session gets

| Tool | Input | What it does | The item it makes |
|---|---|---|---|
| `report` | `problem` | Says what's wrong when the work can't go on; its answer tells the agent to end its turn | a message to the operator, kind `problem` |
| `note` | `remark` | Tells the operator an assumption, a doubt or a counterargument, and carries on | a message, kind `note` |
| `ask` | `question`, `decisions` (each with the agent's lean), `wait` | Asks the operator. With `wait`, the call holds until they answer and returns the answer; without, it returns at once and the answer reaches the agent at a later call | a question |
| `send` | `to`, `kind` (`note`, `problem`, `disagreement`, `question`), `text` | Sends a message to a party's inbox: the operator in this piece, other agents once spawn gives them one; never holds | a message of that kind |
| `wait_inbox` | none | Holds until something reaches the agent's inbox, and returns all of it | none |
| `read_issue` | `number`, `repository` | An issue or pull request of this repository, or of another the operator's login can read (`owner/name`), with its comments, and a pull request's checks | none |
| `find_issues` | `query`, `state`, `repository` | Searches the issues and pull requests of this repository, or of another the operator's login can read (`owner/name`) | none |
| `file_issue` | `title`, `body` | Opens an issue | none |
| `comment` | `number`, `body` | Comments on an issue or pull request | none |
| `draft_pull_request` | `branch`, `title`, `body` | Opens a draft pull request from a pushed branch into the integration branch | none |

- **`report` and `note` are the library's speaking tools** (`lup.tools.speaking`): the same names and input models (`Problem`, `Remark`), so an agent's habit carries between an ask from code and a launched session. In a launched session whoever asked is the operator, so each lands in their inbox (`DESIGN.md`, *Sessions*: "telling them something is a message with a `kind`"). Their functions are the environment's, putting the item in the inbox; their descriptions say where it goes. `report` keeps its meaning: the agent stops and says why, and its answer tells it the report is with the operator and to end its turn.
- **`ask` takes numbered decisions,** each with the agent's lean, which the operator answers "leaning", "undecided" or "leave open" with a comment (`DESIGN.md`, *The dashboard*), or a plain question answered in words. A question's answer is told to the conversation that asked, once.
- **`wait_inbox` takes no time limit (leaning):** the runtime's limit on a call bounds it (*Holding a call*), and no loop re-enters a wait to keep the cache warm (`docs/graveyard.md`). It isn't called `wait`: on a Codex model in code mode, Codex has a `wait` tool of its own, which polls a running cell (`docs/library.md`, *No tools but lup's own*), and two tools of one name invite the model to call the wrong one.
- **`send` is the inbox's general verb** (the operator's decision): every agent has an inbox and can write to another's. `report` and `note` keep their own meanings beside it, as the library's speaking tools: `report` stops the work, `note` attaches a doubt to it. A `question` sent is a message that asks for no answer the agent waits on; a decision of the operator's to wait on is `ask`'s. In this piece `to` is `operator`; spawn adds the agents a session can address.
- **The GitHub tools** write to this repository alone (*GitHub through `gh`*); the two that read reach any the operator's login can read, named by `repository` (`docs/related-repositories.md`). There's no merge tool, and none closes or edits an issue **(leaning)**: closing one is the operator's judgement, which a comment can ask for. `draft_pull_request` targets the integration branch, `LUP_INTEGRATION_BRANCH` (`settings.py`, `dev` by default), as trust on launch reads it.
- **Not here:** `propose` (piece 3) and `spawn` (later).

### Found through tool search, listed in the guidance

- **Behind each runtime's tool search, as it defers MCP tools by default** (the operator's decision): Claude Code loads only names and server instructions (its `mcp` docs, *Scale with MCP tool search*), and Codex leaves them out of the first tool list where the model supports tool search (`core/src/tools/spec_plan.rs`). So a tool's description can be as long as it needs, without costing every request its context. The first lup's 14 coordination tools, always loaded, carried about 10 KB of descriptions alone.
- **Listed in every session's guidance, so the agent knows what's there.** The first lup found deferred tools made agents conclude a tool didn't exist, and moved to `alwaysLoad: true` (its `8827c0442`, `8f2ecbe10`); aib found "deferred tool schemas made the agent guess search terms" (`docs/field-notes.md`, *From the downstream projects*). So the guidance a launch renders (`launch/guidance.py`) lists each of lup's tools by its name and its summary, compiled from the tools themselves, and says they're found through tool search by name.
- **A tool's summary is its docstring's first line,** 50 characters at most, as a git commit's subject line is; the rest of the docstring is its full description, as long as it needs. `@lup_tool` already takes the description from the docstring (`lup/tools/tool.py`), so this keeps one source: a summary line past 50 characters, or none, fails when the tool is made, naming it. Set aside: a description field on `lup_tool`, a second place to say what the docstring says.
- **Results as `content` only,** as the library's server answers today (`served`, `adapters/claude/runtime.py`). Codex shows the model only `structuredContent` where a result has it, dropping the content blocks (`protocol/src/models.rs`); Claude Code reads `content`. A result with both would read differently on the two runtimes.
- **A large result** is the runtime's to keep whole: Claude Code saves one past `MAX_MCP_OUTPUT_TOKENS` (25,000 by default) to a file and gives the path; Codex cuts one past about 10,000 bytes by default (`utils/output-truncation`) unless a tool's `output_token_limit` is raised. An issue thread can pass that, so `read_issue`'s limit is raised on Codex's entry **(leaning)**, and `DESIGN.md`'s large results to a file arrive with the tools slice.

### Who's calling

The launch is the socket's: the service hears a call on the launch's own `mcp.sock`, which nothing in the room names (`docs/launch.md`, *On the host: the service*). Within the launch, **each conversation has an id of lup's own, which the hook writes into every call to lup's tools** (the operator's decision):
- **lup mints it** the first time a hook names a conversation: a session's start, a subagent's start, or its first call. Each runtime's adapter reads its own ids from the hook's payload (a session's, a subagent's), as it does today, and the service keeps which runtime ids each lup id stands for. Nothing past the adapter knows a runtime's ids.
- **The hook stamps it.** The `call-started` hook on a call to one of lup's tools answers with the call's input rewritten to carry a field the model's schema doesn't show, `caller`, set to that conversation's id. The server reads `caller` and nothing else of who's calling. The first lup did the same with a hidden `caller` field (its `docs/platform-differentiation.md`): measured on Claude Code 2.1.283, "a rewrite with no decision reached the server even for a tool with `additionalProperties: false`"; on Codex 0.158.0 the rewrite reached the server beside `permissionDecision: "allow"`, and without it "was dropped — the call ran as the model wrote it". Owed live on the versions a launch runs.
- **Set aside: reading each runtime's own ids at the server,** each call's `_meta` (Codex's `callId`, `threadId`, `sessionId`; Claude Code's `claudecode/toolUseId`, joined to its session through the hook). It would put each runtime's spelling in the server too, and the first lup found wiring back to each runtime separately didn't stay uniform, where its own interface did.
- **A call with no `caller`,** a hook that didn't run, is taken as the launch's main conversation, and the service's log says so.
- A process in the room could write another conversation's id into a call. It stays within its own launch, so it can only speak as another conversation of the same session.

## The server: in the host service, reached through a socket

- **A second socket per launch, `mcp.sock`,** in the launch's socket directory beside `hook.sock`, so the room sees it at `/run/lup/mcp.sock` through the directory it already mounts. A message is one line, so its server reads with a line limit well above asyncio's 64 KiB default. Each connection is one MCP session, served by `mcp`'s low-level `Server`, as the library's server is built today, over the connection's own streams (`Server.run(read, write, …)` serves "a single connection over the given streams", `mcp` 2.3.0).
- **In the room, the stdio server is a bridge:**
  - **Claude Code:** `--mcp-config <launch>/mcp.json` with `--strict-mcp-config`, the entry a stdio server running `socat STDIO UNIX-CONNECT:/run/lup/mcp.sock` (socat is in every room, for the hook). `--strict-mcp-config` is "Only use MCP servers from `--mcp-config`, ignoring all other MCP configurations" (its `cli-reference`), managed ones included (its `managed-mcp` docs); the room loads none of the operator's today anyway, since its `~/.claude.json` is lup's and `--setting-sources user` drops `.mcp.json`.
  - **Codex:** the same `socat` bridge, given as `mcp_servers.lup` in the same `-c` inline table that turns off each of the operator's servers: a later `-c` override of the same path replaces the earlier (`config/src/overrides.rs`), so the two can't be separate overrides. An operator's own server named `lup` is refused, the launch saying to rename it: Codex merges a `-c` table into the user's configuration key by key (`config/src/merge.rs`), so their `env`, `cwd` or `enabled_tools` would carry into lup's server, and a `url` makes Codex refuse the configuration ("url is not supported for stdio", `config/src/mcp_types.rs`).
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
- **An item** has a number (one sequence per user, so the operator types `lup-dev inbox answer 12`), a reason, a sender and a recipient, its text, when it was made (through `lup_dev.clock`), and its state: waiting, told (when, and how), answered, decided, or done. The reasons in this piece: a message, with its kind; a question, with its decisions; an answer; an approval, trust on launch's question (*Trust on launch*), decided rather than answered by an item, since no inbox waits for its answer. Proposals, workers' results, reminders and timers join them in later pieces (`DESIGN.md`, *Sessions*).
- **An item for a conversation that has ended** goes to its session's main conversation, saying whose it was **(leaning)**: a subagent that asked without waiting is usually gone by the time the operator answers. A conversation ends at its `conversation-ended` hook. A subagent resumed later finds nothing waiting; the alternative, keeping it for a conversation that may never call again, leaves the answer unread.
- **Kept in lup's state,** `$XDG_STATE_HOME/lup/inbox/`, one JSON file per item, each written whole (`stored.py`, `write_model`). The service is the only writer, on its event loop. **Never mounted into a room:** the first lup's sessions approved their own questions by appending to the relay log they could write. Set aside: one log folded on every read, the first lup's first store ("597 KB of touches and sixteen rows for two live sessions", its `docs/coordination.md`), whose trimming once deleted 121 messages (its `4d1f08f61`). Items are kept once told or answered; clearing old ones goes with lup's cleanup (`DESIGN.md`, *Footprint and cleanup*).

### How an agent is told

"Messages are received at the next tool call, through the one hook, or with a blocking wait. Each answer is told once, never again" (`DESIGN.md`, *Sessions*). Every item waiting for a conversation is told together, oldest first, by whichever of these comes first:
- **At its next call.** The `call-started` hook's answer carries them as `additionalContext`: Claude Code puts it into the conversation as a system reminder the model reads on its next request (its `hooks` docs, *Add context for Claude*); Codex collects a `PreToolUse` answer's `additionalContext` for the model, unless the answer is one it refuses, such as a plain `allow` (`hooks/src/events/pre_tool_use.rs` at `rust-v0.162.1`), owed live. Where the judge answers the same hook, the items are added to its answer.
- **At its turn's end,** where some are still waiting: the `turn-ended` or `conversation-ended` hook holds the end once, `decision: "block"` with the items as the reason, which keeps the conversation going on both runtimes (Claude Code's `hooks` docs, *Stop decision control*; Codex's, `docs/launch.md`, *The one hook*). The items are told by that reason, so they never hold an end again (*No turn that won't end*).
- **When it calls `wait_inbox`,** whose result is the items.
- **When its session starts or resumes,** in the `session-started` hook's answer.
- **When it's idle,** between its turn's end and its next hook:
  - **Claude Code:** through the session's own messaging socket, put in the launch's socket directory with `--messaging-socket-path /run/lup/messages.sock` (in the 2.1.296 binary's help: "Cross-session messaging server path"), so the host reaches it at the same file. "When the receiving session is idle, Claude Code starts a new turn with the message" (its `cross-session-messaging` docs, *Message delivery*); a session that bypasses permission prompts, as a launch does, holds each incoming message for approval unless `crossSessionInbound` is `"accept"`, which the launch's settings set. The frame beyond the optional auth line is undocumented; the first lup measured one on 2.1.278 to 2.1.285 (its `coordination/wake.py`, `195ff73f3`). Owed live on 2.1.296. With `accept`, the operator's other Claude Code sessions can start a turn in the room too; they're theirs.
  - **Codex:** nothing reaches an idle session, a declared gap with its evidence: unprompted notifications from a server are only logged (`rmcp-client/src/logging_client_handler.rs`), and the app-server's `turn/start` runs inside the terminal's own process under `--no-daemon`. The item waits for the session's next call; the operator typing anything in its terminal starts one.
  - Set aside on Claude Code: its channels (a research preview, registered only through an allowed plugin or `--dangerously-load-development-channels`, whose confirmation screen is interactive), and an `asyncRewake` hook, a process held in the room per session to wake it.
  - Claude Code runs no `Stop` hook for a turn the operator interrupts ("Does not run if the stoppage occurred due to a user interrupt", its `hooks` docs), so after an interrupt the service doesn't know the session is idle, and an item waits for the next call.
- **Hooking every call on Claude Code.** Its launched hooks are `SessionStart` and `PreToolUse` on `Edit` and `Write` today; delivering at the next call needs `PreToolUse` on every call, and the turn's ends need `Stop` and `SubagentStop`. The service answers a hook the judge doesn't read (any call but the file tools' writes, and the turn's ends on Claude Code, where the room has no checkpoint) itself, without starting the judge's process: what the runtime's adapter reads of the payload says which (*Modules and public API*, the `Courier`). Such a hook costs a `socat` process in the room and a round trip on a Unix socket, measured before landing; the first lup's guard in the same place took 7.85 ms against its dispatcher's 107 ms (its `17321798b`). Codex already hooks every call, each answered by the judge.

**Told once.** An item is told when it's written into a hook's answer, a held call's result or the messaging socket, and never again. Three cases where that write might not reach the model:
- **Too long for a hook.** Claude Code caps a hook's `additionalContext` at 10,000 characters, past which it saves the text to a file with a 2,000-character preview, and "doesn't ask Claude to read the file" (its `hooks` docs); Codex spills past its `additionalContextLimit`, 2,500 tokens by default. So an item past its runtime's cap is announced in the hook (who sent it, its size) with a line saying `wait_inbox` returns it whole, and stays waiting until then **(leaning)**. Nothing is cut.
- **A held call whose turn ended while it held.** On Codex in code mode a held call is a pending cell, and the model may end its turn: seen live, "ended its turn after 7 min 49 s, the hook still waiting" (`docs/field-notes.md`, *Launch, live*). Where the service has seen the conversation's turn end while a call of its held, the answer isn't counted told by that call: the call returns a line saying the answer reaches the agent at its next call, and the item is told there **(leaning)**.
- **A held call abandoned with Esc.** Codex never sends `notifications/cancelled` (rmcp's `service.rs`, which Codex's timer doesn't use); Claude Code may (the string is in its binary), unverified. Where it does, the service drops the call and the item stays waiting. Where it doesn't, an answer written into a call nobody reads is the gap, said in that runtime's adapter once the live check settles it.

**Batching and not talking over the operator** (`DESIGN.md`, *Sessions*): in this piece every item an agent receives comes from the operator's own act (an answer, a message they send), so nothing needs holding back; a burst is told together.

### No turn that won't end

An agent can always end its turn, and nothing re-launches it for what it's already been told (the operator's requirement). Every hold at a turn's end, the inbox's and the judge's alike:
- **Holds once, then lets the turn end:** the agent ending its turn again ends it (`stop_hook_active` on both runtimes), whatever's still there.
- **Holds once per thing, across turns:** what a hold held an end for doesn't hold a later end again. An inbox item is told in the hold's reason, so it's done. The judge's findings at a turn's end (on Codex in a room: type errors and ruff's findings left in the session's own files, `docs/launch.md`) are remembered as passed once the agent ends its turn past them, and hold a later end only where they've changed. So the agent stopping, the operator asking something, and the agent stopping again ends the turn at once, unless something new came. The Codex room's turn's end as landed holds again at every turn's end on the same findings; it's changed to this with the inbox's own hold (*Building it*).
- **Never wakes an idle session on its own:** the idle wake (above) is for an item the operator's act made, and a burst of them wakes once. No hook starts a turn because a turn ended.

### Holding a call

`ask` with `wait`, and `wait_inbox`, hold their MCP call until something arrives. Each runtime's limit on a call is set above a hold's day, 25 hours, as the hook's is:
- **Claude Code:** `"timeout": 90000000` (milliseconds) on the entry. Without it, a stdio call with no response or progress for 30 minutes aborts; the server's `timeout`, at least 1,000 ms, raises that idle limit with it, and the wall-clock limit is the same `timeout` (the 2.1.296 binary, as its `mcp` and `env-vars` docs describe). `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`, set since piece 1, keeps a held call from moving to the background after two minutes.
- **Codex:** `tool_timeout_sec = 90000` on the entry; its default is 300 s, seconds as a float with no cap, and progress doesn't extend it (`config/src/mcp_types.rs`, `rmcp-client/src/logging_client_handler.rs`). In code mode the cell yields after 30 s and the model may end its turn (above), so on those models a held call waits for the operator but the agent may not.
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
- **A desktop notice** when an item for the operator arrives, through `notify-send`: the repository's worktree, the kind, and the item's first line. `Notices` and `NotifySend` are the inbox's (`inbox/notices.py`). `notify-send` is an optional requirement of the host, said once where it's missing.
- **Set aside:** bridging into the first lup's dashboard (#56 suggested it as the inbox's first face), which costs a keeper parking each review again as the dashboard expires it, an hour after it's parked, and a bridge loaded by path: the stopgap lup stops building on.

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
- **Everything is a selection** (`DESIGN.md`, *Modules*), so allowing force pushes is an `.add` with its reason rather than a switch.
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
  - for each of the repository's remotes, `url."lup::<url>".insteadOf = <url>`, its push URL too where it has one: a rewrite given outside the repository's config applies to a URL the repository's config names, for push and fetch alike (measured, git 2.56.0 on the host and 2.55.0 in the room). Fetching needs it as much as pushing: lup's own remote is `<alias>:joy-void-joy/lup`, `<alias>` an SSH alias in the operator's SSH configuration, which the room can't resolve. `pushInsteadOf` would leave fetches failing, and is ignored for a remote with its own push URL;
  - `branch.autoSetupMerge = false` and `push.default = current`, as the first lup set for the same read-only config (its `7d64da189`). `git push -u` in the room pushed, failed twice to write the upstream ("Device or resource busy"), then printed "branch 'feat' set up to track 'origin/feat'." and exited 0 (measured): nothing records an upstream in the room, so a branch's push names its remote, or relies on `push.default`, and the guidance says so.

**On the host,** the remote module's `RoomHandler`:
- **Where it pushes is the repository's word, never the room's.** It runs git in the repository's own git directory, which the launcher found on the host before the room started and the registration carries (`Register.repository`), never a path the room names; it takes the remote's URL from that repository's `config` by the remote's name (`git remote get-url --push <name>`), which the room can't write, once `git config --local --get-all remote.<name>.url` shows the remote is defined there: a `remotes/<name>` or `branches/<name>` file the room plants defines a remote `get-url` returns too (measured, `docs/field-notes.md`). A URL, even one equal to a remote's, is refused: otherwise a room could point the helper at anything the operator's credentials reach. A destination must be a full `refs/…` name passing `git check-ref-format`, since a short `main` reaches `refs/heads/main` (measured).
- **It checks each update against the limits:** a force (`+`, `option force`, `option cas`), a deletion (an empty source), a protected destination. git's own non-fast-forward refusal comes before the helper hears anything, from the refs `list for-push` reported (measured), and a room can speak to the socket directly, so the host checks all three itself.
- **It pushes by object id,** `git push <url> <oid>:<dst>`, one update at a time, or an `--atomic` batch as one push so none lands if any is refused; an update git didn't force is never forced, so the forge refuses a non-fast-forward too, and a force the limits allow is pushed forced (`+`, or `--force-with-lease` where git sent a lease), else allowing `force-push` would change nothing (as built); each update's `ok <dst>` or `error <dst> <why>` carries git's own words. The objects are already in the repository, since it's the host's, mounted, so nothing crosses the socket but ids.
- **`list`** is `git ls-remote <url>`, read word by word. **`fetch`** is `git fetch --no-write-fetch-head <url> <name>`, after which the object asked for must be there; no ref is written on the host.
- **The operator's credentials** are the service's environment: their SSH agent and git's credential helpers as the terminal had them when a launch started the service. A push failing on them says git's own error; `lup-dev host stop` and the next launch start the service from a terminal that has them.
- **git and `gh` are spawned through asyncio** and awaited on the service's event loop, as each judge is, for the same reason: `sh` forks in a process with threads (#23), and would hold a thread per call. The `ignore` there grows to say so.
- **Every push and fetch is said in the service's log:** the launch, the remote, each ref and object, and the outcome.
- **#13 stays open.** A push through the helper still moves the room's remote-tracking ref (measured: with a fetch refspec, `refs/remotes/origin/main` moved, its reflog "update by push"), so the checkpoint can still set a pushed write aside as pulled. Piece 3 removes the per-call checkpoint the issue is about. lup's own repository has no fetch refspec, so no remote-tracking refs, and isn't affected meanwhile.

**Set aside:**
- **Lending credentials into the room,** the first lup's ladder: a forwarded SSH agent, which "can sign anything that key can sign, for every host it reaches" (its `2026479aa`), a copy of the keys, a token over HTTPS. Its own docstring: "The agent can read whatever it is lent". Nothing would hold a push to the declaration's limits.
- **`connect`, or git's `ext::` helper,** which pipe git's pack protocol to the forge: fetching needs no policy there, but holding a push to the limits means reading the ref updates inside the protocol's packets, and telling a force from their old and new ids; `ext::` is also off by git's default policy ("known-dangerous protocols (ext) have a default policy of never").
- **A dumb pipe in the room** like the hook's, with the host reading git's protocol and resolving each `<src>` in the worktree's git directory: the host would then run git in a directory the room writes (below).

**Running git on the host in a repository the room writes: checked, 2026-10-14** (`docs/field-notes.md`, *Host-side git in a repository the room writes*: each vector measured on scratch repositories laid out like lup's, a hostile room against git 2.56.0). The room can't write `config` or `hooks/` (read-only mounts), but it writes the rest of the git directory: refs, `packed-refs`, `objects/`, `info/`, `shallow`, each worktree's directory, and the common directory's own `config.worktree`. Each, and what the host does about it:
- **The object store must be self-contained:** the host refuses to push or fetch while `objects/info/alternates` or `objects/info/http-alternates` exists, or anything under `objects/` is a symbolic link. Measured: alternates naming another repository's objects let a push copy that repository's blob to the forge, through a relative entry and through nested alternates too; and with no alternates at all, a symlinked pack under `objects/pack/` did the same. One filesystem check covers them all; lup's own repository uses none. A project with an in-tree alternate would be refused too, said as such.
- **replace refs** (`refs/replace/`): a push by object id sends the real objects whatever they say (measured), and host git runs with `GIT_NO_REPLACE_OBJECTS=1` besides, for the commands that read them;
- **refs and `packed-refs`:** pushing by object id, with destinations checked against the limits and the remote's refs from `ls-remote`, reads no local ref (measured);
- **an explicit git directory, always:** host git runs with the repository's common git directory named (`git -C <common>`), never discovered from a working directory, so a worktree's directory (`commondir`, `HEAD`, `index`, its `config.worktree`) is never read (measured). `safe.directory` is no backstop: it refuses only a directory another user owns, and under `--userns=keep-id` the room's files are the operator's;
- **`extensions.worktreeConfig`:** the common directory's `config.worktree` is the room's to write (the read-only mount covers `config` alone), and with `extensions.worktreeConfig=true` in `config` host git reads it, `core.sshCommand` and `core.hooksPath` included (measured): the launch refuses a repository whose `config` sets it;
- **`info/attributes` and `info/exclude`:** a push and a fetch check nothing out, and an attribute's driver is defined only in `config` (measured);
- **`shallow`:** the forge refused a push cut short by it (measured); nothing leaves that shouldn't;
- **`config`'s includes:** an `include.path` naming `info/evil.cfg` made host git read the room's `core.sshCommand` (measured), so the launch refuses a repository whose `config` includes, through `include.path` or `includeIf` (`gitdir:`, `onbranch:`), resolved relative to the including file and followed recursively, a file inside the room's mounts; a check that belongs to piece 1's room as much as to this;
- **automatic maintenance:** a fetch started `git maintenance run --auto --detach`, outliving it (measured on 2.56), so host git runs with `gc.auto=0` and `maintenance.auto=false`;
- **a malformed pack** in `objects/pack/` can't change what an object id delivers (measured), but floods host git's standard error, which the service logs: each push or fetch logs git's errors once, not line by line **(leaning)**.

### GitHub through `gh`

- **From the host, through `gh`** (2.102.0 on this machine, logged in as the operator), already lup's through `sh` for issue states (`codescan/directives.py`, `GitHubIssues`), each answer read with `--json` into a pydantic model.
- **The repository is named once,** by the launcher, from the repository's own remote, read in its git directory (`gh repo view --json owner,name` there), carried in the registration (`Register.github`), and passed to every call as `--repo`. A worktree's `.git` file is the room's to write (#54), so resolving the repository from the worktree would let a room choose which repository the operator's login acts on.
- **Each tool's action is checked against the limits** (`read-issues`, `file-issue`, `comment`, `draft-pull-request`) before `gh` runs.
- **`draft_pull_request`** runs `gh pr create --draft --base <integration branch> --head <branch>`; the branch must already be on the remote, pushed through the helper, or the tool says so.
- **Bodies go on `gh`'s standard input,** never through a shell.
- **`gh` missing or logged out on the host:** each tool answers why (a login problem is `gh`'s own status 4, so no `gh auth status` runs before each call), and the launch says it once. `gh` is an optional requirement of the host.
- **Set aside:** GitHubKit (typed models from GitHub's schema, a new dependency, and a token held in the service); `gh` in the room with `http_unix_socket` pointed at a host socket adding the operator's token, which puts github-cli back in the image and the policy on HTTP requests, and whether `gh` speaks TLS over that socket is unverified.

### The gate in a room

The gate checks each `defer(issue=…)`'s issue is still open, through `gh` (`Issues`, `codescan/directives.py`). In a room it crashed on `CommandNotFound: gh`, and since then leaves those issues unchecked there and says why (`docs/field-notes.md`, *Launch, live*). **`HostIssues`,** an `Issues` asking the host for an issue's state over `request.sock` (`IssueState`), answered by the forge's handler with `gh`, is the gate's choice wherever `/run/lup/request.sock` is there; elsewhere `GitHubIssues`, as today. So `uv run lup-dev check` in a room checks deferrals again. The gate runs the project's own `lup-dev` against the per-user service, so a kind the service doesn't know is refused with its name, and the gate says the issue went unchecked and why.

## Trust on launch: the summary first

The first approval on lup's own repository showed its whole host zone, about 110 files and 24,000 lines (`docs/launch.md`, *Trust on launch*), which the operator found unusable. The question becomes, in order **(leaning)**:
1. **What's approved, and why it runs on the host:** "The host runs this repository's declaration and this `lup-dev` outside every room: they judge its sessions' writes, and carry out their pushes and GitHub actions with your credentials." Then the commits: the copy approved before, and the tip.
2. **One line per file:** git's own `--stat`, each file with its lines changed and a bar of those added and removed, a file created or removed marked (`--compact-summary`), and the totals, shown as git prints it, coloured, nothing of it parsed. A release's change is said by its versions, as now.
3. **"Show the whole diff?",** no by default; yes opens it in the pager as today.
4. **"Approve?",** no by default.

As built (`launch/trust.py`, `docs/launch.md`, *Trust on launch*): the summary is printed rather than paged, so it stays on screen when the question comes; the launch holds a control connection on the approval, so an answer given elsewhere stops the terminal asking ("Item N was declined elsewhere."); the diff is kept beside the item and read only on request (`lup-dev inbox show N --diff`); two launches on one zone share one item.

**An inbox item from the start, answerable at the launching terminal too** (the operator's decision): its destination is the inbox wherever the operator answers it, the dashboard in time (`DESIGN.md`, *Policy*: "in the terminal until the inbox, then wherever the inbox is answered"). So the launch puts the question in the inbox as an approval, and waits on it; the launching terminal shows the summary and asks, its answer answering the item, while `lup-dev inbox answer` from any terminal, and the dashboard once it exists, answer the same item, whichever comes first. Nothing about the question is rebuilt when the dashboard comes. The alternative: in the terminal alone in this piece, moved to the inbox later.

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
    async def call(self, name: str, arguments: JsonValue) -> Answer: ...

await serve(LaunchTools(...), reader, writer)   # one MCP session over one connection, until it closes
```

| File | What it's for | Public names |
|---|---|---|
| `tools/serving.py` | Serving tools over MCP: what's served, as a seam; an MCP server over it; one connection over a pair of streams, newline-delimited JSON-RPC as stdio carries it, read with `mcp`'s own message model | `Toolset` (an ABC: `specs`, `call`), `Answer` (moved from `sessions/submission.py`), `tool_server(toolset, name="lup")`, `serve(toolset, reader, writer, name="lup")` |
| `tools/tool.py` | A tool's summary: its docstring's first line, 50 characters at most, checked when the tool is made | `ToolSpec.summary` |
| `sessions/submission.py` | `Toolbox` is a `Toolset` | |
| `adapters/claude/runtime.py` | `served(toolbox)` gives way to `tool_server(toolbox)` | |
| `sessions/terminal.py` | What a terminal's session loads beside its hooks | `ToolServer` (`name`, `socket`, a Unix socket in the room, `timeout`), `TerminalSettings.servers`; `TerminalSettings.messages`, where the session's own messaging socket goes, none for the runtime's default |
| `adapters/claude/terminal.py` | `--mcp-config <launch>/mcp.json` and `--strict-mcp-config`, each server a stdio entry running `socat` to its socket, with `timeout` in milliseconds; `--messaging-socket-path` and `crossSessionInbound: "accept"` in the launch's settings | none beyond `terminal` |
| `adapters/codex/terminal.py` | each server in the `mcp_servers` inline table that turns the operator's off: `socat STDIO UNIX-CONNECT:<socket>`, `tool_timeout_sec`, `default_tools_approval_mode = "approve"`; no messaging socket, the gap declared with its evidence | none beyond `terminal` |

- **Each runtime's tool search is left as it is,** so `ToolServer` has no field for it; loading a server's tools upfront (`DESIGN.md`, *Calling agents*: "a tool server can be kept out of tool search") arrives with the tools slice, as a field arrives with the slice that uses it.
- **Which bridge a room runs is the adapter's,** since only it knows its runtime has one of its own; the neutral form is a server reached on a Unix socket in the room.

### The environment

| File | What it's for |
|---|---|
| `host/rooms.py` | A launch's sockets beside its hook: `mcp.sock`, lup's tools for the launch, one MCP session per connection, each call's conversation read from the `caller` its hook stamped, and routed to the module serving that tool (`RoomTools`: `specs`, `call` with the launch and the party); `request.sock`, one typed request per connection, the launch attached, routed to the modules' `RoomHandler`s through `RoomRoute.to`. Two modules serving one tool name, or answering one kind, are refused when the service is built |
| `host/courier.py` | What the host reads of each runtime's hooks, and how it answers them: `Courier`, an ABC each adapter fills (`heard`: a hook's event, the runtime's session and conversation ids, its call and tool, and whether the judge reads it; `told`: a hook's answer with items added, and a call to lup's tools rewritten to carry its `caller`), with `Heard`; and `Conversations`, the lup id minted for each conversation the first time a hook names it, kept with the runtime ids it stands for |
| `host/service.py` | `HostService` gains `courier`, `room_routes` and `tools`; a hook the judge doesn't read is answered with what's waiting, without the judge; each launch's room sockets open and close with it |
| `host/protocol.py` | `Register` gains `repository`, the repository's git directory, and `limits`, a `Limits` of the actions allowed and the protected ref patterns |
| `host/client.py` | `RoomClient`: one typed request on `/run/lup/request.sock`, from a room's program |
| `inbox/store.py` | Items and parties, kept one file each in lup's state: `Inbox`, `Item`, `Party` (`Operator`, `Conversation`), `Question`, `Decision`, `Verdict` (`leaning`, `undecided`, `leave open`), `Answer` |
| `inbox/delivery.py` | Telling a conversation: at its next call, at its turn's end, by `wait_inbox`, at its session's start, and its wake where its runtime has one; told once; an item too long for a hook announced; an item for an ended conversation passed to its session's main one |
| `inbox/tools.py` | `report`, `note`, `ask`, `send` and `wait_inbox` in a launched session, a `RoomTools` |
| `inbox/ends.py` | A turn's end held once per thing, across turns: what a hold held it for, an item told or the judge's findings passed, remembered per conversation |
| `inbox/protocol.py` | The operator's requests on the control socket (list, show, answer, done, send) and their handlers |
| `inbox/notices.py` | The desktop's notices: `Notices`, and `NotifySend` through `notify-send` |
| `forge/github.py` | GitHub through `gh --json`, on one named repository: `GitHub` |
| `forge/tools.py` | `read_issue`, `find_issues`, `file_issue`, `comment`, `draft_pull_request`, a `RoomTools` |
| `forge/protocol.py` | `IssueState`, the room's request for an issue's state, and its handler |
| `remote/helper.py` | The room's helper, `git-remote-lup`, on Python's standard library alone |
| `remote/protocol.py` | The helper's requests and replies (`Listing`, `Pushing`, `Fetching`) and their handler: the limits, the remote's URL, git run in the repository's git directory |
| `remote/config.py` | The room's git configuration from the repository's remotes (`room_config`) |
| `codescan/directives.py` | `HostIssues` beside `GitHubIssues`, sending an `IssueRef`'s repository and number as an `IssueState`; `cli.py`'s `check` picks it where the room's socket is there |
| `declaration/kinds.py`, `declaration/modules/core.py` | `Credentials` (a `Layer`), `Actions`, `Refs`; `Core.credentials` |
| `launch/session.py`, `launch/room.py` | The tool server and the messaging socket in `TerminalSettings`; the helper and `GIT_CONFIG_GLOBAL` in the room; the registration's `repository` and `limits` |
| `launch/trust.py` | The question, summary first, an approval in the inbox that the launching terminal answers too |
| `launch/guidance.py` | Each of lup's tools listed by its name and summary, from the tools served |
| `adapters/__init__.py`, `adapters/claude.py`, `adapters/codex.py` | `Adapter` gains `heard` and `told`, which `cli.py` builds the `Courier` from; Claude Code's launched hooks become `SessionStart`, `PreToolUse` on every call, `Stop` and `SubagentStop` |
| `layout.py` | `LaunchSockets.mcp`, `.request`, `.messages`; where the inbox is kept; the launch directory's `gitconfig` and `bin/` |
| `cli.py` | `inbox`, until the command-line piece gives each command group its file; the courier, the modules' routes and their tools handed to the service |

- **Subsystems (leaning):** `inbox/`, `forge/` and `remote/` need only the host's seams and the library, so they sit just above `host`: `adapters` > `launch` > `policy` > `codescan` > `declaration` > `catalog` > `remote` > `forge` > `inbox` > `host` in the `layers` contract, though none of the three imports another. `codescan` reaches `forge` for `HostIssues`; `launch` reaches `remote` for the room's configuration; piece 3's judge reaches `inbox`. The host service still imports none of them: `cli.py` hands it their routes and tools, as it hands it the `Answerer` today.
- **No new dependency:** `mcp` is the library's already, and git and `gh` run as programs. git and `gh` join podman among the host's requirements (`launch/room.py`, `host_needs`), `gh` and `notify-send` as optional.

## Tests

- **No agent and no network in any test.** The host service on sockets under the test's temporary directory, a stand-in `gh` (a script on the `PATH` answering recorded JSON), and git on scratch repositories, the "forge" a bare repository on disk.
- **The library's serving:** a `Toolset` served over a socket pair to `mcp`'s own client: tools listed, a call routed with its arguments, an invalid call refused by the tool, results as `content` only; `Toolbox` through the same path; Claude Code's in-process server unchanged in behaviour; a tool whose docstring's first line passes 50 characters, or that has none, refused when it's made.
- **Each runtime's terminal compile,** compared whole: Claude Code's `mcp.json`, flags and settings; Codex's `mcp_servers` table holding lup's server and the operator's turned off, one of theirs named `lup` refused.
- **The room sockets:** a call heard on one launch's `mcp.sock` reaching that launch's tools with its conversation; a request on `request.sock` with its launch attached; a control kind sent there refused; the sockets gone with the launch and served again after a restart.
- **Each adapter's `Courier`,** on recorded payloads: who's speaking, whether the judge reads it, items added to every answer its hooks give (an empty one, the judge's allow, its refusal, a turn's end held or not), and a call to lup's tools stamped with its conversation's lup id, the same id for every call of one conversation.
- **Turn's ends:** held once per thing across turns: an agent stopping, an item arriving and being told, and the agent stopping again ending at once; the judge's findings passed once not holding a later end until they change.
- **The inbox:** items told at a call, at a turn's end once, by `wait_inbox`, at session start, and through a stand-in messaging socket; never twice; a long item announced and returned whole by `wait_inbox`; a held call's answer after its turn ended told at the next call; an ended subagent's item passed on; items surviving a restart; numbered decisions answered; `lup-dev inbox` refusing inside an agent's session. Time through `lup_dev.clock`.
- **git through the helper,** real git on scratch repositories: the helper run by git against a test service, pushing to a bare repository by object id; a force, a lease, a deletion and a protected ref refused with their reasons; a URL that isn't a remote refused; alternates outside the repository refused; a fetch writing no ref on the host; `git push -u` still exiting 0; the helper's requests validating as the host's models.
- **GitHub:** each tool through the stand-in `gh`, `--repo` always the registered repository; an action outside the limits refused; `gh` missing; `HostIssues` answering the gate.
- **The declaration:** `Credentials` layering across a base and a project, an unknown action refused, the limits reaching the registration.
- **Trust:** the summary, the diff only when asked, through a stub `Asker`.
- **Live, by hand, before landing,** on a scratch project and on each runtime: below.

## Checks owed

Seen live on 2026-10-14 (`docs/field-notes.md`, *Piece 2, live*): on Claude Code 2.1.299 and Codex 0.162.1, lup's tools found through tool search by the names the guidance lists and called through the `socat` bridge, each call stamped with its conversation (Claude Code's `updatedInput` with no decision, Codex's beside `allow`); an item told at the next call without interrupting the one running (Claude Code's hook context, Codex's developer message); an idle Claude Code session woken by the operator's message through its messaging socket; a held `ask` answered after 36 minutes on Claude Code (past its 30-minute idle limit) and after 6 minutes 53 seconds on Codex (past its 300-second default); `git fetch` and a branch's push to GitHub through the host, a deletion refused by the limits; `read_issue` and `find_issues`; `gh repo view` naming the repository behind an SSH alias; an unjudged hook's cost, 4.5 ms. Still owed:
- **Claude Code:** Esc on a held call (whether it sends `notifications/cancelled`); `/mcp` reconnecting lup's server after a service restart; `--resume` keeping the session's id, so a resumed session finds what waited.
- **Codex:** in code mode, what the model sees of a held call answered after its turn ended (the hold above stayed a direct call); resuming keeping the thread's id.
- **GitHub's write tools,** at their first real use from a launched session (the operator's choice): `file_issue`, `comment` (on a pull request's number too), `draft_pull_request`.
- **A protected ref refused by lup live:** a push to `main` met git's own fast-forward refusal first; lup's rule is tested, and was seen against a stand-in forge in a room.

## Building it

Each a branch that passes the gate on its own, foundation first **(leaning)**:
1. **`feat-tool-serving`,** the library: `lup.tools.serving`, `Toolbox` and Claude Code's asks on it; a tool's summary line; `ToolServer`, `TerminalSettings.servers` and `.messages`, each adapter's compile. The research behind this note goes into `docs/field-notes.md` here.
2. **`feat-room-sockets`:** `mcp.sock` and `request.sock` per launch, `RoomHandler`, `RoomTools`, the `Courier` and each adapter's part of it, lup's own conversation ids stamped by the hook, Claude Code's hooks widened, hooks the judge doesn't read answered without it; served with no module's tools yet.
3. **`feat-inbox`:** the store, delivery, the inbox's tools, `lup-dev inbox`, the notices; turn's ends held once per thing across turns, the Codex room's judge's findings among them; lup's tools listed in the guidance; the launch giving the session its tool server and messaging socket.
4. **`feat-credential-limits`:** `Credentials`, `Actions` and `Refs` on `Core`, resolved by the launch into the registration.
5. **`feat-forge`:** GitHub through `gh`, its tools, `HostIssues` for the gate in a room.
6. **`feat-remote`:** the helper, the room's git configuration, pushing and fetching on the host, and the review's responses: the self-contained object store, the explicit git directory, and the launch's refusal of a `config` that sets `extensions.worktreeConfig` or includes a file the room writes.
7. **`feat-trust-summary`:** the question, summary first, an approval in the inbox the launching terminal answers too (decision 14).
8. **The live checks** on both runtimes, recorded in `docs/field-notes.md`; then `Core`'s guidance, and lup's own sessions move onto launch, the operator removing the committed runtime trees.
