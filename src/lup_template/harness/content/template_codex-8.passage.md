`lup-devtools harness codex` regenerates and verifies the Codex artifacts,
installs an immutable content-addressed copy of the plugin after a digest check, and
launches the Codex CLI in a persistent per-worktree home seeded from personal
Codex authentication and settings.
`lup-devtools dev usage codex` reports this backend's usage and
`lup-devtools dev usage claude` the other's; profiles are managed with
`lup-devtools setup profile`.
`--codex-home` or an inherited `CODEX_HOME` selects an explicit home instead.

Each repo names its plugin **marketplace** after the project — the plugin entry stays `lup`, so `{{ skill_pattern }}` is identical everywhere. Codex resolves the marketplace from the repository's `.agents/plugins/marketplace.json` and installs the plugin into its own cache, verifying the digest before every launch; `lup-devtools dev plugin name` (run by `{{ init_skill }}` and `{{ install_skill }}`) wires the per-project name.

