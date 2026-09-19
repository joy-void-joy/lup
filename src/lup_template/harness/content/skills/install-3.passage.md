### Settle the seams the target inherits

Everything installed above ships at a default, and a handful of those defaults are places lup holds an opinion the target is meant to overrule. **A default nobody was shown is not a decision** — and it matters more here than in a fresh scaffold, because the target already has conventions of its own, which is exactly what § Guidelines means by respecting them.

Run `uv run --directory <target> lup-devtools dev seams`. It prints each seam, what it holds, and where it is written. Put each to the user:

- **Who owns which files.** A human-owned file surfaces every change as an approval and the agent proposes rather than writes it. Ask specifically about `README.md`: a target whose README is maintained by hand wants it owned, and one that wants the agent writing it says so with `dev seams --disown README.md`.
- **Which trees an edit needs approval into.** Ask what this target actually guards — a migration set, a deployment manifest, a data directory, a generated client — rather than carrying over paths that describe lup's own tree.
- **What each tree is for.** Its test roots, its build products, its scratch. Every gate reads this one answer, so a target whose layout differs and never says so is judged by lup's layout instead of its own.
- **Which scan rules it holds itself to.** The one most likely to be wrong by default: the rules encode conventions this project settled, and a target that settled one differently is not defective there. Offer keeping them, dropping named ones (`dev seams --retire <rule-id>`), or dropping the family outright (`dev seams --retire-all`), and mean all three. `docs/rules.md` in the target lists what each id refuses, so read it with them rather than asking about thirty ids blind.

Then regenerate: `uv run --directory <target> lup-devtools harness generate all`.

## Phase 7: Verify & Report

After installation:

1. **List all files created/modified** in the target repo, marking which ones generation now owns
2. **Show a summary** of what was installed and why
3. **Note what was skipped** and why (especially in non-interactive mode)
4. **Suggest next steps**:
   - Review the installed hooks and adjust patterns
   - Try `{{ meta_skill }}` to review the generated harness trees
   - Run `{{ commit_skill }}` to test the commit workflow
   - Consider `{{ update_skill }}` later for ongoing sync

## Guidelines

- **Respect the target**: Don't impose lup conventions where the target has its own. Adapt to them.
- **Minimal footprint**: In non-interactive mode, prefer doing less. The user can always run with `--interactive` later to add more.
- **No new dependencies**: Don't install anything that requires `pip install` or `npm install` unless explicitly approved in interactive mode.
- **Adapt, don't copy**: Every file needs to be reviewed and adapted for the target's ecosystem.
- **Preserve existing work**: Never overwrite files a harness tree already holds. Merge or extend.
- **Explain decisions**: For each installed item, briefly explain what it does and why it helps.
