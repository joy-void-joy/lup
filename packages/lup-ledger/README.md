# The ledger: lup's typed graph, and threads

The ledger keeps the work as a typed graph: nodes, the edges between them, and every version of every node. Threads are its first kind. A thread is one concern: what's in it (items, the operator's parts, checks) and where it stands. It's one of the core's submodules, always present. No one writes to it yet: the host service opens it once the inbox's items are its nodes (#345).

## Records

`lup_ledger.records`:
- **A node** (`Node`) has a number from one sequence shared by every node of every repository, cited `@12`. It also has its repository, who wrote it, when, and a name where its kind gives it one (`@dashboard-lag`), unique among its repository's nodes.
  - Who wrote it is the operator or a conversation, the latter known by its runtime's ids (`lup_ledger.parties`). These are the inbox's own parties, field for field, so a record and an item say who they're from alike.
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
  - either, in its types: `Settled.by` is the operator.
- **Where a node stands is read from the edges drawn to it, never stored:** a status kept on a record outlives what justified it. Each node says whether it waits on the operator, given the edges drawn to it (`Node.waiting`).

## Threads

`lup_ledger.threads`. A thread (`Thread`) has:
- a name, which `thread=` takes, and never an agent's in its repository;
- a title;
- the thread it's under, for sub-threads as deep as needed;
- the conversation holding it, or none.

What's in it is edges drawn to it:
- **a member** (`In`): an item, or a check (`Check`), something only the operator can try;
- **a part** of an item, moved in by its id (`Moved`): the operator's words. It counts as a member while its item stays in its own thread;
- **a reference** (`Refers`): an item of another thread that touches this one, shown here as a line pointing at it, and no member;
- **its status** (`Status`), the latest one drawn:
  - parked until the first of its triggers comes: an issue closing, a branch or a commit landing, a conversation ending, a time, or a condition named as `defer`'s `when=` names one;
  - done, in an agent's word, with what to try;
  - settled, which only the operator does;
  - declined;
  - reopened.

`Standing.read` says three things:
- **Where it stands:** as its status says. While it's working or reopened, it waits on the operator where a member does. A check waits until they answer it (`Answered`), and each kind of node answers for itself, so a new kind changes nothing in the reading.
- **What waits on the operator.**
- **Who's on it:** its holder, then each conversation that wrote what's in it.

`Threads`, on the store, reads threads:
- one, by its number or its name, or a repository's;
- those under one;
- who answers for one: its holder, or else the nearest thread above it that somebody holds;
- what's in one, the references to it, and where it stands.

A thread's sub-threads are read from its repository's threads by their `parent`, so a read covers at most one repository's threads.

## The store

`Ledger` is one SQLite database, through Python's own `sqlite3`, holding every repository's records: `$XDG_STATE_HOME/lup/ledger/ledger.sqlite3` (`LedgerLayout`). The host service will be its only writer, and no room mounts it, as with the inbox (`docs/inbox.md`, *Parties and items*).
- **Numbers:** `numbered` takes the next one, never taken twice. `kept` given a number the sequence hasn't reached moves the sequence past it, so an item numbered before keeps its number.
- **Versions:** `kept` appends a node's version, and `versions` reads them all. A version whose time isn't after the one before it is refused, so each version says when it was written, and a reader can tell when a thread was renamed or moved. The first lup's ledger copied a node's first time onto every later version, and nothing could tell when a task closed.
- **Names:** `kept` refuses a name another node of the repository holds, and a new name among `taken`, the names of the repository's agents, which the host service knows.
- **Indexed, so no read walks the store:**
  - a node's latest version is one row of `nodes`, found by its number, by its repository and kind, or by its name;
  - its versions are found by its number;
  - an edge is found by the node it's drawn to or from.

  A test checks every query's plan. A log folded whole at every read hung on 85 MB in the first lup.
- **Threads at once:** the host service answers each hook in a thread of its own. So the store keeps one connection, behind one reentrant lock:
  - each write is one transaction, rolled back where it's refused, so nothing of it is kept;
  - `together` holds the lock across several reads, so they see one state.
- **Its tables' version** is kept in the database (`user_version`), and a database at another is refused.

## Layout

The ledger is a distribution of its own, `lup-ledger`, in lup's uv workspace:
- **`src/lup_ledger/`, its library side:** the records, parties, threads and the root error, `LupLedgerError`, which every error it raises descends from.
- **`src/lup_ledger/environment/`, its environment side:** the store, where it lives, and threads read on it. It imports `lup_dev`.
- **Two import contracts of its own,** in the root `pyproject.toml`: the library side never imports `lup_dev` or `lup_dashboard`, and only `lup_dev` imports the environment side.
- **The extra `lup-ledger[environment]`** brings `lup-dev`, so code using the library side alone doesn't pull in the environment.
- **`tests/`** run with every package's tests.
