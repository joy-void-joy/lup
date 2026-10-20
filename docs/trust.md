# Trust on launch

The code that runs on the operator's machine, outside every room, is approved before it runs, since what changes the walls goes through the operator (`DESIGN.md`, *Who it's for*). That's the project's declaration, and the `lup-dev` that judges its sessions' writes and acts with the operator's credentials. There's no install step to remember: a launch asks, the first time and whenever that code changed (`launch/trust.py`, whose docstring has the details).

## Using it

- **A launch asks** where the host zone changed: a summary first (what's approved and why it runs on the host, the commit approved before and the tip, and git's own count of each file changed), then "Show the whole diff?", then "Approve?", each no by default. The first approval on lup's own repository held about 24,000 lines, unusable as a whole diff, so the summary comes first and stays on screen.
- **The question is an item in the operator's inbox,** answered at the launching terminal, in the dashboard, or with `lup-dev inbox answer N`, whichever comes first; the terminal stops asking once it's answered elsewhere. The dashboard shows each file changed whole, with the judge's reading of it.
- **`lup-dev trust`** asks the same with no session after it. Like a launch, it refuses inside an agent's session, so nobody answers their own approval.
- **A push from a room that moves the integration branch** puts the approval of its tip in the inbox, naming the session that pushed, so the operator needn't notice that the code the host runs changed. Their comment on the answer reaches that session.
- **Declined,** the session launches on the copy approved before, and the launch says the tip isn't the code judging it; with none approved yet, nothing launches.

## The host zone

What the host runs for a project (`Zone`, found by `declared`):
- **the declaration,** `lup_project.py` or the package `lup_project/`, and every file of the project it imports, in turn, with the conditions modules its modules name;
- **the `lup-dev` it runs,** as the lockfile resolves it: from the repository's own workspace, as lup's does, its packages' sources, uv's files and the engine's source; or a release from an index, held to its version and its dependencies'. A lock resolving `lup-dev` from git, a URL or a path outside the workspace is refused, since a copy built from git would lack the engine, which is built and never committed;
- **the person's own layer,** by its content (*Trusted by its content*).

**Trusted by its content.** `lup_project.local.py` is Python the host runs, and a room writes the worktree, but git holds none of it. So its content joins the zone: unchanged, it asks nothing; changed, created or removed, its diff is in the summary itself, since git's count can't show a file git doesn't hold. The approval keeps the copy approved, which the judge and a launch read beside the commit's export, never the worktree's. Approved where only the layer changed, nothing is installed and no service restarts.

## Why it's this way

- **Read at the integration branch's tip** (`LUP_INTEGRATION_BRANCH`, `dev` by default), never a branch's own copy. What's approved is what runs, and a commit landing on the tip judges nothing until it's approved.
- **Found without running the project's code.** The tip's files are exported from git's objects, and the declaration is read with `ast`, its imports followed by Python's own path finder, which imports nothing; loading it to find them would run the project's code on the host before the operator was asked. Every import counts, a `TYPE_CHECKING` block's too, since showing more than runs only costs reading. What can't be followed is said with the question.
- **A first approval trusts the zone as it is.** The operator chose it by pulling it; what trust guards is what changes afterwards, through pushes they haven't read. So its files are read by their roles alone, and no engine runs.
- **Exported from git's objects, never with `git archive`,** which applies the repository's `.gitattributes`, so the copy could differ from the diff approved.
- **Each repository's own judge.** The approved copy is installed with `uv tool install` in a place of its own (`Layout.judge`), and each launch's hooks are judged by its repository's copy. So every session is judged by the code approved for its repository, and one project's approval can't replace another's judge. On lup's own repository, the copy is also the user's `lup-dev`, and the host service restarts on it.
- **The judge's reading comes in two passes,** so a type check, seconds on lup's zone, doesn't hold the question up. Before it's asked, each file is read from its parse alone; once it's in the inbox, the host service reads its types and replaces the reading.
- **Two launches asking about the same zone** wait on one approval, and either answer, or the inbox's, reaches both.
