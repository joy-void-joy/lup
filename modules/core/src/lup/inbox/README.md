# The inbox

Everything between agents and the operator: the parties, the concerns they hold, what's said between them, and where each stands (`DESIGN.md`, *Concerns and piles*). Each repository has one, kept in the store (`lup/store/README.md`), and every reading is made from what's kept when it's asked.

## What's kept

- **Parties** are named, never numbered: the operator (`operator`), each agent, by their path (`port-plan/promise-door`), and each pile (`frictions/dashboard/keys`). An agent is known by lup's id for them (`lup.Agent.id`), which stays put as they're renamed. A pile is a party that holds concerns and does nothing else; one named by a path not there yet is made, with each pile above it, under the party its path starts with. Where a party sits is an `Under` edge to its spawner or the pile above it. Each repository has `no-agent` and `frictions`.
- **Concerns** are numbered, `@12`: a title, a body whoever answers for it rewrites whole as it changes, every earlier body kept as an earlier version, and the words it came from. A **friction** is a concern of its own kind: what got in an agent's way, held and shown as a friction, never mistaken for a concern.
- **Items** are numbered: one thing a party said, to the parties it names, kept whole. A message, of a tone (a note is news; a problem, a disagreement or a question wants its reader's answer); a question with numbered decisions, each with its lean; the operator's answer, a ruling on each; how it felt; a block, a stop; a turn's last words; the operator's comment, on an item, a part of it, or to a party.
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
- **the operator's are its commands:** `answer` a question, `comment` on an item or a part of it, `tell` a party (a pile opens a concern with it), `clear`, `decline`, `pile` (make one by its path), and `shown`, which the page says of what's been on the operator's screen.

`Speaking` is the agents' side, in each project: their tools, each a service call on `Inboxes` for the agent calling, with the names and inputs sessions know: `concern` (open one, or say one thing of one: words, a body, `join`, `hold`, `hand`, `move`, `done`), `friction` (to a pile's path, made where it isn't there, `frictions` by default), `note`, `send` (to any party by its name), `ask`, `how_it_felt`, `blocked`, `stop`, `withdraw` and `inbox`. A friction and a message can go to another repository the store holds (`repository=`), as a friction about lup met in a project's session goes to lup's pile; it's kept there, its writer the agent of the project it was said in. A session's own machinery (#5) calls the services that tell an agent what's for them once (`told`), and that name, end and start an agent (`agent_named`, `agent_ended`, `agent_started`).

## What the operator sees

`Inboxes`' views, each a document of the shell's blocks (`lup/shell/README.md`):
- `parties`: a repository's parties at the top, each a fold of the `party` kind with what it holds and what of it is new or waits, opening on its buffer;
- `party`: a party's buffer: the concerns it holds, each a fold of the `concern` kind with its marks, the parties under it, then what it said or was told outside any concern;
- `concern_view`: a concern whole: its body, the concerns under it, then what's been said in it, each item under a line saying who, of what kind, its number, and whether it's new or waits;
- `waiting`: what waits on the operator.

A comment on a block reaches the party it's about: whoever wrote an item, whoever holds a concern, the agent or pile a buffer is. A pile is a party (`Pile`) for that alone: it keeps what's sent to it, as a concern.

## Promises

Laws, over every slice of every call: nothing is told to a party twice; every comment of the operator's reaches a party; a concern is cleared by the operator's act alone; a cleared concern comes back only when something new is said in it. Scenarios: a friction lands where its agent sends it and reads as a friction; an ended agent's concerns wait in `no-agent` and are theirs again when they start; a question waits until answered or withdrawn, a note never; news stays until cleared, and a concern cleared comes back with something newer; a comment on agents' exchange reaches both; every concern is found from the list of parties; what waits shows as waiting until answered.

The state the laws read is every repository's inbox as data (`everywhere`, a tool that only reads), read again only once the database has taken a write.
