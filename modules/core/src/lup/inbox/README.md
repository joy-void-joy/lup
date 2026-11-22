# The inbox

Everything between agents and the operator: the parties, the concerns they hold, what's said between them, and where each stands (`DESIGN.md`, *Concerns and piles*). Each repository has one, kept in the store (`lup/store/README.md`), and every reading is made from what's kept when it's asked.

## What's kept

- **Parties** are named, never numbered: the operator (`operator`), each agent, by their path (`port-plan/promise-door`), and each pile (`frictions/dashboard/keys`). An agent is known by lup's id for them (`lup.Agent.id`), which stays put as they're renamed, and keeps the session they're in (`lup.Agent.session`). A pile is a party that holds concerns and does nothing else; one named by a path not there yet is made, with each pile above it, under the party its path starts with. Where a party sits is an `Under` edge to its spawner or the pile above it. Each repository has `no-agent` and `frictions`.
- **Concerns** are numbered, `@12`: a title, a body whoever answers for it rewrites whole as it changes, every earlier body kept as an earlier version, and the words it came from. A **friction** is a concern of its own kind: what got in an agent's way, held and shown as a friction, never mistaken for a concern.
- **Items** are numbered: one thing a party said, to the parties it names, kept whole. A message, of a tone (a note is news; a problem, a disagreement or a question wants its reader's answer); a question with numbered decisions, each with its lean; the operator's answer, a ruling on each; how it felt; a block, a stop; a turn's last words; the operator's comment, on an item, a part of it, or to a party. A module declares its own kinds of item, each a class deriving from `Item` in its `Recorded`, saying whether one waits (`waits`) and how the operator's views lay it out beyond its words (`laid`, a `Laid`: a fold opening on one of the module's views, and the module's commands its blocks offer), as a landing says a branch waits on the operator's review. What came of one, for the operator's act, is an `Outcome`.
- **Edges** say where each is and what's been done:
  - `Under`, from a concern or a party to what it's under, and `In`, from an item to the concern it was said in or moved to: one place each, the latest drawn;
  - `WorksIn`, from an agent to the concern they work in, where what they say without naming another lands;
  - `Answers`, from an item to what it answers, or a part of it;
  - `Told`, from a party to an item told them; `Shown`, of what's been on the operator's screen;
  - `Done`, from an agent, saying a concern is done and what to try; `Cleared` and `Declined`, the operator's;
  - `Withdrawn`, of an item its writer took back; `Ended` and `Started`, of an agent.

## Where each stands

- **Who holds a concern:** the party it's under, or that its nearest parent concern is under. One whose agent has ended reads as in `no-agent`, saying who left it, and is theirs again when they start again: nothing is moved for an end, so a resumed agent finds what they held.
- **Two marks on a concern,** each its own: the agent's "done", with what to try, and the operator's clearing. Each stands until something newer is said in it, so a concern that comes back to life is open again for both.
- **What waits on the operator:** an item for them whose kind waits, which nothing they or its other readers said answers, and its writer hasn't withdrawn; a concern its agent says is done, which they haven't cleared or declined since. Nothing else waits.
- **What's new to the operator:** every item they haven't had on their screen, whoever it was for, since they read every exchange: a message between agents is in both agents' buffers, new until shown. It stays where it is once shown, losing only its mark, until they clear it. Clearing is the one act that clears: an item, a concern, or a party's buffer whole, until something new happens there.
- **What's told to an agent:** each item for them not told yet, told once, never again.
- **A comment** reaches whoever wrote what it's on, and each party it was for where an agent wrote it to another; one to a pile opens a concern there.
- **A turn's last words** answer each of the operator's items told the agent since their last turn's end.

## Tools and acts

Two parts. `Inboxes` holds the store's database, one for the machine (`approved=True, shared=True`), its file in the part's own directory (`Data`), opened at its first use. Everything kept goes through it:
- **agents' acts are its services,** which their project's code calls, so the repository an act is kept under is the one lup vouches for (`by: Codebase`), never one the caller names;
- **the operator's are its actions and commands:** the dashboard's actions, each under its verb's key on the blocks offering it, `comment` on an item or a part of it, `comment_to` the party a block reaches where it offers no comment of its own (a pile opens a concern with it), `clear` (`done`), `decline`, and `shown` (`seen`), which a block runs once it's been on the operator's screen; and the terminal's commands, `answer` a question, `tell` a party, and `pile`, making one by its path. A comment is the shell's `Commented`, kept whole: the words, the block's lines it quotes, where the passage starts and ends, and the block's version.

`Speaking` is the agents' side, in each project: their tools, each a service call on `Inboxes` for the agent calling, with the names and inputs sessions know: `concern` (open one, or say one thing of one: words, a body, `join`, `hold`, `hand`, `move`, `done`), `friction` (to a pile's path, made where it isn't there, `frictions` by default), `note`, `send` (to any party by its name), `ask`, `how_it_felt`, `blocked`, `stop`, `withdraw` and `inbox`. A friction and a message can go to another repository the store holds (`repository=`), as a friction about lup met in a project's session goes to lup's pile; it's kept there, its writer the agent of the project it was said in. A module posts an item of its own kind through `post`, for an agent, by the kind's name and its own fields (`Posting.of`), and says what came of it through `settle`, an outcome told to the agent that answers the item, so it waits no more; the inbox's own kinds are never posted. Both take `by: Machine`, the repository named in what's given, or `by: Codebase`, its own repository alone. The database reads its records as every module of the project lup runs on the machine declares (`Declared`), so a kind of a project's own module, not among those, is refused. A session's own machinery (#5) runs where the machine's parts run, and calls, as the machine (`by: Machine`), naming the repository in what it gives: the services that tell an agent what's for them once (`told`), list the agents with something not told yet, whom it wakes (`untold`), keep a turn's last words (`turn_ended`), and name, end and start an agent (`agent_named`, `agent_ended`, `agent_started`). Transcripts reads what's been said through `said`: every item every repository's inbox kept after a key of the store's, in the order kept, each with who said it, its words whole (a question's decisions each with its lean, an answer's rulings) and what it's on (the item a comment or an answer is on, the lines a comment quotes, the decisions an answer rules on), so a search finds the operator's words with what they answered.

## What the operator sees

`Inboxes`' views, each a document of the shell's blocks (`lup/shell/README.md`):
- `parties`: a repository's parties at the top, each a fold of the `party` kind with what it holds and what of it is new or waits, opening on its buffer;
- `party`: a party's buffer: the concerns it holds, each a fold of the `concern` kind with its marks, the parties under it, then what it said or was told outside any concern;
- `concern_view`: a concern whole: its body, the concerns under it, then what's been said in it, each item under a line saying who, of what kind, its number, and whether it's new or waits;
- `waiting`: what waits on the operator.

An item of a module's own kind is laid out as its kind says: under its words, a fold of the kind's choosing, opening on the module's view, and each of its blocks offers the module's commands beside a comment.

A comment on a block reaches the party it's about: whoever wrote an item, whoever holds a concern, the agent or pile a buffer is. A pile is a party (`Pile`) for that alone: it keeps what's sent to it, as a concern.

## The second lup's ledger

Until the switch (#13), a repository's frictions and concerns come over from the second lup's ledger once, by the operator's command `convert`, run where the machine runs, given the ledger's file and the repository as each lup names it (`conversion.py`). The second lup kept the words of both tools, `concern` and `friction`, as one kind of item, so a concern read as a friction on the operator's dashboard; a thread is sorted here by the tool its first words were filed with. A friction goes to `frictions`, for triage to group. A concern keeps its title, every body it had, its done mark, and its place: under the agent holding it, else under the concern it was under, else in `no-agent`. Each keeps the words filed in it with either tool, as the operator was told them, by whoever wrote them and when; the notes agents sent into a thread, and everything else of the ledger, stay there, for #11 to make searchable. The agents who held or wrote them are made as lup knows a session's (`lup.Agent.of`), under whoever spawned them, a subagent named as the second lup named them; each reads as ended, so what they held waits in `no-agent`, saying who left it, and is theirs again when they start here. What came over has been on the operator's screen there, so none of it is new. The ledger is opened read-only, the store written in one transaction, and a second run refused.

## Promises

Invariants, over every slice of every call: nothing is told to a party twice; every comment of the operator's reaches a party; a concern is cleared by the operator's act alone; a cleared concern comes back only when something new is said in it. Scenarios: a friction lands where its agent sends it and reads as a friction; an ended agent's concerns wait in `no-agent` and are theirs again when they start; an agent something was sent to is among those to wake until it's told them; a question waits until answered or withdrawn, a note never; news stays until cleared, and a concern cleared comes back with something newer; a comment on agents' exchange reaches both; every concern is found from the list of parties; what waits shows as waiting until answered; an item of a module's own kind waits, laid out as its kind says, until the module settles it, the outcome told to its agent, and the inbox's own kinds can't be posted. A repository's threads in the second lup's ledger come over once, each sorted by the tool its first words were filed with, with what it keeps; notes, another repository's threads and a second run don't.

The state the invariants read is every repository's inbox as data (`everywhere`, a tool that only reads), read again only once the database has taken a write.
