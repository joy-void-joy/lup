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

| # | What | Standing | Node |
| --- | --- | --- | --- |
|  | **[Two behaviour-preserving refactors of the hermetic policy kernel under packages/lup/src/lup/policy/kernel/, each its own branch and commit. (1) kernel/syntax.py has four loops that walk a string counting delimiter depth: balanced_end (parentheses, depth 1, skips quoted strings and backslash escapes), brace_end (braces, depth 1, skips $( … ) via balanced_end), and the two arithmetic readers near lines 755-830 (parentheses, depth 2, one refusing backticks and $( inside). They differ only in delimiter pair, starting depth, and what they skip; one helper taking the pair and the skip rule replaces all four. (2) kernel/edit.py is 4000 lines and holds the TypeScript span scanner inside masked_typescript_lines: the nested literal_end, regex_end and template_piece readers and the character walk around them, roughly lines 700-830. That scanner belongs in its own kernel module beside syntax.py, the shell grammar, which already is one. The net: the tokenizer tests under packages/lup/tests/unit and tests/unit that import kernel.syntax, and test_antipatterns.py, which imports masked_typescript_lines directly. After either change run harness generate all, since the kernel is copied into both plugins and the drift check refuses a stale copy, and declare any name that changed module in lup.devtools.dev.migrations.DECLARED, which dev migrate check enforces.](lup:27040ab7df1c)** — Fold the shell tokenizer&#x27;s delimiter-depth loops into one helper, and move the TypeScript span scanner into its own kernel module | held | `27040ab7df1c` |
|  | **[Containment is the cause, and the wake mechanism is intact — both demonstrated rather than argued. Two Claude sessions inside one container, sharing one /tmp/cc-socks, discover each other (ListAgents listed the second as &#x27;longprobe [88d4e9] · interactive · busy&#x27;), a native SendMessage to it returned success, and the peer dropped its own work and answered the message. The five peers on this repository&#x27;s roster are unreachable for exactly one reason: each runs in its own container, where /tmp is the container&#x27;s own overlay, so each session&#x27;s socket directory holds only its own socket. Nothing about wake() or the runtime broke; visibility did, when contained launches became the posture on 2026-08-25 (fa3cc672b, hardened ae7ccdad7 and c35a99051). Two earlier conclusions in this record were wrong and are corrected below: the policy stop is not structural, and a same-container probe that saw nobody was blind in one direction only. What is left is three decisions, which are the user&#x27;s: whether to declare a host bridge for the socket directory and how, whether to declare the handle at join, and what shape the policy carve-out takes.](lup:916989542a4c)** — Native SendMessage as the wake for an idle Claude peer: why it never carries today, and what would make it | held | `916989542a4c` |

Generated from this repository's ledger: 6 node(s), 0 edge(s); 4 coordination:task; 2 coordination:handoff; newest record 2026-09-19T15:00:52.019040+00:00. Regenerate with `uv run lup-devtools ledger writeup`.
