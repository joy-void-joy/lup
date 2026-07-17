# Harness authoring and generation

The native Claude and Codex trees are deterministic committed output. Run
`uv run lup-devtools harness generate all` before review. The local pre-commit
hook regenerates and stops if that changes tracked files; CI runs the read-only
`uv run lup-devtools harness check all` drift check and never commits changes.

`src/lup_template/devtools/harness/content/` contains the canonical skill,
agent, guidance, pattern, and template declarations.
`src/lup_template/devtools/harness/catalog.py` composes them with resolver
invocations and the application-owned hook policy. Prompt prose is stored as
ordered typed parts. A
`SkillInvocationRenderer` owns the complete native invocation spelling; shared
code never rewrites `/lup:` into another prefix.

Concrete renderers build independent artifact families. Tree builders compose
them, then validators check the result. Generate and launch with:

Generation orchestration itself accepts a frozen `GenerationRecipe` containing
the desired tree, current-tree reader, ownership location, and requirements.
Only the CLI composition root maps a user-facing target name to a concrete
recipe. Adding another target supplies another recipe; it does not add a branch
to reconciliation or materialization.

```bash
uv run lup-devtools harness claude --generate-only
uv run lup-devtools harness codex --generate-only
uv run lup-devtools harness claude [native arguments]
uv run lup-devtools harness codex [native arguments]
```

Reconciliation compares the current tree, desired tree, and
`.lup-ownership.json`. Exact existing bytes may acquire first ownership.
Managed bytes may be replaced or deleted only when their recorded digest still
matches. Local, sensitive, unknown, and changed generated files are preserved
and reported as conflicts. Writes use atomic replacement; stale proposals are
rejected.

Generated plugins include their policy runtime and dispatcher. Hook execution
does not import `lup-devtools`, this checkout, or its virtual environment.
Claude and Codex decoders convert native tool payloads to the same semantic
edit/shell/fetch/search vocabulary. Shared policy evaluates that vocabulary;
adapter renderers translate the decision. Codex `ask` is a documented
fail-closed exit-code-2 approximation.

Codex packages are installed through the native plugin CLI only when the
separately installed cache digest is absent or stale. The source plugin is not
mistaken for the cache. Personal trust state, credentials, active run state,
and cache contents are never generated or committed. Review hook trust with
the native `/hooks` surface after generation.

Commit generated `.claude`, `.codex`, `.agents`, and `AGENTS.md` artifacts
together with catalog changes. CI should run both generation commands and
require a clean diff.

See `docs/adopter-guide.md` for complete skill, fetch-policy, conflict, and
source-patch reconciliation walkthroughs. The one-time reviewed differences
from the retired native catalog are recorded in
`docs/typed-content-migration-audit.md`.
