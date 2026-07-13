# Dev-tooling decisions (from /lup:resolve)

Recorded outcomes for concerns that were decided but deferred, or resolved without code changes. Full analyses were produced under `tmp/` during the resolve run (2026-06, salvaged from `review/resolve-620ff88`); the durable substance is captured here. Counts marked with an as-of date are snapshots — re-measure before acting on them.

## Linter migration (DEFERRED to a focused session)

Replace the regex anti-pattern hook + bespoke `# lup: ignore` with a real linter and typed `# noqa` suppressions. Phased:

- **Phase 1** — Enable the ruff rule families that already implement the wanted rules: `B` (bugbear → B006 mutable default args), `G` (→ G004 f-string in logging), `ANN` (→ ANN401 no `Any`); `E711` (`== None`) is on by default. Add a `[tool.ruff.lint] select = […]` block (the config still selects nothing custom as of 2026-07), run ruff repo-wide, fix genuine hits, and `# noqa: CODE` the legitimate boundaries — this is where the `# lup: ignore` markers (237 in library + template source as of 2026-07, of which 31 still untyped) begin migrating to typed `# noqa`.
- **Phase 2** — A small lup AST plugin (flake8 plugin or standalone checker; ruff has no stable custom-rule API as of this writing) for the lup-specifics ruff lacks: no `__all__`, no `_`-prefix, BaseModel-not-dataclass, structured-parse smells (`.strip`/`.split`/`.replace` used for parsing), backend `match`. Rules `LUP00x`, suppressed by `# noqa: LUP00x`.
- **Phase 3** — Rewire the edit hook to run ruff (+ the lup plugin) on proposed content instead of regex matching, and retire `# lup: ignore`.

This subsumes the anti-pattern notes (auto_allow_edits.py) and the ignore-direction note (CLAUDE.md "remove all ignores", utils.py "audit for missing ignores").

### Anti-pattern hit-counts (verified as of the 2026-06 audit)
- `== None`/`!= None`, f-string-in-logging, mutable default args: **0** instances — clean regression guards.
- `os.environ`/`os.getenv`: **5** real boundary uses (config.py, claude/run.py, paths.py) — would each carry a `# noqa`.
- `.strip(`: **106** — too blunt as a flat regex; in Phase 2 it becomes an AST rule that distinguishes whitespace-stripping from parse-stripping.
- `dict`/`object` bare annotations, `BaseModel`: noisy as flat regex (untyped constructors everywhere) — Phase 2 AST rules.

## Ignore-direction (DECIDED, realized via the linter)
The `# lup: ignore` notes don't contradict — they describe one regime: make the hatch **typed** (`# noqa: CODE`), **audited** (`dev check --antipatterns` already reports missing/spurious markers), and **minimized** (fix code rather than suppress). "Remove all the `# lup: ignore`" = retire the generic untyped hatch in favour of typed `# noqa`.

## Marketplace (DECIDED: keep as plain-`claude` fallback)
`lup-devtools claude` loads the plugin via `--plugin-dir` ("no marketplace, no cache" — `claude/run.py`). `marketplace.json` + the settings.json plugin entry are consulted **only** by a bare `claude` (no wrapper). Kept as that fallback; CLAUDE.md's description corrected to stop calling it load-bearing-for-everything. `set_marketplace_name` (wired into `/lup:init`) maintains it for that path.

## Tests-audit (DECIDED: record only, no changes now)
Suite is ~6–8% dead weight, concentrated — not a pervasive stub explosion. Worst offenders: duplicate `model_backend` test classes in `test_sdk_interop.py`; dict-key/identity echoes in `test_tool_policy.py`; field-passthrough dupes in `test_lib_adapter_fixes.py`. Highest-value *additions* (for a future pass): adversarial bash-hook bypass cases (`$(...)`/env smuggling, multi-segment deny-wins), symlink/`..` breakout for the edit + permission hooks, unknown-backend dispatch must raise. (The piped/uv-wrapped interpreter pipeline cases landed together with this document's salvage PR.)

## Deferred (notes left in place)
- **Linter migration** (above) — focused session.
- **#9 `/init` TODO-gatherer** (setup.py:278) — new command surface; scope separately. *Status 2026-07: the marker is no longer present in setup.py; treat as resolved or re-raise deliberately.*
- **#10 external setup review + hosted dashboard** (config.py:15) — needs external repos an offline editor can't reach + a product decision.
