# CLAUDE.md Template

This file exports portable sections from the upstream CLAUDE.md as a scaffold for downstream projects. It contains conventions, workflow patterns, and coding standards that apply to any project using lup.

**How it's used:** `{{ init_skill }}` and `{{ install_skill }}` perform a **section-level merge** — they use the `<!-- section: ... -->` markers below to identify independent merge units, compare them against the target's existing CLAUDE.md, add sections that are missing, and leave existing sections untouched. Placeholders like `<project>` are replaced with the actual project name.

---

<!-- section: CLAUDE.md -->
# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

**Note:** Modifying `CLAUDE.md` means modifying `.claude/CLAUDE.md` (this file).

