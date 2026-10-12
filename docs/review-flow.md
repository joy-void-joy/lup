# Reviews: drafts, submissions, and where reviews are parked

**One sentence:** A change waiting for the operator's review is a draft beside its file, under `.lup/drafts/`, which `lup-dev submit` puts before the operator as one review in the first lup's dashboard, and `lup-dev wait` carries out once it's approved, telling each answer once.

**Superseded.** This drafts flow is superseded by `DESIGN.md`'s proposals (*Sessions*, *Approval*; why in `docs/graveyard.md`, "The drafts flow"). It will be reworked or removed with the judge, in that piece.

**What runs.** Everything here is reached from the command line. No hook writes into a draft, tells an answer or carries out an approval, and lup's tools aren't served to agents. A draft begins when something writes the change at its draft's path and submits it. The operator, or an agent through its shell, submits, waits, lists and replies with `lup-dev`. How the hooks carry what the judge asks to the operator is `docs/judging-writes.md`'s (*Asking the operator*), and this flow isn't on that path.

## Two rules

### Told once, never re-told

Each answer the operator gives (an approval, a decline, a remark) is told to the agent exactly once. Afterwards the agent finds it only when it asks, through `reviews`. A reminder about something already told is noise: it spends the agent's attention and turns, and nothing new is learned from it. Any reminder is the operator's call, never the agent's.

In the code, a wait is where an answer is told. Each submission records whether its ending was told (`Submission.told`) and how many of its remarks were (`remarks_told`), and a wait tells only what's untold. A review withdrawn because the same conversation superseded it counts as told by `submit`'s own result.

**The same holds for the operator: parking a review again is silent.** The first lup's dashboard expires a review an hour after it's parked, and the keeper parks it again (decision 20). That re-park raises no desktop notice and sends no message, and the frozen mark carries over to the new id without one either. The operator was told when the review was first parked, and when an agent first froze on it.

### Nothing approved happens behind the agent's back

The files an agent is working with don't change under it between two of its calls, except by its own hand. An approved change is carried out at a moment the agent chooses: when it waits on the review, with what was applied in the wait's result. Never at an ordinary call, and never by the dashboard, which runs on the host, outside the wall.

In the code, `Desk.wait` is the one place an approval is carried out and told. `Desk.apply` carries one out without telling it, the step a conversation's turn's end would take; nothing calls it outside the tests.

## Modules and public API

All in `packages/lup-dev/src/lup_dev/`.

| Module | What it's for | Public names |
|---|---|---|
| `policy/drafts.py` | Where each draft lives and what lup records of it: beginning, keeping and forgetting one | `Draft`, `Recorded`, `Drafts` (`recorded`, `all`, `of`, `path`, `begin`, `keep`, `forget`), `draft_path`, `drafted`, `escaped`, `unescaped`, `ESCAPED`, `DraftError` |
| `policy/submissions.py` | One worktree's reviews: submitting, waiting, carrying out answers, listing, replying | `Desk` (`submit`, `wait`, `reviews`, `reply`, `apply`); `Caller`, `Offered`; `Submission`, `SubmittedFile`, `Submissions`, `Standing` (`Open`, `Applied`, `Declined`, `Stale`, `Withdrawn`); `Awaited` (`OneReview`, `AnyReview`, `AllReviews`, `FileApplied`); the results `Submitted`, `Waited`, `Told`, `Listing`, `Listed`; `SubmissionError` |
| `review.py` | What reviews share: the operator's answers, and the seam to wherever reviews are parked | `Queue`; `ReviewRequest`, `ReviewedFile`; `Look`, with `Waiting`, `Answered` or `Gone`; `Answer`, `Remark`, `LineComment`; `ReviewError` |
| `legacy_dashboard.py` | Parking reviews in the first lup's dashboard, through its host half | `LegacyQueue`, a `Queue`; `Host`, `Call`, `Export`, `Kept`, `Keeping`, `Notices`, `NotifySend`; and `LegacyDashboard`, the installer's reviewer (`docs/judging-writes.md`, *The judge's review, in the dashboard*) |
| `cli.py` | The command line | `lup-dev submit`, `wait`, `reviews` and `reply`; the hidden `lup-dev review keep` |

**How they fit.** Each command in `cli.py` builds a `Desk` for the worktree holding the current directory, with the judge's `Services` and a `LegacyQueue`. The `Desk` reads drafts through `Drafts`, judges them with the worktree's judge, records submissions in the worktree's store, and parks each review through the `Queue`, which knows it only by its number. `LegacyQueue` turns a `ReviewRequest` into one review in the first lup's dashboard and reads the operator's answer back as a `Look`. Every record the `Desk` keeps changes only under the store's lock, the lock a checkpoint holds.

## Drafts

`policy/drafts.py`.

- **One draft per file, per worktree,** shared by a session and its subagents. Each records the conversation that began it (`Conversation`, from `policy/importers.py`).
- **A draft is written at `<worktree>/.lup/drafts/<path>`** (`CheckoutLayout.drafts`), escaped. A segment of `<path>` that starts with `.` has it written `%2E`, and one that starts with `%` has it written `%25`, so `.claude/settings.json` is drafted at `.lup/drafts/%2Eclaude/settings.json` and every draft's path reads back to one file (`ESCAPED`, `escaped`, `unescaped`). The escaping keeps a draft's path out of any directory a runtime protects, since a runtime may refuse a hook-approved write into one at any depth. Only a segment's first character is escaped, so draft paths read as their files' do. The escaping carries a `# lup: defer` to #43: once lup generates the runtimes' own directories, no agent edits a file in one.
- **`draft_path(worktree, file)`** says where a file's draft is written; **`drafted(worktree, path)`**, its inverse, names the file a path drafts, or the path itself where it isn't a draft. A path outside the worktree, one climbing out with `..`, and `.lup/drafts/` itself refuse (`DraftError`).
- **Why there:**
  - `.lup/` is ignored by git and excluded from the store, so no snapshot, commit or checkpoint sees a draft, and ruff passes over it.
  - pytest and pyright skip directories whose name starts with a dot (pytest's default `norecursedirs` holds `.*`, pyright's default `exclude` holds `**/.*`), and no import path reaches `.lup/`, so a draft never runs.
  - `.lup/**` is scratch in the path roles (`catalog/paths.py`), so a write there is allowed at any size, with no rules at the edit. A draft is judged when it's submitted.
  - The agent's file tools and its shell reach it.
- **What lup records of a draft** (`Draft`, in the store's `drafts.json`, `StoreLayout.drafts`):
  - its file, from the worktree's root;
  - its base: the object id, in the store, of the file's accepted content when the draft began, or that it was last applied as; none where the file didn't exist;
  - the conversation that began it;
  - a rename's old path;
  - the review it was last submitted in.

  The draft's path isn't recorded: it's derived from the file (`Drafts.path`).
- **A draft stands while its file does** (decision 49). `all` and `of(path)` return only drafts whose file stands; `recorded` returns every record, dropped ones included. Deleting the draft's file drops the draft at once; its record stays until something forgets or replaces it.
- **`begin(path, began, copy=False)`** begins the draft of a file, given as the file or its draft's path, its base the file's accepted content. With `copy`, the file as it stands is copied into the draft, for an edit to go on from, unless something is written there already, which stands. Without, the draft is whatever is written at its path. It refuses a file with a draft standing, a `copy` of a file that doesn't exist, and a worktree with no accepted tree, where a draft would have no base. A dropped draft's record is replaced. In production only `submit` begins drafts, never with `copy`.
- **`keep(draft)`** records what changes in a draft's record, in place of its file's: the review it's submitted in, a rename's old path, its base once applied (decision 51).
- **`forget(path)`** removes the draft's file, its record, and the directories left empty under `.lup/drafts/`.
- Every method reads or writes the record, so its caller holds the store's lock.

## Submitting

`Desk.submit(caller, files, why="", *, wait=False, timeout=None)` puts drafts, and files landed as context, before the operator as one review.

- **`Caller`** names who calls: the session, the subagent (blank for the session's own conversation), the call's id, and the working directory relative paths start from.
- **Each `Offered` file** has its `path` (the file or its draft's path, absolute or from the caller's directory), its `context` (what changes in it and why, in the agent's words; required), and for a rename, `renamed_from`, the old path.
- **`why`** says what the whole change does, and heads the review. It's required with several files; with one file and no `why`, the file's context heads it.
- **With `wait`,** it waits on the review in the same call, as `wait` on it does, for at most `timeout`.

What it does, under the store's lock:
1. **Reads each file named** (`Desk.named`):
   - a draft standing for the file is submitted;
   - a draft written at its path with no record is begun there, its base the file's accepted content. That's how the agent asks for the operator's view on a change nothing asks about (decision 17): it writes the new file, or a copy of the file it edits, at `.lup/drafts/<path>`, and submits it;
   - a file with no draft that changed since the caller's session started in the worktree is landed already, and shown as context: its diff since then, with nothing to apply (decision 15). For a caller with no start recorded, the operator's command line, the diff runs from the worktree's `HEAD`. That's how a module comes with its tests.
2. **Judges each draft whole, and each renamed file's removal,** as a change to its file against the accepted content, with the paths the session has approved (decision 60). A finding of lup's rules on any of them refuses the whole submission, every draft's findings listed at the draft's path, and nothing is parked. What the judge asks is listed on the review, file by file. A draft it asks nothing about is reviewed all the same, as asked for anyway (decision 16).
3. **Parks one review** through the `Queue`, as a `ReviewRequest`, first keeping each version submitted at `.lup/review/<n>/submitted/<path>` (`ReviewLayout.submitted`; decision 57). Where it can't be parked, the review's directory is removed and nothing is recorded.
4. **Records the submission,** numbered in the worktree, in the store's `submissions.json` (`StoreLayout.submissions`): the conversation, the heading, and each `SubmittedFile` with its context, its base, the version submitted (an object in the store), its asks, and whether it's context only. A rename is two files: the new one, naming its `renamed_from`, and the old one, deleted. Each draft records the review it's in, and its rename.
5. **Logs each draft's judgement as a verdict** in the repository's verdict log: outcome `ask`, tool `submit`, its reasons the kinds of ask, or `asked-anyway` (decision 58). The answer is logged against them once it's read.
6. **Returns a `Submitted`:** the review's number, its heading, its files, the reviews it superseded, and what waiting told, said in `text()`.

**Superseding** (decision 25). Naming a file again while a review holding it waits supersedes that review. It's withdrawn from the queue, recorded `Withdrawn` ("superseded by review `<n>`, which holds its files"), and its directory removed. The superseding review holds all its files: those named again as they stand, the rest at the version submitted before, with their verdicts. Each file's earlier context comes first, then the one just given. The heading is the latest `why`, else the earlier one, else the first file's context. A review the same conversation submitted counts as told, since the `Submitted` names it; one another conversation submitted is told to that conversation at its next wait.

**It refuses** (`SubmissionError`):
- no files, an empty context, several files with no `why`, or a file named twice;
- a path outside the worktree;
- a draft's path with nothing written there;
- a file that's neither a draft nor changed since the session started;
- a draft whose file changed since it began (its base isn't the file's accepted content), since the review would show the draft undoing that change (decision 59);
- a rename whose old path isn't a file, or has a draft of its own, and a landed file named as a rename;
- a draft with findings of lup's rules.

**A worktree no session has reached** has no accepted tree; submitting there accepts it as it stands, as a session's start does (`Desk.accepted`; decision 61).

## Waiting

`Desk.wait(caller, awaited, timeout=None)` holds until what it waits on has something to tell, then tells it.

| `Awaited` | What it waits on |
|---|---|
| `OneReview(number)` | One review |
| `AnyReview(numbers)` | The first of several to end |
| `AllReviews()` | Every review of the calling conversation with something untold, until all have ended |
| `FileApplied(path)` | The review submitted last that changes the file, read again at each look, so a resubmission is followed. It ends at a decline too (decision 55) |

- **At each look,** under the store's lock, it reads each waiting review's state and remarks from the queue (`Queue.look`) and acts on the answer (*Carrying out an answer*). Every approval it reads is carried out there and then.
- **It ends** when a review it waits on has ended and isn't told yet (for `AllReviews`, once every one has ended), when the operator remarked on one still waiting (decision 54), when nothing it waits on is waiting, or at its timeout.
- **It holds at most `Desk.patience`,** 23 hours and 55 minutes, a little under the day a runtime gives a tool call, looking every 2 seconds (`Desk.poll`) on the judge's `Clock`. Before its first sleep, it marks each review still waiting as one an agent is frozen on (`Queue.frozen`). A wait with no time to hold marks nothing.
- **It returns a `Waited`:** a `Told` for each ending and remark it told, the reviews still waiting, and those that ended and were told before. Its `text()` says each, then what still waits, or that there's nothing to wait on.
- **What a wait tells is recorded as told,** so no later wait tells it again. Whichever caller's wait reads an answer is the one told it: a wait isn't limited to the caller's own reviews, except with `AllReviews`.

What each ending says:
- **applied:** "The operator approved review `<n>`, and it's applied", with the files written and removed, the operator's note and line comments, and for each draft edited since it was submitted, that it stays, holding only the later edits;
- **declined:** nothing changed, where the drafts stand, and to revise and submit them again, or answer with `reply`;
- **stale:** approved, but nothing applied, naming the files that changed, and to bring the drafts up to date;
- **withdrawn:** why;
- **a remark on a review still waiting:** what the operator wrote, and that the agent may answer with `reply`.

## Carrying out an answer

What `Queue.look` reads is acted on once (`Desk.settled`).

### Approval

Carried out in one step under the store's lock (`Desk.carried`):
1. **Check** that each file the review changes still holds what it was submitted over. Where one doesn't, nothing is applied: the review is `Stale`, naming the files, its answer logged `approved`, and the queue lets it go.
2. **Write** each version submitted, and delete what the change deletes, a rename's old path included: all or none. Each version is written again from the store under `.lup/review/<n>/submitted/`, then moved into place, keeping the file's mode, so a copy edited in the worktree is never what's applied. Where a move fails, the files moved already are put back, and the wait fails, saying nothing changed.
3. **Accept** the paths as they now stand in the worktree's accepted tree, every other change left for the next checkpoint (`Desk.accept`: `Store.snapshot`, `changed`, `unstage`, `accept`), so no checkpoint of any session judges them again (decision 48). The submitting session's record, where there is one, gets the paths as approved, so the approval covers their design asks for that session, and as touched by the conversation, so its turn's end checks them.
4. **Record** the review as `Applied`, and log its answer, `approved`, against its verdicts.
5. **Settle each draft:** one still equal to its version submitted, or dropped, is forgotten; one edited since stays, its base the version applied, so it holds only the later edits.
6. **Remove** `.lup/review/<n>/`.
7. **Ask for the importers pass** on the applied files the rules check, for the submitting conversation.
8. **Spend** the approval where the review is parked (`Queue.spend`), so the dashboard shows it carried out. This comes last, once lup's own record says the review is applied: where spending fails, the failure is raised, and the review stays applied, told at the next wait.

### Decline

Nothing on disk changes. The file was never touched, and the draft is the agent's version, still where it was (decision 23). The review is `Declined`, with the operator's note and comments, its answer logged `declined`, and the queue lets it go ("declined, and the answer read"; decision 56). The versions submitted stay under `.lup/review/<n>/submitted/`, where after-side comments count their lines. The agent revises the draft and submits it again, or answers with `reply`.

### A review gone from the queue

A review that left the queue unanswered (`Gone`, with the queue's reason) is recorded `Withdrawn` with that reason, logged `unanswered`, and let go.

### Edits after submitting

The approval applies the version submitted, whatever the draft holds by then (decision 24). Edits made after submitting stay in the draft, and the review doesn't change. To show the operator the newer version before they answer, the agent submits the file again, which supersedes the review.

### Remarks and line comments

- **A remark** (a note or comments the operator sends before deciding) ends a wait, and is told once, with the review still waiting.
- **Each comment is anchored to lines of one file,** on its before or after side (`LineComment`), and said as `path:first-last (side): note`, with the file's path in full.
- **An after-side comment counts lines in the version submitted.** Where the draft moved on since, the message says so, naming where that version stands: under `.lup/review/<n>/submitted/`, or the file itself once applied.

## Listing and replying

- **`Desk.reviews(conversation=None)`** lists a conversation's drafts (those it began) and reviews, or with none, the whole worktree's, as a `Listing`. A review still waiting is looked at in the queue, so the listing can say "approved, not yet applied: it applies when it's waited on", "declined, not yet told" or "gone from the queue, not yet told". Nothing is told or carried out.
- **`Desk.reply(caller, number, text)`** answers the operator in the thread of a review still waiting: any of the caller's session's, a worker's included (decision 62). It settles nothing. Another session's review, or one that ended, refuses.
- **`Desk.apply(number)`** carries out a review's approval, read from the queue, without telling it: the review stays untold, for a later wait. A review that isn't waiting, or isn't approved, refuses.

## The queue

`review.py` is the seam. Whatever parks reviews answers to `Queue`, so the `Desk` never knows where a review waits, and the queue knows a review by its number in the worktree (decision 38).
- **`ReviewRequest`:** the number, who asks (the session, and the subagent where there is one), the heading, and the files (decision 36). Each `ReviewedFile` has its path, its text before and after (none where the change creates or deletes it), its context, its asks, and whether it's landed. Whether the change creates, overwrites or deletes the file is read from the two sides (`kind()`); its standing from `asks` and `landed`: asks listed, the judge asks; none, the agent asked anyway; landed, context. A file with no text on either side, or one landed with asks, refuses.
- **`Look`:** the review's state, `Waiting`, `Answered` with the `Answer`, or `Gone` with why, and every remark sent on it, oldest first (decision 37). Telling each once is the caller's.
- **`Answer`** (approved, a note, line comments), **`Remark`** (a note, line comments) and **`LineComment`** are also what the installer's review reads (decision 33).
- **`Queue`'s six methods** (decision 35):
  - `park`: put a review before the operator, telling them once;
  - `look`: how it stands, with what the operator sent on it;
  - `spend`: record its approval as carried out, and let it go;
  - `withdraw`: take it out, saying why;
  - `reply`: say something in its thread as whoever asked, settling nothing;
  - `frozen`: mark it as one an agent is frozen on, telling the operator once.
- **`ReviewError`** is raised where reviews are parked, by the queue and by the installer's reviewer.

## The first lup's dashboard

`legacy_dashboard.py` parks reviews in the first lup's dashboard, where the operator reads them until lup's own dashboard exists. It holds two reviewers, both through `Host`: `LegacyDashboard`, the judge's own review that `lup-dev install` waits on (`docs/judging-writes.md`), and `LegacyQueue`, the reviews submitted from a worktree. Only `cli.py` imports it.
- **`Host`** is the first lup's host half (`packages/lup/src/lup/policy/assets/host.py` in its checkout). It uses only the standard library, so it's loaded by path, and the dashboard reads exactly the records it writes. Its answers are modelled here (`Parked`, `Entry`, `HostAnswer`, `RecordedReply` and the rest), read against the host at `40c2d28`.
- **The first lup's checkout is found as the interim review hook finds it** (`legacy_checkout`): `LUP_INTERIM_REVIEW_LEGACY_CHECKOUT`, read from the directory holding the repository's git directory. Where the host half isn't there, parking refuses, naming the setting.
- **A review is one `Propose`** (decision 19): each file whole after the change, its text before recorded as the review's precondition. The before side is exported to `.lup/review/<n>/before/` (`Export`, `ReviewLayout.before`), and the review records each file there, since the dashboard retires a waiting review whose recorded files don't stand on disk as recorded. Line comments come back from the export to the worktree's paths.

### `LegacyQueue`

- **`park`** writes the export, parks the `Propose`, and records it in the store's `parked.json` (`Kept`: what parks it, every id the dashboard gave it, and whether an agent froze on it; `StoreLayout.parked`, under `parked_lock`). It raises a desktop notice, "A change waits for your review", and starts the keeper unless one runs. A number parked already refuses, as does a review the host won't park as waiting; its export is removed then.
- **`look`** reads the answer on the id the review stands under, and the remarks on every id it was parked under. A review the dashboard expired still reads as waiting, since the keeper parks it again; one that left otherwise, or isn't in the relay, is `Gone`.
- **`spend`** spends the approval through the host, as the first lup's agents spend one by repeating their call (`docs/judging-writes.md`, decision 110), so the dashboard shows it carried out, then removes the export and the record. A review not approved refuses.
- **`withdraw`** records the first lup's own cancel through the host half where the review still waits (`transition_relay_entry`, with `withdrawn: <why>` as its outcome; decision 40), then removes the export and the record. Removing the export alone isn't enough: a file the change creates is recorded as absent, and still stands as recorded once the export is gone, so a review of created files would stay answerable.
- **`reply`** appends the first lup's reply record to the relay (`append_relay_records`), as whoever asked, on the id the review stands under (decision 41). An empty reply refuses.
- **`frozen`** marks the review, the first time only, with a reply in its thread, "An agent is frozen on this review: it waits for your answer before going on.", and a desktop notice, "An agent waits on your review" (decision 27).
- **The keeper** (`keep`; decision 20) runs as the hidden `lup-dev review keep <worktree>`, started by `BackgroundSpawner` and printing to the store's `keeper.log`. One runs per worktree, holding `keeper.lock` for its life. Every 15 seconds it parks each review the dashboard expired again, under another id, silently; a frozen mark is said again under the new id, without a notice. It stops once every review is answered or gone, releasing its lock under the record's guard, so a review parked as it stops starts another keeper.
- **Desktop notices** go through `notify-send` (`Notices`, `NotifySend`; decision 44). Where it isn't installed, none is raised; one that fails is said on standard error, and the review stands parked.

### What the operator sees

One review per submission, headed by its `why`, then a line saying how an approval is carried out and where each file's before side is. That line says an approval applies "when the agent next waits on it or ends its turn"; only a wait carries one out. Each file is a fold whose header gives its context, then its standing: "Needs your review: `<asks>`.", "Nothing here asks for review; the agent asked for your view.", or "Context, already landed: nothing here is applied." Inside is the whole diff. Drafts never appear.

## The command line

`cli.py`. Each command builds a `Desk` for the worktree holding the current directory (`desk`), with the judge's services and a `LegacyQueue` (`queue`). It calls as the operator, a conversation of its own: `Caller(session="operator", call=<a token of its own>, cwd=<where it runs>)` (decision 46). An agent running these commands through its shell submits as the operator too.
- **`lup-dev submit [--why TEXT] [--wait] [--timeout T]`** reads its files as JSON on standard input, the list `Desk.submit` takes: `[{"path": …, "context": …, "renamed_from": …}]` (decision 47). Its help says where a draft is written and how its path is escaped.
- **`lup-dev wait [N…] [--any] [--all] [--file PATH] [--timeout T]`** takes exactly one form: one review by its number, several with `--any`, `--all` for every review submitted from the command line in the worktree with something untold, or `--file`.
- **`lup-dev reviews`** lists the whole worktree's drafts and reviews.
- **`lup-dev reply N TEXT`** answers in the thread of a review submitted from the command line.
- **A timeout** is `HH:MM:SS` or ISO 8601 (`PT30M`), read by pydantic.
- **`lup-dev review keep <worktree>`,** hidden, runs the keeper.

## Where things live

| Place | What |
|---|---|
| `<worktree>/.lup/drafts/<path>` | Each draft, its path escaped |
| `<worktree>/.lup/review/<n>/submitted/<path>` | Each version submitted, until it's applied |
| `<worktree>/.lup/review/<n>/before/<path>` | The before side, while the review is parked in the first lup's dashboard |
| The worktree's store (`StoreLayout`, outside the worktree): `drafts.json`, `submissions.json` | The records of drafts and submissions, under the store's lock |
| The store: `parked.json`, `parked.lock` | What's parked in the first lup's dashboard, under its own lock |
| The store: `keeper.lock`, `keeper.log` | The running keeper's lock, and what it prints |
| The repository's verdict log | Each draft submitted, and its answer |

## Tests

In `packages/lup-dev/tests/`, with nothing reaching a real dashboard, desktop or clock:
- **`test_drafts.py`:** escaping and reading back, beginning a draft for a write or an edit, a file being created, a draft written before it began, dropping by deleting, forgetting, renames.
- **`test_submissions.py`:** the `Desk` against a `FakeQueue` and the test kit's clock. Parking, verdicts, context files, refusals, asking anyway, superseding, an approval whole or not at all, stale, decline, the wait's forms, its timeout and patience, told once, remarks, renames, edits after submitting, listing, replying, `apply`, a worktree no session reached, and the command line through typer's runner with the services and the queue patched.
- **`test_legacy_dashboard.py`:** the queue and the installer's reviewer against a stand-in host half written into a stand-in checkout of the first lup, with the test kit's clock and a stand-in `notify-send`. Parking, looking, spending, withdrawing, replies, the frozen mark, the keeper and the notices.

## Decisions

Each keeps the number the code and this note cite it by, with its alternatives.

- **2. Drafts live at `.lup/drafts/<path>`, a segment's starting `.` written `%2E` and a starting `%` written `%25`.** *Alternatives:* lup's state directory outside the worktree, which the agent's file tools can't reach without a mount; `tmp/drafts/`, which mixes drafts into the agent's scratch; unescaped paths, which Claude Code refuses under `.claude/` or `.git/`; a flat numbered name per draft, safe but unreadable; percent-encoding whole segments with `urllib.parse.quote`, which never escapes a dot and escapes spaces and every character outside ASCII, so a draft written by hand wouldn't be found where lup looks. *Where:* `policy/drafts.py`, `layout.py`.
- **3. One draft per file per worktree,** shared by the session and its subagents. *Alternative:* per session, which loses drafts when a resumed or forked session gets another id, and hides a worker's drafts from the session landing its branch. *Where:* `policy/drafts.py`.
- **15. A landed file named in a submission is shown as context,** its diff since the session started, nothing applied. *Alternative:* drafts only, so a module reaches the operator without its tests beside it. *Where:* `policy/submissions.py`.
- **16. Every draft submitted goes to the operator,** with its asks or as asked for anyway, and a finding of lup's rules refuses the whole submission. *Alternatives:* apply at once a draft that no longer asks, which would land an asked-anyway change unreviewed; let files with findings go stale in the dashboard. *Where:* `policy/submissions.py`.
- **17. A change becomes a draft on purpose by being written at its draft's path,** or copied there first for an edit. *Alternatives:* a tool that copies a file into its draft and returns the path, sparing the agent the escaping; a submit option naming files to draft as they stand. *Where:* `policy/submissions.py`, `cli.py`.
- **19. A review is parked in the first lup's dashboard as one `Propose`,** its before side exported to `.lup/review/<n>/before/`, apart from the versions submitted. *Alternative:* record the before side at the file's own path, so the page shows the real path and the dashboard retires the review if the file moves, but nothing can then withdraw it, which superseding needs. *Where:* `legacy_dashboard.py`, `layout.py`.
- **20. A keeper keeps each review in the first lup's dashboard past its hour,** started by parking unless one runs, one per worktree under a lock, parking expired reviews again silently and stopping once nothing waits. *Alternatives:* park again only when a wait looks, so the review of an agent that's gone idle vanishes after an hour; put sessions on the first lup's roster, which couples lup to its coordination; `submit` starts the keeper, which ties submissions to the first lup's dashboard. *Where:* `legacy_dashboard.py`, `policy/importers.py`, `cli.py`.
- **23. A decline leaves the draft where it is,** its note and comments told once and kept with the submission. *Alternative:* move the draft to `.lup/saved/`, as a refusal saves a version. *Where:* `policy/submissions.py`.
- **24. Edits after submitting stay in the draft;** the approval applies the version submitted, and a draft edited since stays with only the later edits. *Alternatives:* refuse writes to a draft while its review waits, which stops the agent; apply the newest draft, which the operator never saw. *Where:* `policy/submissions.py`, `policy/drafts.py`.
- **25. Submitting a file again while its review waits supersedes the whole review.** *Alternatives:* refuse until it's answered; withdraw only the files named again, splitting what was submitted together. *Where:* `policy/submissions.py`.
- **27. The frozen mark is a reply in the review's thread and a desktop notice,** said once and carried to each id the review is parked under afterwards, even once the wait that froze ends, since the first lup's thread can't take a reply back. Only the mark carries over; the agent's own replies stay on the id they were written on. *Alternatives:* park the review again with its heading marked, which gives it another id and loses comments the operator was drafting; carry every reply over; mark only while a wait holds. *Where:* `legacy_dashboard.py`.
- **33. `Answer`, `Remark` and `LineComment` live in `review.py`,** shared by submissions and the installer. *Alternative:* `policy/submissions.py` imports them from `install.py`, tying submissions to the installer. *Where:* `review.py`.
- **35. `Queue` is one ABC of six methods, with an `ignore` on `interface-shape`,** which allows one to three. *Alternatives:* three methods, `park`, `look`, and one taking what the asking side says (spent, withdrawn, a reply, frozen) as data; two ABCs, parking and the thread. *Where:* `review.py`.
- **36. A `ReviewedFile`'s kind is read from its two sides, and its standing from `asks` and `landed`.** *Alternatives:* the kind as a field, which could disagree with the sides; the standing as a union of three models. *Where:* `review.py`.
- **37. `look` returns the state as one of three models, and the remarks apart from the answer.** *Alternatives:* one model with a state word and optional fields; the remarks merged into the answer's note. *Where:* `review.py`, `legacy_dashboard.py`.
- **38. The queue knows a review by its number in the worktree;** the dashboard's ids, another at each park after an expiry, stay inside `LegacyQueue`. *Alternative:* callers hold the dashboard's id, which changes every hour. *Where:* `legacy_dashboard.py`, `layout.py`.
- **40. Withdrawing records the first lup's own cancel through its host half,** then removes the export. *Alternatives:* remove the export only, which leaves a review of created files answerable; a sentinel file recorded as a precondition, which the page doesn't show. *Where:* `legacy_dashboard.py` (`Host.cancel`, `LegacyQueue.withdraw`).
- **41. A reply is appended with the host half's `append_relay_records`,** as the first lup's own relay appends one: it holds the relay's lock, writes its heading on an empty log, and reopens a log rewritten under it. *Alternatives:* `append_review_record`; no replies until lup's own dashboard; the first lup's own `review reply` command, which runs its whole package. *Where:* `legacy_dashboard.py` (`Host.reply`).
- **44. A desktop notice goes through `notify-send`;** where it's missing none is raised, and one that fails is said on standard error. *Alternative:* refuse the park when the notice fails. *Where:* `legacy_dashboard.py`.
- **46. The command line calls as the operator,** a conversation of its own named `operator`. *Alternatives:* the user's login name; `--session` and `--agent` options to act for a session, which nothing tells an agent; the runtime's session id read from the environment its commands get, which only an adapter may name. *Where:* `cli.py`.
- **47. `lup-dev submit` reads its files as JSON on standard input,** with `--why`, `--wait` and `--timeout` as options. *Alternatives:* one file per call, which can't put several files in one review; repeated `--file` and `--context` options paired by position, with nowhere for one file's `renamed_from`; a directory with a manifest. *Where:* `cli.py`.
- **48. An applied approval moves the files into the accepted tree.** *Alternative:* record them as judged in the session's record, which only that session's next checkpoint reads: another session's checkpoint, or an approval applied from the command line, would judge the applied files as a shell write and put a created module back. *Where:* `policy/submissions.py` (`Desk.accept`, `Desk.carried`).
- **49. A draft's path is derived, never recorded, and a draft stands while its file does,** so deleting the file drops the draft at once. *Alternatives:* the draft's path as a field of `Draft`, which could disagree with its file's; a record that stands until forgotten, with a `drop` tool or command, one more name for an `rm`. *Where:* `policy/drafts.py`.
- **51. `Drafts.keep(draft)` records any change to a draft's record in its place.** *Alternative:* a method for each change. *Where:* `policy/drafts.py`.
- **52. The behaviour is the methods of a `Desk`,** one worktree's reviews, holding its `Worktree`, the judge's `Services` and its `Queue`. Reviews are numbered per worktree, and a wait, a listing and a reply look at the caller's worktree. *Alternatives:* free functions taking the three each time; the records of every worktree a session holds. *Where:* `policy/submissions.py`.
- **53. `wait` takes an `Awaited` and a timeout,** holds at most a little under a day, polls every 2 seconds, and marks each review it holds on as frozen once, before its first sleep. *Where:* `policy/submissions.py`.
- **54. A remark ends a wait,** told once with the review still waiting, so the agent can `reply` and wait again. *Alternative:* hold until the answer and tell the remarks with it, which leaves an agent frozen on a question it can't see. *Where:* `policy/submissions.py`.
- **55. A wait on a file returns at a decline,** so the agent isn't frozen on work only it can do. *Alternative:* keep waiting across a decline until a resubmission of the file is approved. *Where:* `policy/submissions.py`.
- **56. A decline, a stale approval and a review gone from the queue are each let go through `Queue.withdraw` once read,** with why; a declined review's versions submitted stay for its comments. *Alternatives:* leave a declined review parked, its record and export kept for good; a seventh `Queue` method letting an answered review go. *Where:* `policy/submissions.py`.
- **57. The versions submitted are kept at `.lup/review/<n>/submitted/<path>`,** apart from the export's `before/`, and applying writes each there again from the store before moving it into place. *Alternative:* each at its own path under `.lup/review/<n>/`, which a file under a top-level `before/` would share with the export. *Where:* `layout.py`, `policy/submissions.py`.
- **58. Each draft submitted is logged as a verdict,** `ask` from the tool `submit`, and its answer logged against it (`approved`, also for a stale approval; `declined`; `unanswered` for a review gone). *Alternatives:* log nothing until drafts have their own outcome; log an asked-anyway draft as the `allow` its judgement gives, counting reviewed files among allowed writes. *Where:* `policy/submissions.py`.
- **59. Submit refuses a draft whose file changed since it began.** *Alternative:* submit it against the accepted content, so the review shows the draft undoing the other change. *Where:* `policy/submissions.py`.
- **60. A draft is judged as a change against the accepted content, not as a whole-file write,** so a draft made by a `Write` over a file doesn't list the whole-file ask; it goes to the operator all the same. *Alternative:* record how each draft began, to ask as its first write would. *Where:* `policy/submissions.py`.
- **61. Submitting in a worktree with no accepted tree accepts it as it stands,** so the command line works where no session has been. *Where:* `policy/submissions.py` (`Desk.accepted`, `Desk.since`).
- **62. `wait`'s `AllReviews` and `reviews` take the calling conversation's reviews; `reply` takes any of the caller's session's,** so a session answers on a worker's review. *Alternative:* the conversation's only, for `reply` too. *Where:* `policy/submissions.py`.
