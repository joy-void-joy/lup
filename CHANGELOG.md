# Changelog

## 0.2.0 — 2026-07-16

Breaking capability-composition release.

- Replaced engine/client/options service locators with narrow `SessionFactory`,
  `Session`, `Turn`, event, interrupt, steer, fork, binding, render, launch, and
  policy capabilities.
- Added strict typed turn-bound `submit_output`, whole-logical-turn wrappers,
  debounced background scheduling, immutable routing, profile transforms, and
  Claude/Codex concrete factories.
- Moved Codex execution to typed live app-server JSON-RPC and records the
  current dynamic-tool rebinding limitation explicitly.
- Added a single Pydantic harness catalog, deterministic Claude/Codex artifact
  compilation, validation, safe reconciliation, ownership manifests, hermetic
  semantic policy dispatchers, Codex cache verification, and named launchers.
- Added the persisted DAG resolver with question brokering, isolated leases and
  worktrees, semantic multi-parent joins, bounded review, integration,
  verification, final review, and cleanup records.
- Added the project-wide `abc-capability` AST rule and typed suppression audit.
- Removed all legacy engine, client, broad options, profile, background-driver,
  replay-stream, and provider-wide tool-registry modules. There is no legacy
  facade.
- Fixed `LocalProcessLauncher` to capture through pipes so git output stays
  plain regardless of the host pager configuration, and made resolver resume
  treat the persisted phase as a monotonic high-water mark so hard-killed runs
  recover from every mid-phase kill window.

See [docs/migration-0.2.md](docs/migration-0.2.md).
