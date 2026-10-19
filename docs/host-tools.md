# lup's tools in a launched session: the inbox, and the operator's credentials on the host

A launched session gets lup's tools from an MCP server the host service runs for its launch. Through them it asks and tells the operator, who answers with `lup-dev inbox` or the dashboard (`docs/dashboard.md`), reads what lup's judge made of its writes, and reaches GitHub with the operator's login; through git's remote helper it pushes and fetches with their credentials. Each is held to limits the project's declaration sets. The room, its one hook and the host service are `docs/launch.md`'s; this doc is what the service gives a session beside its judge, and the clipboard it lends rooms.

## What we have

Paths are under `packages/lup-dev/src/lup_dev/` unless they name another package.

### lup's tools

| Tool | Input | What it does | The item it makes |
|---|---|---|---|
| `report` | `problem` | Says what's wrong when the work can't go on; its answer tells the agent to end its turn | a message to the operator, kind `problem` |
| `note` | `remark` | Tells the operator an assumption, a doubt or a counterargument, and carries on | a message, kind `note` |
| `ask` | `question`, `decisions` (each with the agent's lean), `wait` | Asks the operator. With `wait`, the call holds until they answer and returns the answer; without, it returns at once and the answer reaches the agent at a later call | a question |
| `send` | `to`, `kind` (`note`, `problem`, `disagreement`, `question`), `text` | Sends a message to a party's inbox, the operator's; never holds | a message of that kind |
| `wait_inbox` | none | Holds until something reaches the agent's inbox, and returns all of it | none |
| `inbox` | `number`, `every` | Reads the inbox of the agent's repository, changing nothing: each item in a line, those still waiting or every one; given a number, one of the agent's own whole | none |
| `withdraw` | `number`, `why` | Takes back a message or question the agent sent that still waits for the operator, with its reason | none: the item is `withdrawn` |
| `judged` | `every`, `path`, `since`, `until`, `answered` | Reads what lup's judge made of the writes in the agent's repository, changing nothing: its session's verdicts, or every session's, counted by outcome and reason, then the latest a line each; then the repository's holds still open, and on request those answered | none |
| `rename` | `name` | Names the session's launch after its task; from a subagent, names that subagent alone, under its parent. Refused where another launch, or another subagent of the launch, holds the name (or another launch the container it would give), saying whose (`docs/launch.md`, *Names*) | none |
| `read_issue` | `number`, `repository` | An issue or pull request of this repository, or of another the operator's login can read (`owner/name`), with its comments, and a pull request's checks | none |
| `find_issues` | `query`, `state`, `repository` | Searches the issues and pull requests of this repository, or of another the operator's login can read (`owner/name`) | none |
| `file_issue` | `title`, `body` | Opens an issue | none |
| `comment` | `number`, `body` | Comments on an issue or pull request | none |
| `draft_pull_request` | `branch`, `title`, `body` | Opens a draft pull request from a pushed branch into the integration branch | none |

- **Who serves which.** The inbox's seven are the core's (`InboxTools`, `inbox/tools.py`), and so is `judged`, the judge's (`JudgeTools`, `policy/tools.py`), which reads lup's state on the host (`Layout`), and which the inbox, below the judge in `lup_dev`'s layers, can't import; `rename` is the host service's own (`Naming`, `host/service.py`). The GitHub tools are the `GitHub` module's (`GitHubTools`, `packages/lup/src/lup/github/tools.py`), a module's `ModuleTools` (`declaration/serving.py`), served from the launch's own process of its repository's approved copy (`host/workers.py`, `worker.py`), so a module's code runs as the operator approved it for that repository.
- **`report` and `note` are the library's speaking tools** (`lup.tools.speaking`), with the same names and input models (`Problem`, `Remark`), so an agent's habit carries between an ask from code and a launched session. In a launched session whoever asked is the operator, so their functions and descriptions are the inbox's, and each lands in the operator's inbox. `report` keeps its meaning: the agent stops, and the answer tells it the report is with the operator and to end its turn.
- **`ask` takes numbered decisions,** each with the agent's lean, which the operator answers "leaning", "undecided" or "leave open", each with a comment; or a plain question, answered in words. The answer is told to the conversation that asked, once.
- **`send` is the inbox's general verb:** a message of a kind to a party's inbox, the operator's being the one there is. `report` and `note` keep their own meanings beside it, and a decision of the operator's that the agent waits on is `ask`'s.
- **`inbox` reads, and changes nothing.** It lists the items about the agent's repository, oldest first (`Inbox.about`): those a conversation of it sent or was sent, and the approvals of its host zone, each with its number, when it was made, what it is, from whom to whom ("you" for the conversation reading), where it stands and its first line. An agent sees what waits for the operator, its siblings' items among them, without asking. Given a number, it reads an item whole where it's the conversation's own: as it was told, where it was sent to it, and as it was written, with its decisions and leans, where it sent it; another's is said with its first line alone. Nothing it reads is marked read or told: what reaches an agent still comes through `wait_inbox` and its calls.
- **`withdraw` is the sender's alone.** An agent's workflow is its own, so a message or question it sent that no longer needs the operator (settled, answered by itself, overtaken by a changed plan) comes off their list with its reason, a line (`Withdrawn`, `Delivery.withdrawn`). It leaves the review and `lup-dev inbox`; `lup-dev inbox show` says it was withdrawn, and why. Another conversation's item, an approval or a held change, which the operator answers, and an item no longer waiting are refused in words.
- **`judged` reads the judge's stores, which no room mounts** (`docs/judging-writes.md`, *The verdict log*, *Asking the operator*), and changes nothing. First the verdicts it selects, counted by outcome and reason as `lup-dev verdicts` counts them (`tallied`, `policy/verdicts.py`); then the latest, a line each: when, the file (absolute where the log names its worktree), the tool (or `checkpoint`, `move`), the outcome with its reasons, and the operator's answer. By default the calling session's, by the runtime and session the log records, so a subagent reads its session's; with `every`, every session's and a move's, each saying whose. Then the repository's holds still open, and with `answered` those answered, else their count: each with its key, when it was made and by which conversation, where it stands (what waits with it, or when it was answered), its files with what each asks, and the operator's comment. `path` narrows both to one file, absolute or relative to its worktree; `since` and `until` narrow both to when each was made, an ISO 8601 time (without a zone, the host's, as the answer says times) or an ISO 8601 duration back from now by the service's clock (`PT2H`).
  - **Sized to be read whole:** an answer lists the latest 50 verdicts at most, and 20 holds of each state (`Onlooker.listed`, `holds_listed`). Where it leaves earlier ones out, it says how many and the `until` that reads them, the moment of the earliest it listed, never splitting a moment, so nothing is out of reach. lup's own log, listed whole after ten days, was 785,000 characters, past what a tool's result holds; the default answer on it is about 7,000 for one session and 11,000 with `every`.
  - **Only the launch's repository:** its verdict log, by the git directory the launcher found (`Register.repository`), never a path the room names. Its holds are those whose verdicts that log holds, by key and worktree (`logged`, `policy/holds.py`): a hold is kept in the store of the worktree its session works in, which for a write in the git directory isn't the worktree its verdict names, so every store is read for them.
  - **A held write's answer is its hold's:** the log has an approval of a write its agent waited on only once the judge hears that call finish, which a launched Claude Code session's hooks never report, while the hold has the answer as soon as it's given.
  - **Read off the event loop,** in a thread, since a repository's log grows with every write judged.
- **`wait_inbox` has no time limit of its own:** the runtime's limit on a call bounds it (*Holding a call*). It isn't called `wait`: on a Codex model in code mode, Codex has a `wait` tool of its own, which polls a running cell (`docs/library.md`, *No tools but lup's own*), and two tools of one name invite the model to call the wrong one.
- **The GitHub tools** write to this repository alone (*GitHub through `gh`*); the two that read reach any repository the operator's login can read, named by `repository` (`docs/related-repositories.md`). None merges, or closes or edits an issue: closing one is the operator's judgement, which a comment can ask for. `draft_pull_request` targets the integration branch, `LUP_INTEGRATION_BRANCH` (`settings.py`, `dev` by default).

### Found through tool search, listed in the guidance

- **Behind each runtime's tool search,** which defers MCP tools by default: Claude Code loads only their names and the server's instructions, and Codex leaves them out of the first tool list where the model supports tool search (`docs/field-notes.md`, *MCP in a launched session*). Neither entry asks to load them upfront. So a tool's description can be as long as it needs without costing every request its context: the first lup's 14 coordination tools, always loaded, carried about 10 KB of descriptions alone.
- **Listed in every session's guidance,** each by its name and summary, compiled from the tools served (`listed`, `launch/guidance.py`; `served_tools`, `cli.py`), with a line saying tool search finds each by its name. The first lup found agents told nothing of deferred tools concluded they didn't exist (its `8827c0442`, `8f2ecbe10`), and aib that "deferred tool schemas made the agent guess search terms" (`docs/field-notes.md`, *From the downstream projects*).
- **A tool's summary is its docstring's first line,** 50 characters at most, as a git commit's subject line is; the rest of the docstring is its full description. `@lup_tool` refuses a tool whose first line is longer, or that has none (`ToolSpec.summary`, `packages/lup/src/lup/tools/tool.py`), so the docstring is the one source.
- **Results are `content` only,** one text block (`packages/lup/src/lup/tools/serving.py`): Codex shows the model only a result's `structuredContent` where it has one, and Claude Code reads `content`, so a result with both would read differently on each.
- **A large result is the runtime's to keep:** Claude Code saves one past `MAX_MCP_OUTPUT_TOKENS` (25,000 by default) to a file and gives the path; Codex cuts one past about 10,000 bytes by default (`docs/field-notes.md`, *MCP in a launched session*).

### Who's calling

The launch is the socket's: the service hears a call on the launch's own `mcp.sock`, which nothing in the room names (`docs/launch.md`, *On the host: the service*). Within the launch, each conversation has an id of lup's own, which the hook writes into every call to lup's tools (`host/courier.py`, `host/rooms.py`):
- **lup mints it** the first time a hook names a conversation: a session's start, a subagent's start, or its first call (`Conversations`). Each runtime's adapter reads its own ids from the hook's payload (`heard`), and the service keeps which runtime ids each of lup's stands for, so nothing past the adapter reads a runtime's ids: the first lup, wired to each runtime's own, found they didn't stay uniform.
- **The hook stamps it.** The `call-started` hook on a call to one of lup's tools answers with the call's input rewritten to carry `caller`, the conversation's id, and `call`, the runtime's id for the call (`tool_use_id` on both runtimes), fields the model's schema doesn't show (`stamp`, `Stamped`). The server reads them, and takes them out before the tool sees the arguments. Claude Code takes the rewrite as `updatedInput` with no decision, so the call goes through the session's own permission mode; Codex applies it only beside `permissionDecision: "allow"`. Both reach the server (`docs/field-notes.md`, *Piece 2, live*).
- **`call` anchors the item** the call makes (`Item.call`): the conversation's record keeps the same id beside the call (*An item's moment*).
- **A call with no `caller`,** whose hook didn't run, is taken as the launch's main conversation's, and the service's log says so; one naming a conversation no hook of the launch named isn't run.
- A process in the room could write another conversation's id into a call. It stays within its own launch, so it can only speak as another conversation of the same session.

### The server

- **A socket per launch, `mcp.sock`,** in the launch's socket directory beside `hook.sock`, which the room mounts at `/run/lup`. Each connection is one MCP session, served by the library's `serve` (`packages/lup/src/lup/tools/serving.py`) on `mcp`'s low-level `Server`, one message a line, each read up to 16 MiB (`HostService.line_limit`).
- **In the room, the runtime's stdio server is lup's bridge** (`packages/lup/src/lup/sessions/bridge.py`), `python3 -I <launch>/mcp-bridge.py /run/lup/mcp.sock` on the room's Python, with the standard library alone, carrying each line across both ways. Each runtime's terminal compile gives it (`adapters/claude/terminal.py`, `adapters/codex/terminal.py` in `lup`, whose docstrings give what it rests on):
  - **Claude Code:** `--mcp-config <launch>/mcp.json` with `--strict-mcp-config`, "Only use MCP servers from `--mcp-config`, ignoring all other MCP configurations", managed ones included.
  - **Codex:** `mcp_servers.lup`, the bridge's file mounted read-only at its path, in the same `-c` inline table that turns off each of the operator's own servers, since a later `-c` override of the same key replaces the earlier. An operator's own server named `lup` is refused, the launch saying to rename it: Codex merges a `-c` table into theirs key by key, so its `env`, `cwd` or `enabled_tools` would carry into lup's, and a `url` makes Codex refuse the configuration.
- **No approval is asked:** Claude Code under `bypassPermissions` prompts for an MCP tool only where it's marked as needing the user; Codex's entry says `default_tools_approval_mode = "approve"`.
- **Across a restart of the host service,** which closes every `mcp.sock` connection: neither runtime starts a stdio server again, so the bridge keeps the runtime's side open.
  - A call the service was answering is answered with an error saying its answer is lost and it may have been carried out (a held `ask` among them); its item stays waiting in the inbox.
  - The bridge tries the socket again every half second; a call arriving meanwhile waits, and is answered with an error after a minute without the service.
  - Once it's reached, the bridge replays the runtime's `initialize` under an id of its own, and counts the server back only once that's answered: a service going away can still take a connection and close it unanswered. Then it sends `notifications/initialized`, what waited, and `notifications/tools/list_changed`, which the server declares it may send (`listChanged`), so the runtime lists the restarted copy's tools mid-session.
  - The room's programs are brought up to the service's copy when it serves a recorded launch again (`refreshed`, `launch/room.py`): git's remote helper, the clipboard's programs and the bridge, each rewritten in place where it differs, so a room mounting that one file sees the change. The room runs the helper anew at each push and fetch; a running bridge keeps its code until the next launch.
  - The hook opens a connection per call, so it goes on once the service is back.

### The room's requests

- **A third socket per launch, `request.sock`,** for the room's programs rather than the agent's tools: one JSON request per connection, a pydantic model told apart by `kind`, and one JSON reply, as the control socket takes them. The service attaches the launch, which it knows by the socket (`host/rooms.py`).
- **Its own routes.** A `RoomHandler` answers a request with the launch it came from, routed by `RoomRoute.to(handler)`, apart from the control socket's `Handler`s, so a room never reaches a control kind: registering or ending a launch, stopping the service, or answering the inbox. The first lup's sessions approved their own questions by writing the store they could reach.
- **What uses it:** git's remote helper (*git through a remote helper*), the gate's issue states (*The gate in a room*), the clipboard (*The clipboard*), and a module's `ModuleHandler`s, answered in the launch's own process (`declaration/serving.py`, `host/workers.py`).

### The inbox

Every party has an inbox, kept by the host service (`inbox/`).

#### Parties and items

- **Parties:** the operator, and each conversation of each session, its main one or one of its subagents. A conversation is keyed by its runtime, its session's id and its own, within a repository (`Conversation`, `inbox/store.py`), rather than by the launch it runs in, so a session resumed in a later launch (`lup-dev launch claude --resume <id>`) finds what waited for it there.
- **An item** has a number (one sequence per user, so the operator types `lup-dev inbox answer 12`), a reason, a sender and a recipient, the worktree it's from, when it was made (through `lup_dev.clock`), and its state: waiting, told (when, and how), answered, done, decided, or superseded. Its reason is one of:
  - a message with its kind (`Message`, whose `of` names the item a reply answers);
  - a question with its decisions (`Question`);
  - an answer (`Answer`);
  - the dashboard's review (`Review`);
  - trust on launch's approval (`Approval`, `docs/launch.md`, *Trust on launch*), decided rather than answered, since no party's inbox waits for its answer. One a push to the integration branch asked names the session that pushed, its launch's main conversation as the service last heard it (`Approval.pushed_by`): a push comes from the room's git, not a call, so which of the session's conversations pushed isn't known. The operator's comment on their answer, given in the dashboard or with `lup-dev inbox answer <n> --approve --comment …`, reaches that conversation as a note from the operator saying which approval and the answer (`Delivery.decided`); one a launch asked at its terminal has no session to tell, and its comment is kept with its answer alone;
  - a change held for the operator (`HeldChange`, `docs/judging-writes.md`, *Asking the operator*), decided too, its answer and comment written back to the hold its agent waits on.
- **What an approval or a held change changes** is kept beside its item: its whole diff, as the terminal shows it (`ShowDiff`, `lup-dev inbox show <n> --diff`), and each file it changes, whole before and after, none on the side where it's missing, a binary one by its size alone (`ChangedFile`, `ShowFiles`), which the dashboard's review shows (`docs/dashboard.md`, *The review*). Each is carried by the request that asks (`AskApproval`, `AskHold`): trust reads each file its diff shows from git's objects, in one `git cat-file`, the person's own layer from the copies it compares; a hold, from the content the judge held and the accepted content beside it. Nothing is cut, a first approval carrying every file of the zone: the review lays all of it out, and paints only the lines in view. An approval's files are kept again once the host has read their types (`Inbox.filed`, `TypeReader`), the item kept again with them, which a watch of the inbox sees.
- **An item for a conversation that has ended** goes to its session's main conversation, saying whose it was: a subagent that asked without waiting is usually gone by the time the operator answers. A conversation ends at its `conversation-ended` hook.
- **Kept in lup's state,** `$XDG_STATE_HOME/lup/inbox/`, one JSON file per item and per conversation's whereabouts, each written whole (`stored.py`), an approval's or a held change's whole diff in a file beside it, and its files in another (`InboxLayout`, `layout.py`), read only on request, so listing the inbox never carries them. The service is the only writer, on its event loop, and no room mounts it: the first lup's sessions approved their own questions by appending to the log they could write, and its one log, folded at every read, lost 121 messages to its trimming once (its `4d1f08f61`). Items are kept once told or answered.

#### How an agent is told

Every item waiting for a conversation is told together, oldest first, by whichever of these comes first (`inbox/delivery.py`):
- **At its next call,** in the `call-started` hook's answer as `additionalContext`, which Claude Code puts in a system reminder the model reads at its next request, and Codex in a developer message. Where the judge answers the same hook, the items are added to its answer, and what doesn't fit beside it waits for the next hook. A call to one of lup's own tools (`Heard.served`) is the exception, since its result tells: told beside `wait_inbox`, an item would reach the model only once the held call returned.
- **At its turn's end,** where some are still waiting: the `turn-ended` or `conversation-ended` hook holds the end once, telling the items, which keeps the conversation going on both runtimes. On Claude Code they're `additionalContext`, which the model reads as hook feedback, not as the hook error a block's reason reads as; Codex's turn's end takes no `additionalContext`, so there they're a block's reason (`docs/field-notes.md`, *A turn's end told through `additionalContext`*). Told so, they never hold an end again (*No turn that won't end*).
- **When it calls `wait_inbox`,** or `ask` with `wait`, whose result is the items.
- **When its session starts or resumes,** in the `session-started` hook's answer.
- **When it's idle,** between its turn's end and its next hook, for an item the operator's own act made, the service starts a turn of the session's own, ringing a doorbell: each item's number, kind and sender, and that `wait_inbox` reads them (`doorbell`, `wake`). The items stay waiting, told once by whichever reaches the agent first: `wait_inbox`, its next call's hook, or its turn's end.
  - **Claude Code:** through the session's own messaging socket, put in the launch's socket directory with `--messaging-socket-path /run/lup/messages.sock`, with `crossSessionInbound: "accept"` in the launch's settings, since a session that bypasses permission prompts otherwise holds each message for approval. "When the receiving session is idle, Claude Code starts a new turn with the message", and a busy one takes it at its next boundary. So the service rings only for a session that's idle: its turn ended, it has just started, or the service hasn't heard it since it started (`Presence.turning`); one in its turn is told at its next call or its turn's end. One the operator interrupted runs no `Stop` hook, and is taken as in its turn until its next hook. It rings once until the session's next hook. The socket takes any local session's message, and Claude Code frames each as another session's, not the user's (`docs/field-notes.md`, *Piece 2, live*), so the inbox's content never goes through it: it comes through lup's own tools and hooks alone. Claude Code refuses to start unless the socket's directory is mode 0700, which the service keeps it. With `accept`, the operator's other Claude Code sessions can start a turn in the room too.
  - **Codex:** nothing reaches an idle session, a gap its adapter declares with its evidence: what a server sends unprompted is only logged, and the app-server's `turn/start` runs inside the terminal's own process under `--no-daemon`. The item waits for the session's next call; the operator typing anything in its terminal starts one.
- **Every call is hooked on Claude Code** for this: `SessionStart`, `PreToolUse` on every call, `Stop` and `SubagentStop`. The service answers a hook the judge doesn't read itself, without starting the judge's process (`Heard.judged`, which the adapter's `heard` says): such a hook costs 4.5 ms, against 665 ms for one the judge answers (`docs/field-notes.md`, *A hook the judge doesn't read*). Codex's hooks are the judge's every one.

#### A turn's last message

A session's last message of each turn is an item in the operator's inbox, a note from it (`Delivery.concluded`), so what it ends its turn saying reaches them without the agent sending it again. Both runtimes hand the `Stop` hook the agent's last message (`last_assistant_message`, read into `Heard.said`); once the hook's answer lets the turn end (`Printed.ends`, which each adapter reads), the service makes the note. An end held, by the judge or by the inbox, makes none: the turn goes on, and its next end carries its last message. A subagent's last message is its parent's, and a blank one makes no note. The note is marked as a turn's end (`Message.ending`), said as "the end of a turn": the review heads it `turn ended`, apart from what asks to be answered, and the conversation view leaves it out, since the agent's words already show there.

**Told once.** An item is told when it's written into a hook's answer or a held call's result, and never again (`DESIGN.md`, *Keeping the operator in the loop*: "A finding or a message is told once, never repeated"):
- **Too long for a hook:** Claude Code caps a hook's `additionalContext` at 10,000 characters, past which it saves the text to a file it "doesn't ask Claude to read"; Codex keeps one past its `additionalContextLimit`, 2,500 tokens by default, in a file with a preview. So an item past what its runtime's hook tells whole (`Heard.fits`, 10,000 bytes on both) is announced there instead, who sent it and its size, with a line saying `wait_inbox` returns it whole, and waits until then. Nothing is cut.
- **A held call whose turn ended while it held:** on Codex in code mode a held call is a pending cell, and the model may end its turn (`docs/field-notes.md`, *Launch, live*). Where the service has seen the conversation's turn end while a call of its held, the call returns a line saying the items reach the agent at its next call, and they're told there.
- **A hook gone before its answer was written** puts back as waiting what it would have told (`Post.returned`).
- **A held call abandoned:** a call cancelled while it holds, its connection gone, leaves everything waiting. Codex never sends `notifications/cancelled`, on a timeout or on Esc, and whether Claude Code sends it on Esc is unchecked; where it isn't sent, an answer written into a call nobody reads is lost to the agent.

Every item an agent receives comes from the operator's own act (an answer, a message, a review), so nothing is held back, and a burst is told together.

#### No turn that won't end

An agent can always end its turn, and nothing holds it again for what it's already been told (`holding`, `inbox/ends.py`). Every hold at a turn's end, the inbox's and the judge's alike:
- **holds once, then lets the turn end:** the agent ending its turn again ends it (`stop_hook_active` on both runtimes), whatever's still there;
- **holds once per thing, across turns:** an inbox item told in the hold is told, so it holds nothing more; the judge's findings at a turn's end are remembered as passed once a turn ends past them, and hold a later end only where they've changed (`docs/judging-writes.md`, *The turn's end*). So the agent stopping, the operator asking something, and the agent stopping again ends the turn at once, unless something new came;
- **never wakes an idle session on its own:** the idle wake is for an item the operator's act made, and no hook starts a turn because a turn ended.

#### Holding a call

`ask` with `wait`, and `wait_inbox`, hold their MCP call until something arrives. Each runtime's limit on a call is 25 hours, above a hold's day, as the hook's is (`served`, `launch/session.py`):
- **Claude Code:** the entry's `timeout`, in milliseconds. Without it, a stdio call with no answer or progress for 30 minutes aborts; the server's `timeout` raises that idle limit along with the call's own. `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` keeps a held call from moving to the background after two minutes. A held `ask` returned the operator's answer after 36 minutes.
- **Codex:** `tool_timeout_sec`; its default is 300 s, and progress doesn't extend it. A held `ask` returned after 6 minutes 53 seconds. In code mode the cell yields after 30 s and the model may end its turn (*Told once*), so on those models a held call waits for the operator but the agent may not.

#### The operator's face

```
lup-dev inbox                         what's waiting for you, oldest first; an approval's
                                      line says how to read its summary and diff
lup-dev inbox show <number>           one item whole; --context its moment, --diff an approval's diff
lup-dev inbox answer <number>         a question: each decision in turn, then a comment;
                                      a conversation's message: your reply; an approval: yes or no
lup-dev inbox done <number>           a message read, off the list
lup-dev inbox send <to> <text>        a message to the session a launch runs, or to a subagent
```

- **The command line beside the dashboard** (`DESIGN.md`, *The dashboard*: "Every view also has a CLI command"), in `cli.py`.
- **Answering:** at a terminal, `answer` takes each numbered decision in turn, "leaning", "undecided" or "leave open", typed: an empty line asks again, so going with the agent's lean is said, never assumed; each with an optional comment, then a comment on the whole; a plain question takes a text. `--leaning 1 --leaning 3`, `--undecided 2`, `--leave-open 4` and `--comment` answer without prompts, and `--approve` or `--decline` an approval. The answer becomes an item for the conversation that asked.
- **A review:** the dashboard's reply covering several items at once (`docs/dashboard.md`, *The review*): the operator's draft, kept beside the items (`InboxLayout.draft`), sent as one `Review` item, whole, to every conversation that sent an item it covers: its own items first, with the comments on them or read with nothing to add, then the others' commented items for context; the questions it covers are answered by it, and the messages done.
- **Replying:** `answer` on a conversation's message (a note, a problem, a disagreement, a question sent as a message) takes your reply in words: a note for that conversation, told with the item it replies to and its first line (`Message.of`), and the message off your list. A message can be replied to again; one of the operator's own, an answer or an approval can't.
- **Sending:** `send` names a launch by its name, its id or its worktree, and reaches the session's main conversation; a subagent is reached by its path (`dev/explore-auth`), as `lup-dev sessions` lists it.
- **Each is a request on the control socket,** the inbox's own kinds (`inbox/protocol.py`), starting the service where none runs, as a launch does. Each refuses inside an agent's session (`Runtime.inside`), as `trust` does; the room can't reach the control socket at all, and the store isn't mounted.
- **A desktop notice** when an item for the operator arrives, through `notify-send` (`Notices`, `NotifySend`, `inbox/notices.py`): what it is, who sent it and from which worktree, its first line, and the command showing it. `notify-send` is an optional requirement of the host, said once by a launch where it's missing; a notice that fails is said in the service's log.

#### An item's moment

An item an agent's call made keeps the runtime's id for that call (`Item.call`), and `ShowContext` reads its moment from the conversation's record as it stands (`inbox/context.py`): from the operator's last words before the call, through the call, to their next words or the record's end.
- **Each runtime's adapter finds one conversation's record,** growing while the session runs (`Records.conversation`): Claude Code's `projects/<folder>/<session>.jsonl`, a subagent's `<session>/subagents/agent-<id>.jsonl` beside it, read as its own line of steps; Codex's rollout of the thread, a subagent's its own thread's. It reads it (`Reader.read`), each call with its id (`Called.id`).
- **`lup-dev inbox show N --context`** prints it after the item, each run of tool calls a line and the call marked; the dashboard's review folds it under the item (`docs/dashboard.md`, *The review*).
- **An item without one** says why: no agent's call made it, lup can't read its runtime's records, its record isn't on this machine, or the record doesn't hold the call.

### Watching

A face that stays open, the dashboard first, sees what the operator's commands fetch as it changes, with nothing polled (`host/watch.py`):
- **A watch is a connection on the host's watch socket** (`HostLayout.watch`, beside the control socket, on the host only), carrying one control request on its first line, any kind the control socket answers. The service answers it at once, then again each time what it holds may have changed, sending the reply, one JSON line, where it differs from the one it sent last. A refusal is the last line. The sender keeps its side open while it watches, so its closing is heard and the watch ends with it; the control socket's own protocol, a request read to its end and one reply, stays as it is.
- **What it holds changes in three places alone,** each telling the service's `Changes`: a request answered on the control socket or a room's `request.sock`, a hook answered, and an item of the inbox written (`Inbox.kept`), which catches a question asked with `wait`, made while its call is still held.
- **From an event loop,** `host/client.py`'s `requested` asks one request and `watching` yields a request's replies as they change, raising `HostError` once the service closes the watch, as a service stopping does.
- **What each conversation is doing** comes with the launches listed (`Talker.activity`): running a call, its tool by the runtime's name and whether it's one of lup's, which may hold it until the operator answers; between calls; or ended, a subagent whose conversation is over; each since its hook, through `lup_dev.clock`. It's held in memory, so a service started again knows a conversation's from its next hook.

### Credentials on the host

The room holds no SSH agent, key, token or `gh` login (`docs/launch.md`, *The mounts*). The host carries out a fixed set of actions with the operator's credentials for it, each held to the limits the project's declaration sets (`DESIGN.md`, *Defaults*: "The operator's credentials stay on the host, used on the agent's behalf within limits the project sets"). Lent into the room, credentials would answer to nothing: a forwarded SSH agent "can sign anything that key can sign, for every host it reaches", as the first lup found (its `2026479aa`).

#### What the declaration allows

`Core`'s `credentials`, a `Credentials` layer (`declaration/kinds.py`), holds three selections, each changed where it stands with its reason (`docs/declaration.md`, *What a launch reads*):
- **`actions`,** names from a fixed set, each a handler lup carries out (`Action`, `host/protocol.py`): `fetch`, `push`, `force-push`, `delete-ref`, `read-issues`, `file-issue`, `comment`, `draft-pull-request`. lup's default is `Actions.all()` less `force-push` and `delete-ref`, each dropped with its reason (`catalog/credentials.py`), so an action a later release adds is allowed unless it's withheld too. A name that isn't an action is refused where it's written, naming those that are.
- **`protected`,** patterns over full ref names that no push updates: `refs/heads/main`, since what reaches `main` is the operator's to merge, and `refs/tags/*`, since a tag marks a release. A pattern not starting `refs/` is refused where it's written.
- **`gated`,** patterns over full ref names that a push from a room updates only once the gate passed on the commit it would put there, which the room's helper runs (*git through a remote helper*): `refs/heads/dev` by default, lup's integration branch.

Beyond the limits, an action is refused, saying the project's declaration doesn't allow it (`Core.credentials`) and that allowing it is the operator's call (`Limits.refusal`). The launch resolves `Core.credentials` from the declaration at the approved commit, as it does the session settings, and sends them with the registration as plain data (`Register.limits`, a `Limits`); the service records them with the launch, so a restarted service keeps them. The per-user service never loads a project's declaration, which would run the project's code there.

#### git through a remote helper

**In the room** (`remote/helper.py`):
- **`git-remote-lup`,** shipped in `lup_dev` and written by the launch into its `bin/`, which the room mounts read-only first on its `PATH`; the room's `python` runs it. git runs it for a URL of the form `lup::<address>` ("a URL of the form `<transport>::<address>` explicitly instructs Git to invoke `git remote-<transport>`", `gitremote-helpers(7)`), which git's default policy allows (`protocol.allow`, `user`).
- **It advertises `push`, `fetch` and `option`,** and turns each batch git sends into one typed request on `/run/lup/request.sock`, printing the host's answer in git's terms:
  - `list` and `list for-push`: the remote's refs, from the host;
  - `push`: each source resolved in the room with `git rev-parse --verify`, since git hands the helper the revision as written (`HEAD~1`), and sent as an object id with its destination, whether it's forced (`+`) and the options git set (`force`, `cas` for `--force-with-lease`, `dry-run`, `atomic`, `push-option`); an empty source is a deletion;
  - `fetch <oid> <name>`: the objects fetched on the host into the repository's own store, which the room shares; the room's git then writes its own refs.
- **On the standard library alone,** since the room's Python has nothing else, which an import contract in `pyproject.toml` keeps: git's `rev-parse` runs through `subprocess`, and a refspec or a lease is read by its last `:` (a full ref name can't hold one, `git-check-ref-format(1)`), each under an `ignore` saying so. Its requests are the host's models written as JSON by hand, so a test runs it under git and validates what it sends as those models.
- **The room's git configuration** (`remote/config.py`, `room_config`), `GIT_CONFIG_GLOBAL=<launch>/gitconfig`, since the repository's `config` is read-only in the room and its home has no `~/.gitconfig` (`docs/launch.md`, *The mounts*). It holds:
  - for each URL the repository's remotes name, push URLs among them, `url."lup::<url>".insteadOf = <url>`: a rewrite given outside the repository's `config` applies to a URL inside it, for push and fetch alike (measured, git 2.56.0 on the host and 2.55.0 in the room). Fetching needs it as much as pushing, since a remote's URL may use an alias of the operator's SSH configuration, which the room can't resolve; `pushInsteadOf` would leave fetches failing;
  - `branch.autoSetupMerge = false` and `push.default = current`: `git push -u` in the room pushes, fails to write the upstream ("Device or resource busy") and exits 0, so nothing records an upstream there, and a branch's push names its remote or relies on `push.default`;
  - `lup.requestSocket`, where the helper sends its requests;
  - `lup.gate` and `lup.gated` (`Gating`), each a JSON list: the gate's command on a commit, `lup-dev check --at` through the project's runner, and the declaration's gated refs (`Core.credentials.gated`), read as git's globs, as protected refs are.
- **A push to a gated ref runs the gate first,** on exactly the commit it would put there, so the integration branch never takes a commit the gate fails on, whoever forgot to run it or misread its status. The helper runs `lup.gate` with the commit's object id before asking the host, and holds the update where it fails: git prints the gate's report, then `! [remote rejected] … (the gate failed on <commit>, its report above, so it isn't pushed)`, and with `--atomic` nothing is pushed. A dry run and a deletion run no gate. `lup-dev check --at` answers at once where a pass is recorded for the commit's files (`docs/judging-writes.md`, *The gate*), the usual case, since the session landing work runs the gate on the merged result before it pushes; otherwise it runs the gate in a worktree made at the commit, which on lup's repository costs about 7 s before the gate's own 85 s.
  - **It runs in the room,** before the host is asked: the gate runs the project's code, which the host never runs. The host checks nothing of it, so a room speaking to the socket directly pushes ungated: this steers, as the judge does, and guards nothing.
  - **Outside the repository git runs the helper for:** git runs a helper with `GIT_DIR` naming the worktree's git directory and `GIT_PREFIX` the directory it was run in (measured), which a gate in a worktree of its own would read. The helper runs the gate through `env`, unsetting each variable `git rev-parse --local-env-vars` lists, as git's documentation says a hook leaving its repository does.

**On the host,** the remote module's handlers (`remote/protocol.py`):
- **Where it pushes is the repository's word, never the room's.** git runs in the repository's own git directory, which the launcher found before the room started (`Register.repository`), pinned there (*Running git on the host*). The remote's URL is git's for a remote the repository's `config` defines (`git config --local --get-all remote.<name>.url`, then `git remote get-url --push <name>`): a `remotes/<name>` or `branches/<name>` file the room plants defines a remote `get-url` reads too (measured, `docs/field-notes.md`, *Host-side git in a repository the room writes*). A URL, even one equal to a remote's, is refused, or a room could point the helper at anything the operator's credentials reach. A destination must be a full `refs/…` name passing `git check-ref-format`, since a short `main` reaches `refs/heads/main` (measured).
- **Each update is checked against the limits** before git runs: a force (`+`, `option force`, a lease), a deletion, a protected destination. git's own non-fast-forward refusal comes before the helper hears anything, and a room can speak to the socket directly, so the host checks all three itself.
- **It pushes by object id,** `git push <url> <oid>:<dst>`, one update at a time, or an `--atomic` batch as one push so none lands if any is refused. An update git didn't force is never forced, so the forge refuses a non-fast-forward too; a force the limits allow is pushed forced (`+`, or `--force-with-lease` where git sent a lease). Each update's `ok <dst>` or `error <dst> <why>` carries git's own words. The objects are in the repository's store already, which the room shares, so nothing crosses the socket but ids.
- **`list`** is `git ls-remote <url>`. **`fetch`** is `git fetch --no-write-fetch-head <url> <name>`, after which the object asked for must be there; no ref is written on the host.
- **The operator's credentials** are the service's environment: their SSH agent and git's credential helpers as the terminal had them when a launch started the service. A push failing on them says git's own error; `lup-dev host stop` and the next launch start the service from a terminal that has them.
- **git is spawned through asyncio** and awaited on the service's event loop, as each judge is (`docs/launch.md`, *On the host: the service*).
- **Every push and fetch is said in the service's log:** the launch, the remote, each ref and object, the outcome, and git's standard error once.
- **A push to the integration branch asks trust's approval** of the zone at its tip, where it isn't the one approved (`proposed_after`, `cli.py`; `docs/launch.md`, *Trust on launch*).
- **A push still moves the room's remote-tracking ref** where the repository has a fetch refspec, so the checkpoint can set a pushed write aside as pulled (#13). lup's own repository has no fetch refspec, so no remote-tracking refs.

#### Running git on the host

The room can't write the git directory's `config` or `hooks/` (read-only mounts), but it writes the rest: refs, `packed-refs`, `objects/`, `info/`, `shallow`, each worktree's directory, and the common directory's own `config.worktree`. Each, and what host git does about it, measured on scratch repositories laid out like lup's against a hostile room (`docs/field-notes.md`, *Host-side git in a repository the room writes*):
- **The git directory, pinned:** host git runs in the repository's common git directory with `GIT_DIR` and `GIT_COMMON_DIR` both naming it, through `env` (`pinning`, `Git.pinned`, `git.py`), never discovered from a working directory, so a worktree's directory (`commondir`, `HEAD`, `index`, its `config.worktree`) is never read. Naming the directory alone isn't enough: a `commondir` the room writes at its top, a file a common git directory never has, turns it into a pointer, and `--git-dir`, `-C` and `GIT_DIR` alone all follow it to that directory's `config`, its remotes and `url.*.insteadOf` among it; with both variables set, git reads the repository's own (measured on git 2.55.0). Pinned so: each push, fetch, `ls-remote` and `get-url` for the room (`Remotes.git`), `gh` and the git it runs (`forge/github.py`), and the launch's reading of `config` for the room's git (`room_config`, `room_git`). `safe.directory` is no backstop: it refuses only a directory another user owns, and under `--userns=keep-id` the room's files are the operator's. Where the host's git still finds its directory through a worktree is `docs/worktree-links.md`'s.
- **The object store, self-contained:** the host refuses to push or fetch while `objects/info/alternates` or `objects/info/http-alternates` exists, or anything under `objects/` is a symbolic link (`stray`). Alternates naming another repository's objects let a push copy its blob to the forge, through a relative entry and nested alternates too, and with no alternates at all a symlinked pack did the same; one filesystem check covers them all. A project with an in-tree alternate is refused too, said as such.
- **Replace refs:** a push by object id sends the real objects whatever they say, and host git runs with `GIT_NO_REPLACE_OBJECTS=1` besides, for the commands that read them.
- **Refs and `packed-refs`:** a push by object id, destinations checked against the limits and the remote's refs from `ls-remote`, reads no local ref.
- **`core.sshCommand`, and the rest of `config`:** pinned, the only `config` of the repository's that host git reads is its own, read-only in every room and the operator's to write, so a project's own `core.sshCommand` there holds. `Git` turns off `core.fsmonitor` and hooks for every git it runs.
- **`extensions.worktreeConfig`:** the common directory's `config.worktree` is the room's to write, and with `extensions.worktreeConfig=true` in `config` host git reads it, `core.sshCommand` and `core.hooksPath` included, so the launch refuses a repository whose `config` sets it (`docs/launch.md`, *The room's git*).
- **`config`'s includes:** an `include.path` naming `info/evil.cfg` made host git read the room's `core.sshCommand`, so the launch refuses a repository whose `config` includes a file inside the room's mounts, through any file it includes in turn.
- **`info/attributes` and `info/exclude`:** a push and a fetch check nothing out, and an attribute's driver is defined only in `config`.
- **`shallow`:** the forge refused a push it cut short; nothing leaves that shouldn't.
- **Automatic maintenance:** a fetch started `git maintenance run --auto --detach`, outliving it, so host git runs with `gc.auto=0` and `maintenance.auto=false`.
- **A malformed pack** in `objects/pack/` can't change what an object id delivers, but floods host git's standard error, which the service logs once for each push or fetch.

#### GitHub through `gh`

- **From the host, through `gh`** and the operator's login (`forge/github.py`), each answer read with `--json` into a pydantic model naming the fields asked for; a command answering with a link alone (filing, commenting, opening a pull request) is passed on as `gh` printed it. Measured against `gh` 2.102.0 (`docs/field-notes.md`, *GitHub through `gh` on the host*).
- **The repository is named once,** by the launcher, from the repository's own remotes, read in its git directory (`gh repo view --json owner,name` there, `named`), carried in the registration (`Register.github`), and passed to every call as `--repo`, but for a reading call naming another. Every `gh` runs in that git directory, pinned there, which the git it runs inherits, so a `commondir` the room plants leads it to no remote of the room's. A worktree's `.git` file is the room's to write (#54), so resolving the repository from a worktree would let a room choose which repository the operator's login acts on.
- **Each tool's action is checked against the limits** (`read-issues`, `file-issue`, `comment`, `draft-pull-request`) before `gh` runs.
- **`draft_pull_request`** runs `gh pr create --draft --base <integration branch> --head <branch>`; a branch not on the remote, pushed through the helper, is said before `gh pr create` runs, asked with GitHub's GraphQL, the branch's name a variable.
- **Bodies go on `gh`'s standard input,** and every value the model writes as `--flag=value` or after `--`, never through a shell.
- **A search** leaves out a match in another repository than the one asked, which a query's own qualifiers can reach, and says how many.
- **`gh` missing or logged out on the host:** each tool answers why (a login problem is `gh`'s own status 4, so no `gh auth status` runs before each call), and the launch says it once. `gh` is an optional requirement of the host.

#### The gate in a room

The gate checks each `defer(issue=…)`'s issue is still open (`docs/judging-writes.md`, *The `# lup:` directives*), and a room holds no `gh` and no login. So wherever `/run/lup/request.sock` is there, the gate asks the host (`HostIssues`, `codescan/directives.py`): an `IssueState` on the request socket (`forge/protocol.py`), answered by the `GitHub` module's `Stating` (`packages/lup/src/lup/github/stating.py`) with `gh issue view --json state`, within `read-issues`. Elsewhere it reads them with `gh` itself (`GitHubIssues`). An issue the host doesn't answer (no service, an older one that refuses the kind by its name, `gh` out of reach, reading beyond the limits) goes unchecked, said with the host's reason.

### The clipboard

A room has no display, so nothing in it reaches the operator's clipboard on its own. The host service reaches it for the room (`clipboard/`):
- **In the room,** `wl-paste` and `wl-copy` are first on the `PATH`, beside git's helper: one program under both names (`clipboard/shim.py`), on the room's Python with the standard library alone, written into the launch's `bin/` and refreshed with the host (`RoomClipboard`, `programs`, `launch/room.py`). The room names a Wayland display (`WAYLAND_DISPLAY=lup`, none behind it), so a program choosing its clipboard by it reaches for them: Claude Code copies through `wl-copy` and pastes an image by listing types with `wl-paste -l` and reading `wl-paste --type image/png` (`docs/field-notes.md`, *The clipboard*).
- **On the request socket,** three requests (`clipboard/protocol.py`): the types the clipboard offers, what it holds as one of them (as text where none is named), and text to put on it; each for the clipboard or the primary selection.
- **On the host,** the desktop's own programs answer them (`Desktop`, `clipboard/desktop.py`): `wl-paste` and `wl-copy` where the service's environment names a Wayland session, `xclip` where it names an X one; where it names neither, as for a service started outside the graphical session, each request is refused saying so. A read is bounded: a clipboard holding more than 32 MiB is refused rather than read whole, and a program not answering within 5 s is stopped. `wl-paste` or `xclip` is an optional requirement of the host, said once where both are missing.
- **What it costs:** anything in a room can read what the operator copies, a password among it, and replace it. Every room is lent it.
- **Codex** reads the clipboard natively, through X or Wayland's own protocol rather than through a program, so it isn't reached this way.

### Modules and public API

#### The library

What a server serves is a seam, so one turn's `Toolbox` and a launch's tools are served the same way (`docs/library.md`, *Tools*):

```python
from lup.tools.serving import Answer, Toolset, serve

class LaunchTools(Toolset):                 # the environment's, below
    def specs(self) -> list[ToolSpec]: ...
    async def call(self, name: str, arguments: JsonValue) -> Answer: ...

await serve(LaunchTools(...), reader, writer)   # one MCP session over one connection, until it closes
```

| File (`packages/lup/src/lup/`) | What it's for | Public names |
|---|---|---|
| `tools/serving.py` | Serving tools over MCP: what's served, an MCP server over it, one connection's streams served as stdio carries them | `Toolset` (an ABC: `specs`, `call`), `Answer`, `tool_server(toolset, name="lup")`, `serve(toolset, reader, writer, name="lup")` |
| `tools/tool.py` | A tool's summary, its docstring's first line, checked when the tool is made | `ToolSpec.summary`, `summary_of` |
| `sessions/bridge.py` | lup's MCP bridge: a runtime's stdio server, carried to a Unix socket across the server's restarts | `Bridge`, `main` |
| `sessions/terminal.py` | What a terminal's session loads beside its hooks | `ToolServer` (`name`, `socket`, `timeout`); `TerminalSettings.servers`, `.messages`, `.bridge` |
| `adapters/claude/terminal.py` | `--mcp-config` and `--strict-mcp-config`, each server a stdio entry running the bridge, `timeout` in milliseconds; `--messaging-socket-path` and `crossSessionInbound: "accept"` | none beyond `terminal` |
| `adapters/codex/terminal.py` | Each server in the `mcp_servers` table that turns the operator's off, the bridge mounted read-only, `tool_timeout_sec`, `default_tools_approval_mode = "approve"`; no messaging socket, the gap declared | none beyond `terminal` |
| `github/` | The `GitHub` module (`module.py`), its tools (`tools.py`: `GitHubTools`, each tool's input an `Arguments`, the two that read a `Reading`) and its answer to the gate's issue states (`stating.py`, `Stating`) | `GitHub`, `GitHubTools`, `Stating` |

#### The environment

| File | What it's for |
|---|---|
| `host/rooms.py` | A launch's room sockets beside its hook: the core's tools (`RoomTools`), composed for one launch's session (`LaunchTools`), each call's `caller` and `call` read and taken out (`Stamped`; `stamp`, which an adapter writes them with), the name lup's server goes by (`SERVER`); the room's requests (`RoomHandler`, `RoomRoute`) |
| `host/courier.py` | What the host reads of each runtime's hooks and how it adds to their answers (`Courier`: `heard`, returning `Heard`; `told`, with a `Telling`; `woken`); what each conversation is told at its hooks (`Post`: `telling`, returning `Posted`; `returned`); lup's own id for each conversation (`Conversations`, each a `Conversation`); how a subagent was spawned (`Spawns`, `Spawned`, `Spawning`) |
| `host/service.py` | `HostService`'s `courier`, `post`, `tools`, `room_routes` and `modules`; `rename` (`Naming`, `Namer`, `NewName`) |
| `host/workers.py`, `worker.py` | A launch's modules, served from a process of its own of the repository's approved copy (`Workers`, `LaunchModules`) |
| `host/protocol.py` | `Register`'s `repository`, `limits` and `github` (`GitHubRepository`); the limits as plain data (`Limits`, its `refusal`; `Action`, `actions()`); `Talker`, `Activity` |
| `host/client.py` | `RoomClient`, one typed request on a launch's `request.sock` from a room's program; `requested`, `watching` |
| `host/watch.py` | `Changes`, what tells each watch to answer again |
| `host/records.py` | Each runtime's session records, as its adapter finds and reads them (`Records`, `Reader`, `Called`) |
| `inbox/store.py` | Items and parties, kept one file each: `Inbox`, `Item`, `Operator`, `Conversation`; `Message`, `Question` with each `Decision`, `Answer` with each `Ruling`, `Review` with each `Comment`, `Approval` and `HeldChange`, with their `Diff` and their `ChangedFiles`, each a `ChangedFile` of `Text` or `Binary` content (`content`); the states, `Waiting`, `Told`, `Answered`, `Done`, `Decided`, `Superseded`; `Draft`; `InboxError` |
| `inbox/delivery.py` | Telling each conversation, once (`Delivery`, the service's `Post`), an idle session's doorbell (`doorbell`), and the operator's notices |
| `inbox/typed.py` | An approval's types, read on the host once it's asked with the reading of its files' parse, its files kept again with their whole reading (`TypeReader`, a `Companion` of the service; `docs/launch.md`, *Trust on launch*) |
| `inbox/tools.py` | `report`, `note`, `ask`, `send`, `wait_inbox`, `inbox` and `withdraw` (`InboxTools`, a `RoomTools`; `Speaker`, `specs`) |
| `policy/tools.py`, `policy/holds.py` | `judged` (`JudgeTools`, a `RoomTools`; `Onlooker`, its input `Scope`); a repository's holds, found by its verdict log (`logged`) |
| `inbox/ends.py` | A turn's end held once per thing, across turns (`holding`) |
| `inbox/protocol.py` | The operator's requests on the control socket and their handlers (`ListInbox`, `ShowItem`, `ShowContext`, `AnswerItem`, `FinishItem`, `SendItem`; the approval's `AskApproval`, `AwaitApproval`, `AnswerApproval`, `ShowDiff`, `ShowFiles`; the held change's `AskHold`; the draft's `ShowDraft`, `KeepDraft`, `SendDraft`; a conversation's items, in every state, each with its text whole, `ListItems`, answered `Exchanged`; `routes`) |
| `inbox/context.py` | An item's moment in its sender's conversation (`moment`, `Moment`) |
| `inbox/notices.py` | The desktop's notices: `Notices`, `NotifySend` |
| `forge/github.py` | GitHub through `gh --json` on one repository (`GitHub`, `GitHub.launched`), each answer a model (`Issue`, `PullRequest`, `CheckRun`, `StatusContext`, `Found`, `Search`); naming the repository from its git directory (`named`); `GitHubError`; `PROGRAM` |
| `forge/protocol.py` | The room's request for an issue's state (`IssueState`, answered `Stated`) |
| `remote/helper.py` | The room's helper, `git-remote-lup` (`Helper`, `main`) |
| `remote/protocol.py` | The helper's requests and the host's replies (`Listing`, `Advertised`, `Ref`; `Pushing`, `Update`, `Lease`, `Pushed`, `Updated`; `Fetching`, `Wanted`, `Fetched`) and their handlers (`ListHandler`, `PushHandler`, `FetchHandler`, through `routes`), sharing git on the host (`Remotes`); what the limits refuse (`refusal`, `require`) and a store reading from elsewhere (`stray`) |
| `remote/config.py` | The room's git configuration (`room_config`, `Gating`) |
| `clipboard/shim.py`, `clipboard/protocol.py`, `clipboard/desktop.py` | `wl-paste` and `wl-copy` in the room; the requests (`ListTypes`, `ReadClipboard`, `WriteClipboard`, `routes`); the host's desktop (`Clipboard`, `Desktop`) |
| `codescan/directives.py` | `HostIssues` beside `GitHubIssues` |
| `declaration/kinds.py`, `declaration/modules/core.py`, `catalog/credentials.py` | `Credentials`, `Actions`, `Refs`; `Core.credentials`; lup's defaults (`CredentialDefaults`, `Withheld`) |
| `declaration/serving.py` | What a module serves: `ModuleTools`, `ModuleHandler`, `ModuleHooks` |
| `launch/session.py`, `launch/room.py`, `launch/guidance.py` | The tool server and the messaging socket in `TerminalSettings` (`served`); the room's git and clipboard (`RoomGit`, `RoomClipboard`, `room_git`, `programs`, `refreshed`); lup's tools listed (`listed`) |
| `adapters/claude.py`, `adapters/codex.py` | Each `Adapter`'s `heard`, `told`, `woken` and `hooks` |
| `layout.py` | `LaunchSockets` (`hook`, `mcp`, `request`, `messages`), `HostLayout.watch`, `InboxLayout`, `LaunchLayout` (`gitconfig`, `bin`, `helper`, `pasting`, `copying`) |
| `git.py` | `pinning`, `Git.pinned` |
| `cli.py` | `inbox` and its commands, `sessions`, `rename`; the core's tools (`room_tools`) and what the guidance lists (`served_tools`); the routes handed the service |

`remote/`, `forge/` and `clipboard/` sit above `inbox/` and `host/` in `lup_dev`'s layers, and import none of each other (`pyproject.toml`, the contract "lup_dev's subsystems import downwards"); the host service imports none of them, `cli.py` handing it their routes and tools. git, `gh`, `notify-send` and the clipboard's programs run as programs, and join podman among the host's requirements, all but podman and git optional (`host_needs`, `launch/room.py`).

### Tests

No agent and no network in any test. The host service serves on sockets under the test's temporary directory, in a thread of its own; `gh` is a stand-in on the `PATH` answering `gh` 2.102.0's recorded JSON (`tests/payloads/gh-2.102.0/`); git runs for real on scratch repositories laid out as lup's, a bare repository as the forge; the clipboard's desktop programs are stood in.
- `packages/lup/tests/`: `test_serving.py` (a toolset over a socket pair to `mcp`'s own client), `test_bridge.py` (a stand-in server stopping and starting under the bridge), `test_terminal.py` (each runtime's compile, compared whole).
- `packages/lup-dev/tests/`: `test_host.py` (the room sockets, `caller`, a hook the judge doesn't read, watches), `test_adapters.py` (each `Courier` on recorded payloads), `test_inbox.py` (each way an item is told, once; the tools, `judged` reading the kit's judge's verdicts and holds, and a large log a page at a time, among them; `lup-dev inbox`; a conversation's items listed), `test_remote.py` (the helper run by real git against the service), `test_forge.py`, `test_clipboard.py`, `test_declaration.py` (`Credentials`).

## Where it's going

- **Proposals and holds** replace the per-call checkpoint: the judge's tellings become inbox items, an action beyond the limits becomes a proposal to the operator rather than a refusal, and another session's writes under an open hold are settled with them (#66).
- **Spawn:** other agents become parties `send` reaches, with a roster, and the native `Agent` is denied by default.
- **Quiet** (`DESIGN.md`, *Keeping the operator in the loop*): an agent asks not to be interrupted, the operator's messages wait unless marked urgent, and it gets one summary when the quiet ends. Reminders, timers, follow-ups and workers' results become items too; notices reach channels beyond the desktop's.
- **`lup inbox`:** the inbox's commands become `Core`'s, under the lazy `lup` command (`docs/declaration.md`, *The command line*).
- **Large results** written to a file, the agent given its path and a preview (`docs/library.md`, *Where it's going*), and a tool's output limit raised on Codex where a result such as an issue thread passes about 10,000 bytes.
- **The integration branch** read from the project's declaration rather than a machine setting (#79), for `draft_pull_request`, trust's tip and the gated default alike.
