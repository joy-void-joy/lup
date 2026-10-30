# The ledger: lup's typed graph, and threads

The ledger keeps the work as a typed graph: nodes, the edges between them, and every version of every node. Threads are its first kind. A thread is one concern: what's in it (items, the operator's parts, checks) and where it stands. It's one of the core's submodules, always present. The host service opens it at its start, and keeps the inbox on it: each item a node, where it stands and what it answers edges (`docs/inbox.md`, *Kept on the ledger*). Agents open threads, work in them and are told what lands there through lup's tools (`docs/inbox.md`, *Threads*).

## Records

`lup_ledger.records`:
- **A node** (`Node`) has a number from one sequence shared by every node of every repository, cited `@12`. It also has its repository, who wrote it, when, and a name where its kind gives it one (`@dashboard-lag`), unique among its repository's nodes.
  - Who wrote it is the operator, a conversation, or lup itself (`lup_ledger.parties`, `Writer`). A conversation is known by its runtime's ids. The operator and a conversation are the inbox's parties (`Party`), what an item is from and for, so a record and an item say who they're from alike; lup writes what it does of its own accord, such as an item told, and is no party.
  - A name holds a letter, so `@` takes a number or a name and never mistakes one for the other, or for a part's id (`@2159.3`).
- **An edge** (`Edge`) is drawn to a node, either from another node or said of its target alone, as a thread settled is.
  - Both ends must be on the ledger, in the edge's repository.
  - An edge is never changed and has no number.
  - A later edge from the same node replaces an earlier one where its kind says so (`Edge.replaces`): an item moved to another thread is a later edge, not a changed one.
- **A kind** is a subclass whose `kind` field's default names it, namespaced (`ledger:thread`), and stored on the record. `Kinds` lists the classes the store reads records as; the ledger's own are `lup_ledger.threads.KINDS`.
  - A record of a kind no loaded class declares reads as the base class, every field it held kept. It's never refused or dropped, and a version written from it keeps them.
- **A kind refuses what it can't be:**
  - a node, as it's kept (`Node.refused`);
  - an edge, which alone sees both its ends, as it's drawn (`Edge.refused`);
  - either, in its types: `Declined.by` is the operator.
- **Where a node stands is read from the edges drawn to it, never stored:** a status kept on a record outlives what justified it. Each node says whether it waits on the operator, given the edges drawn to it (`Node.waiting`).

## Threads

`lup_ledger.threads`. A thread (`Thread`) has:
- a name, which `thread=` takes, and never an agent's in its repository;
- a title;
- the thread it's under, for sub-threads as deep as needed;
- the conversation holding it, or none.

What's in it is edges drawn to it:
- **a member** (`In`): an item, or a check (`Check`), something only the operator can try;
- **a part** of an item, moved in by its id (`Moved`): the operator's words. It counts as a member while its item stays in its own thread, and waits on whoever answers for the thread until a node in the thread answers it, whoever wrote it (`answered`); a citation from outside is a reference, no answer, and so is one from an item moved in whole. Each kind of edge says whether it answers a part (`Edge.answers`), as the inbox's citation of the part does and its answer to the whole item the part is of, so the ledger reads one without knowing the inbox's kinds;
- **an item moved in whole** (`Moved` with no part), as the operator gathers frictions into one concern: a member while it stays in its own thread, where `In` would take it out, so its own thread's history stays whole. Nothing waits on it: the thread is what stays open. Its writer isn't on the thread for it, having written it elsewhere;
- **a reference** (`Refers`): an item of another thread that touches this one, shown here as a line pointing at it, and no member;
- **its status** (`Status`), the latest one drawn:
  - parked until the first of its triggers comes: an issue closing, a branch or a commit landing, a conversation ending, a time, or a condition named as `defer`'s `when=` names one;
  - done, in an agent's word, with what to try;
  - settled (`Settled`): by the operator; or by lup, saying why, where it made a thread of a past conversation and nothing in it waited on them (`docs/inbox.md`, *Threads*), its act and never put in their name. Never by an agent: the request settling one is the operator's (`inbox-settle-thread`), and nothing an agent reaches, the `thread` tool among it, settles one;
  - declined, which only the operator does (`Declined.by`);
  - reopened, by the operator, or by lup where what a parked thread waits for comes.

`Standing.read` says four things, where it stands said once for any reader (`stood`):
- **Where it stands:** as its status says. While it's working or reopened, it waits on the operator where a member does. A check waits until they answer it (`Answered`), and each kind of node answers for itself, so a new kind changes nothing in the reading.
- **What waits on the operator.**
- **What waits on whoever answers for it:** each part moved in that nothing answers yet.
- **Who's on it:** its holder, then each conversation that wrote what's in it.

`Threads`, on the store, reads threads:
- one, by its number or its name, or a repository's;
- those under one;
- who answers for one: its holder, or else the nearest thread above it that somebody holds, where a holder `live` says has ended holds nothing;
- the threads parked, each by the status that parks it (`parked`);
- what's in one, the references to it, and where it stands.

A thread's sub-threads are read from its repository's threads by their `parent`, so a read covers at most one repository's threads.

## The store

`Ledger` is one SQLite database, through Python's own `sqlite3`, holding every repository's records: `$XDG_STATE_HOME/lup/ledger/ledger.sqlite3` (`LedgerLayout`). The host service is its only writer, and no room mounts it (`docs/inbox.md`, *Parties and items*).
- **Numbers:** `numbered` takes the next one, never taken twice. `kept` given a number the sequence hasn't reached moves the sequence past it, so an item numbered before keeps its number.
- **Versions:** `kept` appends a node's version, and `versions` reads them all. A version whose time isn't after the one before it is refused, so each version says when it was written, and a reader can tell when a thread was renamed or moved. The first lup's ledger copied a node's first time onto every later version, and nothing could tell when a task closed.
- **Names:** `kept` refuses a name another node of the repository holds, and a new name among `taken`, the names of the repository's agents, which the host service knows.
- **Plain records** beside the graph: what's rewritten in place by its name, with no version and no number (`plain`, `rewritten`), read one by its name or several by the start of their names (`plains`). The inbox keeps there:
  - the operator's draft, rewritten at each pause in their typing, which versions would fill with keystrokes; once sent, it's an item. The review's order and what they write on a conversation they read are the same.
  - each conversation's whereabouts, keyed by the conversation's runtime's ids: not numbered, because nothing cites a conversation by number, and the sequence is the operator's to read, where each subagent heard would skip one. A thread's holder is a conversation by those ids too (`Thread.holder`), and where each works is kept on their whereabouts, so threads need no conversation as a node (#353).
- **Attachments** beside the database: what a record carries that's too large for a row, such as an item's diff, a file each under `attachments/`, named by its content's SHA-256 (`attached`, `attachment`). A record names one by its digest, so the same content attached twice is one file, and an attachment a later version replaced stays, read through the version naming it.
- **Indexed, so no read walks the store:**
  - a node's latest version is one row of `nodes`, found by its number, by its repository and kind, by its kind across repositories (`every`, `keeps`), or by its name;
  - its versions are found by its number;
  - an edge is found by the node it's drawn to or from, or by its kind (`drawn_of`): the host service reads every item and where each stands so at its start.

  A test checks every query's plan. A log folded whole at every read hung on 85 MB in the first lup.
- **Threads at once:** the host service answers each hook in a thread of its own. So the store keeps one connection, behind one reentrant lock:
  - each write is one transaction, rolled back where it's refused, so nothing of it is kept;
  - `writing` holds one transaction across several writes, so they're kept together or not at all: within it, each write is a savepoint, undone alone where it's refused;
  - `together` holds the lock across several reads, so they see one state.
- **Synced at checkpoints:** in write-ahead mode with `synchronous = NORMAL`, a transaction reaches the disk at the log's next checkpoint, not at each commit. One is lost to a power cut, never to the service's crash, as the inbox's files, written whole without a sync, were. Syncing each commit would cost a sync at every hook that tells an item.
- **How far it's written** (`written`): its latest version's and edge's places, which a reader holding what it made of the ledger compares to know whether to make it again, as the operator's review reads every thread (`docs/inbox.md`, *Threads in the review*).
- **Copied whole, as one state** (`copied`): through SQLite's backup, under the lock, the write-ahead log folded in, so a copy taken beside the host service's writes opens as this one does; the host sends it to a room for the dashboard's demo to serve (`docs/host.md`, *Reading from a room*).
- **Its tables' version** is kept in the database (`user_version`). A database at an earlier one is brought to this one at opening, in one transaction (`upgrade`); one at a later one is refused.

## Layout

The ledger is a distribution of its own, `lup-ledger`, in lup's uv workspace:
- **`src/lup_ledger/`, its library side:** the records, parties, threads and the root error, `LupLedgerError`, which every error it raises descends from.
- **`src/lup_ledger/environment/`, its environment side:** the store, where it lives, and threads read on it. It imports `lup_dev`.
- **Two import contracts of its own,** in the root `pyproject.toml`: the library side never imports `lup_dev` or `lup_dashboard`, and only `lup_dev` imports the environment side.
- **The extra `lup-ledger[environment]`** brings `lup-dev`, so code using the library side alone doesn't pull in the environment.
- **`tests/`** run with every package's tests.
