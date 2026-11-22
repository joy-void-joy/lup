# Landing

How a finished branch reaches the integration branch: the agent who wrote it lands it, the operator reviews it, their yes puts it on trial in what their lup runs, and once they've lived with it they accept it onto the integration branch, `dev` unless the declaration says otherwise. `Landing` is a module of its own among lup's default modules, and needs the gate (`lup/gate/README.md`).

## Landing a branch

An agent calls `land` with their branch and what its merge will say. It lands where two things hold, and otherwise says what to do and lands nothing:
- **the branch holds the integration branch's tip on the remote:** the agent merged it in, in their worktree, where they resolve a conflict and see what it brought;
- **the gate passed on its files:** a pass recorded for the tree its tip names, with the local layers (`lup gate check`, everything committed).

So `land` runs neither a merge nor the gate: it reads the remote's tip and the pass, and is answered at once. The pass is a room's word on how its gate went, since a room writes the git directory: it steers, and guards nothing, the operator's review being what does. What the gate's steps found on its tip without failing (`lup/gate/README.md`, *Findings*) is filed as frictions of the agent landing it, under `frictions/` and each finding's subject, and shown in its review. It says the `# lup: defer` comments the branch adds, removes and rewords in its Python files against the integration branch it holds, read from each version's text with the code rules' reader (`changed_deferrals`), a deferral moved to another line neither: work left undone shows as it lands, to the agent and in the review. It returns as soon as the landing waits on the operator's review: an item in the agent's conversation, of landing's own kind (`WaitsOnReview`, posted through the inbox), opening on the branch's review and offering the operator's yes on the tip that landed, or declining it. It waits until they answer it, and what came of it is told to the agent at their next call: on trial, declined, or their comment, after which the agent lands it again. Landing again answers the item before, the tip that landed since waiting in its place; an accept is told the same way. A branch landed again puts its new tip before them; what's on trial stays at the tip they said yes to until they say yes to the new one.

`want` asks the operator to accept a branch on trial, saying why, which shows on its line: a branch on trial isn't on the integration branch, so another agent's branch doesn't hold it until it's accepted.

## On trial

`Landings` is the machine's part (`machine=True, shared=True`): only the machine's parts read a repository's store hash-checked, record an approval and restart a project's containers. It keeps each project's landings, a JSON file each, and serves the operator:
- **`review`**, a landing's view: how the gate went on its tip, what a step that tells said (what the rules listed without failing, say), the `# lup: defer` comments it changes, then each file its tip changes, read from each object's own bytes;
- **`yes`** (`done`): the branch goes on trial at the tip whose review they read, which the yes names: one landed again since is refused, a review of its own;
- **`toggle`**: takes a branch on trial out of what runs, or puts it back, as when they want to see whether it's the one causing what they see;
- **`drop`** (`decline`): takes it off trial, or declines a landing waiting, and leaves the branch as it is;
- **`accept`**: merges its reviewed tip onto the integration branch and pushes it.

**What runs is computed, never merged into:** whenever what's on trial changes, `live` is the integration branch's tip on the remote with each branch on trial and picked merged in, by name, at its reviewed tip, from what the machine read of them hash-checked, in a store of its own (`merging.py`). A branch that conflicts with those before it is left out, and shown so, as is one with more than one merge base, and one whose review was read against an integration branch tip that its tip doesn't hold any more; the others run. The remote's tip is read for the ref it names, never one ending as it does (`ls-remote` matches `x/refs/heads/dev` too). The commit is lup's own, never pushed.

**Approved without asking where it's made of what the operator accepted and reviewed:** where the integration branch's tip is the one they last accepted, or in the history of what they approved last, `live` is approved as a landing's yes approves it (`Approvals.landed`), and the project opens at it, its containers restarted without cutting a call. A tip that moved otherwise, a push of their own, isn't: nothing restarts, and lup asks them as it does for any change of the running branch. For lup itself, this is what its project's containers run, the dashboard among them; the machine's own parts change only through the loader's question at the operator's terminal (`lup/hosting/README.md`, *The loader*).

## Accepting

`accept` reads the integration branch's tip on the remote, merges the reviewed tip onto it on the machine, and refuses where it conflicts, naming the files, where the branch landed again since the yes, or where the integration branch doesn't hold what the review was read against: the agent merges it in and lands again. Where the integration branch holds the reviewed tip already, merged another way, nothing is pushed. It commits the merge with the landing's message, by the operator as their git names them, pushes it through the project's `remote` with a lease on the tip it read (`lup/remote/README.md`), so the push passes `Publishing`, `Private` among what hears it, as a room's does, and moves the repository's tracking ref as `git push` would. The accept is kept as soon as the push is made; then it deletes the branch on the remote where it's there at the reviewed tip, and only then, so a branch is never deleted for looking merged in a store a room writes, and says what of that failed, the accept standing. A push goes only from a store holding its own objects alone, no alternates and no link under `objects/`, since it sends every commit the remote lacks: the reviewed tip's history, not only its files, which the review shows. The branch's worktree and local branch are left for its session's end: nothing on the machine removes a room's files.

The integration branch moves only by an accept: `land` never pushes it, and `remote` refuses a room's push to it. The integration branch, the remote and the release branch a project lands on are set by its first landing, and a later one naming others is refused, so code in the project's container can't move where the operator's accept pushes; a branch named as the integration branch or the release branch never lands.

## git on the machine

Every git command runs through git's companion, the repository's store pinned (`Git.pinned`, `lup/programs/git/README.md`): nothing a room planted read, and what git prints read there alone, no submodule fetched or pushed, no index but its own, no shallow file. The gate asks it for the worktree it's typed in (`Git.located`) and the tree its files make (`Worktree.staged`). The machine itself reaches no remote: reading the integration branch's tip, fetching it, pushing an accept and deleting a landed branch go through the project's `remote` (`lup.within`), which holds the operator's SSH agent; a remote reached over HTTPS through a credential helper of their global configuration doesn't push.

`trial` and `review` are the operator's views alone: a project's landings are read by nobody else's call.

## What's left

- The `# lup: defer` comments of a TypeScript file, which need the code rules' engine, on Node, to read: a landing lists a Python file's alone.
- A gate's result shown on the agent's line in the dashboard, beside the review where it's shown now.

## Promises

`promises.py`, git run for real in a temporary directory, since merging is what only git can say: a remote's bare repository and the project's clone of it, where the promise commits as an agent would and runs the gate as an agent does. A branch lands only holding the integration branch and gated; a yes runs the reviewed tip, approved, and a branch toggled out runs no more, nor a commit added after the yes; a branch that conflicts is left out of what runs; what waits and what's on trial show, each with its review, what the gate told among it; accepting pushes the reviewed tip onto the remote's integration branch, which nothing before it moved; a landing waits on the operator in the agent's conversation until they answer it, which the agent is told, landing again answering the one before.
