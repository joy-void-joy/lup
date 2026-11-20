# Landing

How a finished branch reaches the integration branch: the agent who wrote it lands it, the operator reviews it, their yes puts it on trial in what their lup runs, and once they've lived with it they accept it onto the integration branch, `dev` unless the declaration says otherwise. `Landing` is a module of its own among lup's default modules, and needs the gate (`lup/gate/README.md`).

## Landing a branch

An agent calls `land` with their branch and what its merge will say. It lands where two things hold, and otherwise says what to do and lands nothing:
- **the branch holds the integration branch's tip on the remote:** the agent merged it in, in their worktree, where they resolve a conflict and see what it brought;
- **the gate passed on its files:** a pass recorded for the tree its tip names, with the local layers (`lup gate check`, everything committed).

So `land` runs neither a merge nor the gate: it reads the remote's tip and the pass, and is answered at once. It returns as soon as the landing waits on the operator's review, and their answer reaches the agent as a message: a yes, or their comment, after which the agent lands it again. A branch landed again puts its new tip before them; what's on trial stays at the tip they said yes to until they say yes to the new one.

`want` asks the operator to accept a branch on trial, saying why, which shows on its line: a branch on trial isn't on the integration branch, so another agent's branch doesn't hold it until it's accepted.

## On trial

`Landings` is the machine's part (`machine=True, shared=True`): only the machine's parts read a repository's store hash-checked, record an approval and restart a project's containers. It keeps each project's landings, a JSON file each, and serves the operator:
- **`review`**, a landing's view: how the gate went on its tip, what a step that tells said (what the rules listed without failing, say), then each file its tip changes, read from each object's own bytes;
- **`yes`** (`done`): the branch goes on trial at the tip they reviewed;
- **`toggle`**: takes a branch on trial out of what runs, or puts it back, as when they want to see whether it's the one causing what they see;
- **`drop`** (`decline`): takes it off trial, or declines a landing waiting, and leaves the branch as it is;
- **`accept`**: merges its reviewed tip onto the integration branch and pushes it.

**What runs is computed, never merged into:** whenever what's on trial changes, `live` is the integration branch's tip on the remote with each branch on trial and picked merged in, by name, at its reviewed tip, from what the machine read of them hash-checked, in a store of its own (`merging.py`). A branch that conflicts with those before it is left out, and shown so; the others run. The commit is lup's own, never pushed.

**Approved without asking where it's made of what the operator accepted and reviewed:** where the integration branch's tip is the one they last accepted, or in the history of what they approved last, `live` is approved as a landing's yes approves it (`Approvals.landed`), and the project opens at it, its containers restarted without cutting a call. A tip that moved otherwise, a push of their own, isn't: nothing restarts, and lup asks them as it does for any change of the running branch. For lup itself, this is what its project's containers run, the dashboard among them; the machine's own parts change only through the loader's question at the operator's terminal (`lup/hosting/README.md`, *The loader*).

## Accepting

`accept` reads the integration branch's tip on the remote, merges the reviewed tip onto it on the machine, and refuses where it conflicts, naming the files: the agent merges it in and lands again. It commits the merge with the landing's message, by the operator as their git names them, pushes it with a lease on the tip it read, and moves the repository's tracking ref as `git push` would. Then it deletes the branch on the remote where it's there at the reviewed tip, and only then, so a branch is never deleted for looking merged in a store a room writes. The branch's worktree and local branch are left for its session's end: nothing on the machine removes a room's files.

The integration branch moves only by an accept: `land` never pushes it, and the credentials' broker refuses a room's push to it (#3).

## git on the machine

Every git command runs through `Git` (`lup/hosting/git.py`), pinned to the repository's common git directory, nothing a room planted read, and what it prints read there alone.

## What's left

- The landing's item waiting on the operator in the agent's conversation, once the inbox takes a module's item (#8): until then, what waits is read in `lup landing trial`.
- The `# lup: defer` comments a landing adds and removes, through #9's reader.
- A gate's result shown on the agent's line in the dashboard, beside the review where it's shown now.

## Promises

`promises.py`, git run for real in a temporary directory, since merging is what only git can say: a remote's bare repository and the project's clone of it, where the promise commits as an agent would and runs the gate as an agent does. A branch lands only holding the integration branch and gated; a yes runs the reviewed tip, approved, and a branch toggled out runs no more, nor a commit added after the yes; a branch that conflicts is left out of what runs; what waits and what's on trial show, each with its review, what the gate told among it; accepting pushes the reviewed tip onto the remote's integration branch, which nothing before it moved.
