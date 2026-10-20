# lup's tools and the inbox

Everything between a session and the operator goes through the inbox, which the host service keeps (`inbox/`; `docs/host.md`). A session reaches it through lup's tools, served on its launch's `mcp.sock`; the operator through `lup-dev inbox` or the dashboard (`docs/dashboard.md`).

## lup's tools

| Tool | What it does |
|---|---|
| `ask` | Asks the operator: numbered decisions, each with the agent's lean, or a plain question. With `wait`, the call holds until they answer and returns the answer; without, the answer comes with a later call |
| `note` | Tells the operator an assumption, a doubt or a counterargument, and carries on: news, with no notice |
| `friction`, `how_it_went` | Says what got in the way, the moment it does; says how a piece of work went, once near its end. Each reaches the operator directly, a subagent's too, never its parent |
| `blocked`, `stop` | Says the work can't go on; ends it by the agent's own choice. Either answer tells the agent to end its turn |
| `send` | A message of a kind (`note`, `problem`, `disagreement`, `question`) to the operator's inbox, the general verb beside the speaking tools |
| `wait_inbox` | Holds until something reaches the agent, and returns all of it |
| `inbox` | Reads the repository's inbox, changing nothing: what's still waiting, for the operator or an agent, every item with `every`, or one of the agent's own whole |
| `withdraw` | Takes back a message or question the agent sent that no longer needs the operator, with its reason |
| `judged` | Reads what the judge made of the repository's writes, and its holds, changing nothing (`docs/judging-writes.md`, *The verdict log*) |
| `rename` | Names the session's launch, or a subagent, after its task (`docs/launch.md`, *Names*) |
| `read_issue`, `find_issues`, `file_issue`, `comment`, `draft_pull_request` | GitHub, through the operator's login on the host (`docs/credentials.md`, *GitHub through `gh`*) |

- **Who serves which:** the inbox's tools are the core's (`InboxTools`, `inbox/tools.py`), and so is `judged` (`JudgeTools`, `policy/tools.py`), which the inbox, below the judge in `lup_dev`'s layers, can't import; `rename` is the host service's own; the GitHub tools are the `GitHub` module's, served from the launch's process of its repository's approved copy (`docs/host.md`, *Each launch's judge and modules*).
- **The speaking tools are the library's** (`lup.tools.speaking`): `blocked`, `stop`, `note`, `friction` and `how_it_went` have the same names and inputs on an ask from code, so an agent's habit carries between the two. In a launched session whoever asked is the operator.
- **`wait_inbox` isn't called `wait`,** since on a Codex model in code mode Codex has a `wait` tool of its own, and two tools of one name invite the wrong call.
- **`judged` is sized to be read whole:** the latest 50 verdicts and 20 holds of each state, never splitting a moment, with how many it left out and the `until` that reads them. lup's own log, listed whole after ten days, was 785,000 characters, past what a tool's result holds.
- **Results are one text block:** Codex shows the model only a result's `structuredContent` where it has one, and Claude Code reads `content`, so a result with both would read differently on each. A large result is the runtime's to keep for now (#164).

**Found through tool search, listed in the guidance.** Each runtime defers an MCP server's tools behind its tool search, Codex where the model supports it (`docs/field-notes.md`, *MCP in a launched session*), so a tool's description can be as long as it needs without costing every request its context: the first lup's 14 coordination tools, always loaded, carried about 10 KB of descriptions (its `coordination/tools.py` and `peer_tools.py`). But agents told nothing of deferred tools concluded they didn't exist, so every session's guidance lists each tool by its name and summary (`listed`, `launch/guidance.py`), and a subagent that doesn't read the guidance is told them once, at its first hook that isn't its turn's end (`introduction`, `host/service.py`), with a line that some subagent types have none of them (#108). A tool's summary is its docstring's first line, 50 characters at most, which `@lup_tool` checks (`ToolSpec.summary`), so the docstring is the one source.

## The operator's face

```
lup-dev inbox                         what's waiting for you, oldest first
lup-dev inbox show <number>           one item whole; --context its moment, --diff an approval's diff
lup-dev inbox answer <number>         a question: each decision in turn, then a comment;
                                      a conversation's message: your reply; an approval: yes or no
lup-dev inbox done <number>           a message read, off the list
lup-dev inbox send <to> <text>        a message to a launch's session, or to a subagent by its path
```

- **Answering** takes each numbered decision in turn, "leaning", "undecided" or "leave open", typed: an empty line asks again, so going with the agent's lean is said, never assumed. `--leaning 1 --undecided 2 --leave-open 3 --comment …` answers without prompts, and `--approve` or `--decline` an approval.
- **A review** is the dashboard's reply covering several items at once, sent whole to each conversation with a comment on its items, a question among them, or a message to it; one whose items were only marked read hears nothing (`docs/dashboard.md`, *The review*).
- **Replying** to a conversation's message, or to a write of its that landed flagged, is a note for that conversation, naming the item it replies to with its first line.
- **A desktop notice** comes with an item waiting on the operator, through `notify-send`, an optional requirement of the host; news and flags raise none.
- **Each command is a request on the host's control socket,** and refuses inside an agent's session, as `trust` does. The room can't reach the control socket, and the store isn't mounted.

## Parties and items

- **The parties:** the operator, and each conversation of each session, its main one or a subagent. A conversation is keyed by its runtime, its session and its own id within a repository, not by the launch it runs in, so a session resumed in a later launch finds what waited for it.
- **An item** has a number (one sequence per user, so the operator types `lup-dev inbox answer 12`), a sender and a recipient, the worktree it's from, when it was made, and its state: waiting, told, answered, done, decided, superseded or withdrawn. It's one of: a message of its kind; a friction, how it went or a stop; a question; an answer; a review; trust's approval (`docs/trust.md`); a held change; a flagged write (`docs/judging-writes.md`, *Asking the operator*).
- **Its kind's rank** (`ranked`, `inbox/store.py`), the one place each kind's is said: what waits on the operator first, raising a notice; news next (a note, a friction, how it went, a stop, a turn's last words); flags last.
- **What an approval, a held change or a flagged write changes** is kept beside it: its whole diff, and each file whole before and after, a binary one by its size, which the dashboard shows. Nothing is cut.
- **An item for a conversation that has ended** goes to its session's main conversation, saying whose it was: a subagent that asked without waiting is usually gone by the time the operator answers.
- **Kept on the host** (`$XDG_STATE_HOME/lup/inbox/`), one file per item, written whole. The service is the only writer, and no room mounts it: the first lup's sessions approved their own questions by writing a store they could reach, and its one message log, folded at every read, once lost 121 messages to its trimming.

## How an agent is told

Every item waiting for a conversation is told together, oldest first, by whichever of these comes first (`inbox/delivery.py`):
- **at its next call,** in the hook's answer as `additionalContext`, which Claude Code adds to the model's context beside the call's result, and Codex as a developer message. A call to one of lup's own tools isn't told at its start: told beside `wait_inbox`, an item would reach the model only once the held call returned, and the results of `wait_inbox` and `ask` with `wait` are the items themselves. On Claude Code, whose room hooks no call's end, what waits then goes out at the next call that isn't lup's; on Codex, at the call's end;
- **at its turn's end,** where some are still waiting: the hook holds the end once, telling them, which keeps the conversation going. On Claude Code they're `additionalContext`, which reaches the model as the hook's additional context in a system reminder, not labelled an error as a block's reason is; Codex's turn's end takes no `additionalContext`, so there they're a block's reason (`docs/field-notes.md`, *A turn's end told through `additionalContext`*);
- **when it calls `wait_inbox`,** or `ask` with `wait`;
- **when its session starts or resumes;**
- **when it's idle,** for an item the operator's own act made, arriving while the session is idle: on Claude Code the service starts a turn of the session's own through its messaging socket, ringing a doorbell that says each item's number, kind and sender and that `wait_inbox` reads them. The items themselves never go through that socket, since Claude Code frames what arrives there as another session's message, not the operator's (`docs/field-notes.md`, *Piece 2, live*). Codex has no way in, a gap its adapter declares: the item waits for the session's next call, and typing in its terminal starts one.

**Told once.** An item is told when it's written into a hook's answer or a held call's result, and never again (`DESIGN.md`, *Keeping the operator in the loop*):
- **too long for a hook** (past 10,000 bytes, which Claude Code would save to a file that Claude "can read" but "Claude Code doesn't ask it to"), it's announced there instead, who sent it and its size, and waits for `wait_inbox`, which returns it whole. Nothing is cut;
- **a held call whose turn ended** while it held, as a Codex model in code mode may, returns saying the items come at the next call;
- **a hook gone before its answer was written** puts back as waiting what it would have told.

**A turn's last message** becomes a note in the operator's inbox (`Delivery.concluded`), so what a session ends its turn saying reaches them without the agent sending it again. An end that's held makes none, since the turn goes on; a subagent's last message is its parent's, and makes none either.

**No turn that won't end.** An agent can always end its turn (`holding`, `inbox/ends.py`). Every hold at a turn's end, the inbox's and the judge's alike, holds once and then lets the turn end, holds once per thing across turns, and never starts a turn of its own: the idle doorbell is for an item the operator's act made.

**Holding a call.** `ask` with `wait` holds its call until its question is answered, and `wait_inbox` until anything arrives. Each runtime's limit on a call is set to 25 hours, above a hold's day: on Claude Code the server's `timeout`, which also raises the 30-minute idle limit of a stdio call, with `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` so a held call isn't moved to the background; on Codex `tool_timeout_sec`. In Codex's code mode the cell yields after 30 seconds and the model may end its turn, so a held call waits for the operator there but the agent may not.

**An item's moment.** An item an agent's call made keeps the runtime's id for that call, and `lup-dev inbox show N --context` reads the conversation's record around it, from the operator's last words before the call to their next (`inbox/context.py`), which the dashboard folds under the item. Each runtime's adapter finds and reads its own records (`Records`, `host/records.py`).
