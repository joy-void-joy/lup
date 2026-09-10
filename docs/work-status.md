<!-- Generated from lup_template.writeups by `uv run lup-devtools ledger writeup` — edit the source, not this file. See docs/harness.md. -->

# Work status

What this repository's coordination ledger still holds to do: the tasks not yet finished, what among them waits on a person and what each costs, and the handoffs nobody has closed. Every row is the ledger's, read at generation with its standing beside it — cite the node, not this page. `ledger delegate` records a task, `ledger mine` renders one holder's, and `ledger show <id>` opens any row.

## Open tasks

| # | What | Standing | Node |
| --- | --- | --- | --- |
| 1 | **[resolve review (packages/lup/src/lup/devtools/dev/resolve_review.py) still renders a static HTML page from Python strings with inline CSS. It becomes a fourth surface under packages/lup/web/, typed against the manifest it renders, built by Vite into the wheel like the explorer, wizard and supervisor. The last web UI outside the stack.](lup:review-page-ts)** — Convert the resolver review page to the TypeScript stack | open | `review-page-ts` |
| 2 | **[ledger explore, dashboard, and resolve supervise against a persisted run, plus the exported explorer page from a file. The pages are type-checked, built, route-tested, and mounted under happy-dom; no human has opened one. Needs a machine with a browser.](lup:browser-smoke)** — Open the three surfaces in a real browser | waiting | `browser-smoke` |
| 3 | **[docs/platform-differentiation.md carries the row and says what settles it. Needs a signed-in Codex session (codex login) on this machine.](lup:codex-queue-wake)** — Measure whether codex queue wakes an idle Codex session | waiting | `codex-queue-wake` |
| 4 | **[The drift check rebuilds the bundles and compares them to what is committed; five worktrees on this machine agree, and a second machine with the same lockfile has not been tried.](lup:vite-determinism)** — Verify the Vite build is deterministic on a second machine | waiting | `vite-determinism` |

## What needs a person

### Accounts to create

- [ ] Measure whether codex queue wakes an idle Codex session — docs/platform-differentiation.md carries the row and says what settles it. Needs a signed-in Codex session (codex login) on this machine.  `fe2634b9e4ab`

### Reviews owed

- [ ] Open the three surfaces in a real browser — ledger explore, dashboard, and resolve supervise against a persisted run, plus the exported explorer page from a file. The pages are type-checked, built, route-tested, and mounted under happy-dom; no human has opened one. Needs a machine with a browser.  `82e200567ada`

## Open handoffs

No handoff is open.

Generated from this repository's ledger: 4 node(s), 0 edge(s); 4 coordination:task; 0 coordination:handoff; newest record 2026-09-10T11:17:58.785054+00:00. Regenerate with `uv run lup-devtools ledger writeup`.
