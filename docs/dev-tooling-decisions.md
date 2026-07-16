# Development-tooling decisions

The 0.2 capability-composition release supersedes the earlier deferred notes.

- The Lup checker now uses a project-wide Python AST/import index for the
  `abc-capability` architecture rule. Typed `# lup: ignore[rule-id]` remains
  the audited repository-specific suppression; standard Ruff diagnostics stay
  with Ruff. Missing, untyped, and spurious Lup suppressions are reported.
- Claude and Codex hooks compile from the same semantic policy declarations.
  Generated runtimes are hermetic and do not import this checkout.
- Native harnesses are generated and launched through `lup-devtools harness`.
  Claude uses the verified local directory; Codex requires a separately
  installed cache with a matching digest. Trust, caches, and credentials remain
  personal state.
- The typed harness catalog and ownership manifest are the source of truth for
  generated artifacts. Reconciliation preserves unknown or locally changed
  files and only deletes bytes whose generated ownership is proven.
- Resolver work is isolated in orchestrator-leased branches/worktrees and never
  merged directly into the user's branch.

See the architecture, harness, resolver, and migration guides beside this file.
