<!-- Generated from lup.devtools.harness.generated_paths by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Every generated path, and what it is compiled from

Walked from the trees the recipes compile, so a path reaches this page by being generated rather than by being remembered. The right column is each artifact's own attribution — for most of them the line a reader meets on opening the file, naming where to edit instead — so nothing here can name a source the artifact does not.

A source spelled as a dotted module is a module to open. One spelled as an identifier is a typed declaration, composed in the catalog that names it. One spelled as a path is copied from that file byte for byte.

The repository-wide artifacts written outside every runtime tree — the rule and command references, this page, and the CI workflow — belong to no recipe and are described in [harness.md](harness.md) instead.

## `claude` — 79 artifacts

| Generated path | Compiled from |
| --- | --- |
| `.claude/CLAUDE.md` | lup_template.devtools.harness.content.guidance |
| `.claude/plugins/.claude-plugin/marketplace.json` | plugin.lup |
| `.claude/plugins/lup/.claude-plugin/plugin.json` | plugin.lup |
| `.claude/plugins/lup/.mcp.json` | plugin.lup |
| `.claude/plugins/lup/TEMPLATE_CLAUDE.md` | lup_template.devtools.harness.content.template_claude |
| `.claude/plugins/lup/agents/tdd-implementer.md` | lup.devtools.harness.content.agents.tdd_implementer |
| `.claude/plugins/lup/agents/trace-explorer.md` | lup.devtools.harness.content.agents.trace_explorer |
| `.claude/plugins/lup/agents/version-explorer.md` | lup.devtools.harness.content.agents.version_explorer |
| `.claude/plugins/lup/agents/version-reviewer.md` | lup.devtools.harness.content.agents.version_reviewer |
| `.claude/plugins/lup/commands/add-command.md` | lup.devtools.harness.content.skills.add_command |
| `.claude/plugins/lup/commands/analyze.md` | lup.devtools.harness.content.skills.analyze |
| `.claude/plugins/lup/commands/brainstorm.md` | lup_template.devtools.harness.content.skills.brainstorm |
| `.claude/plugins/lup/commands/bump.md` | lup.devtools.harness.content.skills.bump |
| `.claude/plugins/lup/commands/close.md` | lup.devtools.harness.content.skills.close |
| `.claude/plugins/lup/commands/commit.md` | lup.devtools.harness.content.skills.commit |
| `.claude/plugins/lup/commands/create-investigator.md` | lup.devtools.harness.content.skills.create_investigator |
| `.claude/plugins/lup/commands/debug.md` | lup.devtools.harness.content.skills.debug |
| `.claude/plugins/lup/commands/fb-analyze.md` | lup.devtools.harness.content.skills.fb_analyze |
| `.claude/plugins/lup/commands/fb-implement.md` | lup.devtools.harness.content.skills.fb_implement |
| `.claude/plugins/lup/commands/fb-investigate.md` | lup.devtools.harness.content.skills.fb_investigate |
| `.claude/plugins/lup/commands/fb-reflect.md` | lup.devtools.harness.content.skills.fb_reflect |
| `.claude/plugins/lup/commands/fb-status.md` | lup.devtools.harness.content.skills.fb_status |
| `.claude/plugins/lup/commands/feedback-loop.md` | lup.devtools.harness.content.skills.feedback_loop |
| `.claude/plugins/lup/commands/hooks.md` | lup.devtools.harness.content.skills.hooks |
| `.claude/plugins/lup/commands/implementer.md` | lup.devtools.harness.content.skills.implementer |
| `.claude/plugins/lup/commands/import.md` | lup_template.devtools.harness.content.skills.import_skill |
| `.claude/plugins/lup/commands/init.md` | lup_template.devtools.harness.content.skills.init |
| `.claude/plugins/lup/commands/install.md` | lup_template.devtools.harness.content.skills.install |
| `.claude/plugins/lup/commands/land.md` | lup.devtools.harness.content.skills.land |
| `.claude/plugins/lup/commands/merge.md` | lup.devtools.harness.content.skills.merge |
| `.claude/plugins/lup/commands/meta.md` | lup_template.devtools.harness.content.skills.meta |
| `.claude/plugins/lup/commands/modify-command.md` | lup.devtools.harness.content.skills.modify_command |
| `.claude/plugins/lup/commands/principle.md` | lup.devtools.harness.content.skills.principle |
| `.claude/plugins/lup/commands/rebase.md` | lup.devtools.harness.content.skills.rebase |
| `.claude/plugins/lup/commands/refactor-tools.md` | lup.devtools.harness.content.skills.refactor_tools |
| `.claude/plugins/lup/commands/refactor.md` | lup.devtools.harness.content.skills.refactor |
| `.claude/plugins/lup/commands/report.md` | lup.devtools.harness.content.skills.report |
| `.claude/plugins/lup/commands/resolve-reviewer.md` | lup.devtools.harness.content.skills.resolve_reviewer |
| `.claude/plugins/lup/commands/resolve.md` | lup.devtools.harness.content.skills.resolve |
| `.claude/plugins/lup/commands/review.md` | lup.devtools.harness.content.skills.review |
| `.claude/plugins/lup/commands/update.md` | lup_template.devtools.harness.content.skills.update |
| `.claude/plugins/lup/commands/verify-solved.md` | lup.devtools.harness.content.skills.verify_solved |
| `.claude/plugins/lup/hooks/hooks.json` | hooks.lup-policy |
| `.claude/plugins/lup/hooks/runtime/evidence.json` | hooks.lup-policy |
| `.claude/plugins/lup/hooks/runtime/kernel/__init__.py` | lup.policy.kernel.__init__ |
| `.claude/plugins/lup/hooks/runtime/kernel/archives.py` | lup.policy.kernel.archives |
| `.claude/plugins/lup/hooks/runtime/kernel/commands.py` | lup.policy.kernel.commands |
| `.claude/plugins/lup/hooks/runtime/kernel/decision.py` | lup.policy.kernel.decision |
| `.claude/plugins/lup/hooks/runtime/kernel/edit.py` | lup.policy.kernel.edit |
| `.claude/plugins/lup/hooks/runtime/kernel/fetch.py` | lup.policy.kernel.fetch |
| `.claude/plugins/lup/hooks/runtime/kernel/lex.py` | lup.policy.kernel.lex |
| `.claude/plugins/lup/hooks/runtime/kernel/roles.py` | lup.policy.kernel.roles |
| `.claude/plugins/lup/hooks/runtime/kernel/rows.py` | lup.policy.kernel.rows |
| `.claude/plugins/lup/hooks/runtime/kernel/settlement.py` | lup.policy.kernel.settlement |
| `.claude/plugins/lup/hooks/runtime/kernel/shell.py` | lup.policy.kernel.shell |
| `.claude/plugins/lup/hooks/runtime/kernel/tools.py` | lup.policy.kernel.tools |
| `.claude/plugins/lup/hooks/runtime/kernel/words.py` | lup.policy.kernel.words |
| `.claude/plugins/lup/hooks/runtime/policy_data.py` | lup.policy.bundle |
| `.claude/plugins/lup/hooks/scripts/policy.py` | lup.policy.assets.host and lup.providers.claude.assets.policy_dispatcher |
| `.claude/plugins/lup/scripts/file_suggest.sh` | src/lup_template/devtools/harness/content/assets/file_suggest.sh |
| `.claude/settings.json` | lup_template.devtools.harness.content.settings |
| `docs/README.md` | lup.devtools.harness.content.docs.index |
| `docs/architecture.md` | lup.devtools.harness.content.docs.architecture |
| `docs/contributing.md` | lup.devtools.harness.content.docs.contributing |
| `docs/conventions.md` | lup.devtools.harness.content.docs.conventions |
| `docs/dev-tooling-decisions.md` | lup_template.devtools.harness.content.docs.decisions |
| `docs/harness.md` | lup.devtools.harness.content.docs.harness |
| `docs/library.md` | lup.devtools.harness.content.docs.library |
| `docs/native-capabilities.md` | lup.devtools.harness.content.docs.native_capabilities |
| `docs/orchestration.md` | lup.devtools.harness.content.docs.orchestration |
| `docs/patterns.md` | lup.devtools.harness.content.docs.patterns |
| `docs/permissions.md` | lup.devtools.harness.content.docs.permissions |
| `docs/platform-differentiation.md` | lup.devtools.harness.content.docs.platform_differentiation |
| `docs/quality-pipeline.md` | lup.devtools.harness.content.docs.quality_pipeline |
| `docs/resolver.md` | lup.devtools.harness.content.docs.resolver |
| `docs/self-improvement.md` | lup.devtools.harness.content.docs.self_improvement |
| `docs/supervisor.md` | lup.devtools.harness.content.docs.supervisor |
| `docs/template.md` | lup_template.devtools.harness.content.docs.template |
| `docs/upstream-reports.md` | lup.devtools.harness.content.docs.upstream_reports |

## `codex` — 61 artifacts

| Generated path | Compiled from |
| --- | --- |
| `.agents/plugins/marketplace.json` | plugin.lup |
| `.codex/agents/tdd-implementer.toml` | the portable agent declaration agent.tdd-implementer |
| `.codex/agents/trace-explorer.toml` | the portable agent declaration agent.trace-explorer |
| `.codex/agents/version-explorer.toml` | the portable agent declaration agent.version-explorer |
| `.codex/agents/version-reviewer.toml` | the portable agent declaration agent.version-reviewer |
| `.codex/config.toml` | lup.providers.codex.harness |
| `.codex/plugins/lup/.codex-plugin/plugin.json` | plugin.lup |
| `.codex/plugins/lup/TEMPLATE_AGENTS.md` | lup_template.devtools.harness.content.template_codex |
| `.codex/plugins/lup/hooks/hooks.json` | hooks.lup-policy |
| `.codex/plugins/lup/hooks/runtime/codex_patch.py` | lup.providers.codex.patch |
| `.codex/plugins/lup/hooks/runtime/evidence.json` | hooks.lup-policy |
| `.codex/plugins/lup/hooks/runtime/kernel/__init__.py` | lup.policy.kernel.__init__ |
| `.codex/plugins/lup/hooks/runtime/kernel/archives.py` | lup.policy.kernel.archives |
| `.codex/plugins/lup/hooks/runtime/kernel/commands.py` | lup.policy.kernel.commands |
| `.codex/plugins/lup/hooks/runtime/kernel/decision.py` | lup.policy.kernel.decision |
| `.codex/plugins/lup/hooks/runtime/kernel/edit.py` | lup.policy.kernel.edit |
| `.codex/plugins/lup/hooks/runtime/kernel/fetch.py` | lup.policy.kernel.fetch |
| `.codex/plugins/lup/hooks/runtime/kernel/lex.py` | lup.policy.kernel.lex |
| `.codex/plugins/lup/hooks/runtime/kernel/roles.py` | lup.policy.kernel.roles |
| `.codex/plugins/lup/hooks/runtime/kernel/rows.py` | lup.policy.kernel.rows |
| `.codex/plugins/lup/hooks/runtime/kernel/settlement.py` | lup.policy.kernel.settlement |
| `.codex/plugins/lup/hooks/runtime/kernel/shell.py` | lup.policy.kernel.shell |
| `.codex/plugins/lup/hooks/runtime/kernel/tools.py` | lup.policy.kernel.tools |
| `.codex/plugins/lup/hooks/runtime/kernel/words.py` | lup.policy.kernel.words |
| `.codex/plugins/lup/hooks/runtime/policy_data.py` | lup.policy.bundle |
| `.codex/plugins/lup/hooks/scripts/policy.py` | lup.policy.assets.host and lup.providers.codex.assets.policy_dispatcher |
| `.codex/plugins/lup/skills/add-command/SKILL.md` | lup.devtools.harness.content.skills.add_command |
| `.codex/plugins/lup/skills/analyze/SKILL.md` | lup.devtools.harness.content.skills.analyze |
| `.codex/plugins/lup/skills/brainstorm/SKILL.md` | lup_template.devtools.harness.content.skills.brainstorm |
| `.codex/plugins/lup/skills/bump/SKILL.md` | lup.devtools.harness.content.skills.bump |
| `.codex/plugins/lup/skills/close/SKILL.md` | lup.devtools.harness.content.skills.close |
| `.codex/plugins/lup/skills/commit/SKILL.md` | lup.devtools.harness.content.skills.commit |
| `.codex/plugins/lup/skills/create-investigator/SKILL.md` | lup.devtools.harness.content.skills.create_investigator |
| `.codex/plugins/lup/skills/debug/SKILL.md` | lup.devtools.harness.content.skills.debug |
| `.codex/plugins/lup/skills/fb-analyze/SKILL.md` | lup.devtools.harness.content.skills.fb_analyze |
| `.codex/plugins/lup/skills/fb-implement/SKILL.md` | lup.devtools.harness.content.skills.fb_implement |
| `.codex/plugins/lup/skills/fb-investigate/SKILL.md` | lup.devtools.harness.content.skills.fb_investigate |
| `.codex/plugins/lup/skills/fb-reflect/SKILL.md` | lup.devtools.harness.content.skills.fb_reflect |
| `.codex/plugins/lup/skills/fb-status/SKILL.md` | lup.devtools.harness.content.skills.fb_status |
| `.codex/plugins/lup/skills/feedback-loop/SKILL.md` | lup.devtools.harness.content.skills.feedback_loop |
| `.codex/plugins/lup/skills/hooks/SKILL.md` | lup.devtools.harness.content.skills.hooks |
| `.codex/plugins/lup/skills/implementer/SKILL.md` | lup.devtools.harness.content.skills.implementer |
| `.codex/plugins/lup/skills/import/SKILL.md` | lup_template.devtools.harness.content.skills.import_skill |
| `.codex/plugins/lup/skills/init/SKILL.md` | lup_template.devtools.harness.content.skills.init |
| `.codex/plugins/lup/skills/install/SKILL.md` | lup_template.devtools.harness.content.skills.install |
| `.codex/plugins/lup/skills/land/SKILL.md` | lup.devtools.harness.content.skills.land |
| `.codex/plugins/lup/skills/merge/SKILL.md` | lup.devtools.harness.content.skills.merge |
| `.codex/plugins/lup/skills/meta/SKILL.md` | lup_template.devtools.harness.content.skills.meta |
| `.codex/plugins/lup/skills/modify-command/SKILL.md` | lup.devtools.harness.content.skills.modify_command |
| `.codex/plugins/lup/skills/principle/SKILL.md` | lup.devtools.harness.content.skills.principle |
| `.codex/plugins/lup/skills/rebase/SKILL.md` | lup.devtools.harness.content.skills.rebase |
| `.codex/plugins/lup/skills/refactor-tools/SKILL.md` | lup.devtools.harness.content.skills.refactor_tools |
| `.codex/plugins/lup/skills/refactor/SKILL.md` | lup.devtools.harness.content.skills.refactor |
| `.codex/plugins/lup/skills/report/SKILL.md` | lup.devtools.harness.content.skills.report |
| `.codex/plugins/lup/skills/resolve-reviewer/SKILL.md` | lup.devtools.harness.content.skills.resolve_reviewer |
| `.codex/plugins/lup/skills/resolve/SKILL.md` | lup.devtools.harness.content.skills.resolve |
| `.codex/plugins/lup/skills/review/SKILL.md` | lup.devtools.harness.content.skills.review |
| `.codex/plugins/lup/skills/update/SKILL.md` | lup_template.devtools.harness.content.skills.update |
| `.codex/plugins/lup/skills/verify-solved/SKILL.md` | lup.devtools.harness.content.skills.verify_solved |
| `.codex/rules/lup.rules` | lup.policy.shell_rules |
| `AGENTS.md` | lup_template.devtools.harness.content.guidance |
