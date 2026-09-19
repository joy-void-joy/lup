Every later phase reads this checkout, and step 9 baselines the target's sync
checkpoint at its HEAD. Nothing here may move it, so if the answer was the
stable branch it is standing on the wrong one: stop and say so, and let the
work be re-run from a checkout of that branch rather than installing one branch
while recording another.

If `{{ arguments }}` is empty, use defaults: target=`..`, non-interactive.

## Phase 1: Analyze Source Repo (Lup Template)

Inventory what the lup plugin offers. Read these key files in the **current** repo (`.`):

### Plugin Structure

One declaration set renders into every harness tree the repo commits, so each
capability below exists once per tree:

| Capability | Where it lands |
| --- | --- |
| Plugin identity | {{ manifest_path }} |
| Hook definitions, dispatcher, and hermetic policy runtime | {{ hooks_path }} |
| Skills | {{ skills_path }} |
| Agents | {{ agents_path }} |
| Guidance template | {{ guidance_template_path }} |

### Reusable Library Code

- `packages/lup/src/lup/` — utilities (trace, hooks, metrics, mcp, retry, notes, history, paths)
- `lup.workspace.paths.agent_version()` — version tracking pattern (reads `[tool.lup] agent_version` from pyproject.toml)

### How the Target Obtains Lup

