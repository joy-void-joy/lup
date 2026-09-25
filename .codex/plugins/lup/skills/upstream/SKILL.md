---
name: upstream
description: Fix a defect in lup itself, in a worktree of lup, and pin it until it lands
---

# Fix It Upstream

**What is wrong:** the arguments supplied with this skill invocation

A defect in lup met from a project built on it has two repairs, and only one of
them is cheap twice. Working around it here puts this project's copy further
from upstream — which is exactly what makes the next update expensive — and
leaves the defect for whoever meets it next. Fixing it in lup costs one
worktree and reaches every project at once.

This is that loop. Nothing in it is unusual except where the work happens: in
a worktree of *lup*, under lup's own gate, while the pin here follows the
branch until it lands.

## 1. Confirm the defect is lup's

Read the code that misbehaves before deciding whose it is. Two things that
look like an upstream defect are not:

- **Something this project copied.** `src/` and `tests/` are this project's
  own, merged from upstream rather than imported, so a fix there is a fix
  here — and if upstream's version has the same flaw, both halves want it.
- **Something this project declared.** A catalog, a tool-group list, a policy
  selection. The library behaves as declared; the declaration is what to
  change.

What is left — library code under `packages/lup/` upstream, or a generated
tree compiled from lup's own declarations — is lup's.

## 2. Open a worktree in the lup checkout

`refs/lup` is the registration `sync` materializes, and a session reaches it
when the project is registered with a writable mount. Cut the branch there,
not here:

```bash
uv run --directory refs/lup/tree/<branch> lup-devtools git worktree create fix-<name>
```

If `refs/lup` does not resolve, this machine has not answered the requirement
`sync.json` declares. `uv run lup-devtools sync status` names what is missing
and the command for it: `sync remote lup <url>` for the URL this machine
fetches from, `sync setup lup /path/to/repo` for a checkout it already has,
then `sync fetch lup`. Both write `sync.json.local`, which is a protected
edit: put it to the user rather than writing it. A registration the tracked
file does not mount is tracked for review and not for writing, and widening
that is a tracked edit and the user's too.

## 3. Make the change under lup's gate

Edit in that worktree, and run **lup's** gate there rather than this project's:

```bash
uv run --directory refs/lup/tree/fix-<name> lup-devtools dev check
```

An explicitly granted destination worktree is judged by its own generated
policy, while this session retains its measured boundary and approval channel.
The launch records the accepted evaluator bytes; a writable parent directory
or a `refs/` symlink alone supplies no repository policy grant.

Generate both native trees in a newly created worktree before editing it.
When the launch explicitly mounted the writable bare lup repository, an
operator can accept that worktree's policy without restarting this session.
From the adopter checkout, the operator runs:

```bash
uv run lup-devtools harness policy-refresh --nonce <launch-nonce> --repository <canonical-worktree-path>
```

The edit gate spells this line whole, with this launch's nonce, whenever it
refuses an edit there under a policy the worktree does not generate; hand it
to the operator as written. This accepts only a worktree inside the original
mount and belonging to that same Git repository. It is also the recovery after accepted generated policy
changes: regenerate there, then have the operator refresh its snapshot. The
requesting agent cannot approve replacement policy itself. A worktree outside
the original mount needs a launch granting that path. Run the upstream gate
even when its hook allows an edit; its checks also cover the completed branch.

Two conventions of lup's that are easy to miss from outside it:

- A capability that goes needs a migration declaring what a caller does about
  it, or lup's own gate refuses the branch.
- Generated trees are regenerated, never hand-edited:
  `harness generate all` before the gate.

Commit there with `$lup:commit`, and push the branch.

## 4. Run this project on the fix

Pin the library at the branch carrying it, and take the whole update — the fix
is only proved by the project that met the defect:

```bash
uv run lup-devtools dev library git --branch fix-<name>
uv run lup-devtools dev update
```

Then re-run whatever failed. A fix that does not resolve it is a fix aimed at
the wrong thing, and the worktree is still open to correct it in.

## 5. Land it, and come back to the branch you follow

Once the fix is merged upstream:

```bash
uv run lup-devtools dev library git --branch <the branch this project follows>
uv run lup-devtools dev update
```

Leaving the pin on the fix branch is how a project ends up following a branch
nobody advances, which reads exactly like being up to date.

## Guidelines

- **The defect goes upstream even when the workaround is tempting.** A
  workaround is a decision this project makes on behalf of every project that
  meets the same defect, and it is the decision nobody else can see.
- **Report friction you cannot repair.** Where the fix needs a decision that
  is not yours, or reproduction is the work, `dev report-friction` files it
  against lup with the command, the error and the recovery cost.
- **One branch, one subject.** The fix and whatever this project does about it
  are two changes in two repositories, and a reviewer of either wants only
  their half.
