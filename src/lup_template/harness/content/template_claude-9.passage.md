`lup-devtools harness claude` regenerates, verifies, and runs Claude Code with
the local Lup plugin and the active profile's account (`CLAUDE_CONFIG_DIR`).
`lup-devtools dev usage claude` reports usage for the chosen profile, and
`lup-devtools dev usage codex` reports the other backend's. This repository keeps
its accounts as directories under `.lup/profiles/`, curated with either
`lup-devtools harness profile` or `lup-devtools setup profile` — the same
roster through both.

Each repo names its plugin **marketplace** after the project — the plugin entry stays `lup`, so `{{ skill_pattern }}` is identical everywhere. Marketplace names share one global namespace (`~/.claude/plugins/known_marketplaces.json`), so a shared name like `lup`/`local` collides across repos and an install from one shadows the others; `lup-devtools dev plugin name` (run by `{{ init_skill }}` and `{{ install_skill }}`) wires the per-project name.

