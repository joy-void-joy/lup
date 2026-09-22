# Update from Upstream

Three things in this project come from lup, each with a carrier of its own:
the library a pin, the native trees a regeneration, and the copied half —
`src/` and `tests/`, stamped out at initialization — somebody reading
upstream's commits and retyping them. Moved separately they come apart, and a
commit that changes the library *and* its caller arrives as a breakage rather
than as work anybody chose.

One command moves all three to one commit. What is left for a person is what
no command can decide: a merge conflict in a file both sides changed, and a
migration whose instruction is a sentence.

## 1. Commit what is pending

Invoke `{{ commit_skill }}` first. The update merges a branch into this one, and a
merge cannot start over uncommitted work — nor could you tell afterwards which
changes were yours.

## 2. Run the update

```bash
uv run lup-devtools dev update
```

Optionally `--commit <sha>` to pin every carrier at one named commit rather
than at the tip of the branch this project follows.

What it does, in this order, and the order is the whole point:

1. **Resolves the pin** and reads back the commit `uv.lock` got. Everything
   after this is compiled at *that* commit, so the three carriers cannot land
   at three different places.
2. **Syncs the environment**, so the library on disk is the one just pinned.
3. **Compiles upstream's copied half** at that commit onto the `lup-scaffold`
   branch and merges it. The merge base is the commit this project last took,
   which is what makes this an ordinary merge rather than a diff against
   nothing.
4. **Regenerates the native trees**, under the library that just landed.

A conflicted merge stops it before the regeneration, deliberately: the trees
are compiled from declarations the merge has not finished writing. Running it
again after the resolution is what finishes the pass — that run concludes the
merge itself.

**If the pinned branch was deleted**, the update names it before relocking.
Keep the existing lock while checking which surviving branch contains the
work. Fetch the configured upstream and compare the locked commit with the
candidate's history; if commits were rebased, compare their patches rather
than treating matching titles as proof. Ask the user which replacement to
follow. Then run `uv run --no-sync lup-devtools dev library git --branch
<replacement>` and `uv run --no-sync lup-devtools dev update`. A reviewed
commit can instead be selected with `dev update --commit <sha>`. A transport
failure is reported as unconfirmed reachability, never as a deleted branch.

**If this project has never adopted a scaffold branch**, the update says so.
Root one once, at the commit the project was stamped from:

```bash
uv run lup-devtools dev scaffold adopt --base <commit>
```

## 3. Resolve the conflicts it lists

Every conflict is a file upstream changed that this project also changed. Read
both sides and keep both intents — the bias is inclusion, and a rename on one
side must not swallow an addition on the other. `{{ merge_skill }}` carries the decision tree.

Two things are worth knowing before starting:

- **A declaration is where a conflict belongs.** The harness catalog and the
  tool-group list are files this project is *supposed* to have edited, so a
  conflict there is the mechanism working. A conflict anywhere else is worth a
  second look: it usually means something was copied that could have been
  imported.
- **Never resolve a generated tree by hand.** Take either side, run
  `uv run lup-devtools harness generate all`, and let `harness check all`
  confirm it settled.

Resolve every conflict and `git add` the files, then run `dev update` again.
That pass concludes the merge, compiles the copied half against the
declaration your resolution wrote, and regenerates under it — so an upstream
path this project stops declining arrives in the same pass, instead of waiting
for one that could not start until the merge was committed.

## 4. Apply the migrations it lists

A migration is a break two trees cannot describe between them — a signature
that gained required parameters, a refusal that split. The update prints each
one with the reason it was taken and the steps that answer it. A step carrying
a command can be run; a step that is a sentence is a decision about this
project's code, so make it here rather than looking for a command.

Module moves are not in that list and need no decision, being derived. Where
this project holds imports from before a reorganisation, the exact invocation
that repoints them is

```bash
uv run lup-devtools dev migrate map <the-commit-you-came-from>..
```

## 5. Verify, then commit

{{ watch }}

The `carrier drift` row is the one to read: it names the commit the library is
pinned at and the commit the copied half was merged at, and says nothing at all
when they agree.

Then `{{ commit_skill }}`, keeping the merge and any migration work as separate
commits — they are separate claims, and a reader bisecting a regression needs
to know which one carried it.

## Guidelines

- **Nothing here reads upstream's commits.** Reviewing another repository's
  history for what is worth having is the other direction, and it has its own
  skill: `{{ import_skill }}` with no arguments sweeps every tracked project.
- **A defect in lup is fixed in lup.** Working around one in the copied half
  moves this project further from upstream, which is what makes the next update
  expensive. `{{ upstream_skill }}` cuts the fix in a worktree of lup itself.
- **The copied half is merged, never retyped.** If something upstream changed
  is missing here, the scaffold branch did not carry it — say so rather than
  hand-porting it, because a hand-port diverges from upstream permanently and
  silently.
