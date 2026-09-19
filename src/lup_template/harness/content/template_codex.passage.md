# AGENTS.md Template

This file exports portable sections from the upstream AGENTS.md as a scaffold for downstream projects. It contains conventions, workflow patterns, and coding standards that apply to any project using lup.

**How it's used:** `{{ init_skill }}` and `{{ install_skill }}` perform a **section-level merge** — they use the `<!-- section: ... -->` markers below to identify independent merge units, compare them against the target's existing AGENTS.md, add sections that are missing, and leave existing sections untouched. Placeholders like `<project>` are replaced with the actual project name.

---

<!-- section: AGENTS.md -->
# AGENTS.md

This file provides guidance to Codex — and any agent that reads `AGENTS.md` — when working with code in this repository.

**Note:** Modifying `AGENTS.md` means modifying the repository-root `AGENTS.md` (this file).

