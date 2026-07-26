"""Claude-native prompt and artifact renderers."""

import json
import shlex
from importlib import resources
from pathlib import Path
from lup.harness.contracts import (
    ArtifactRenderer,
    Atom,
    Instruction,
    NativeSpellings,
    PromptRenderer,
)
from lup.harness.generation import argument_text
from lup.harness.models import (
    Agent,
    Artifact,
    ArtifactTree,
    Harness,
    HookSet,
    ModelTier,
    Plugin,
    PluginLocation,
    QualifiedAgentName,
    Skill,
    SkillInvocation,
    TreeLocation,
)
from lup.policy.bundle import (
    policy_kernel_modules,
    render_policy_data,
    runtime_url_scope,
)


CLAUDE_MODEL_ALIASES: dict[ModelTier, str] = {
    "inherit": "inherit",
    "strongest": "opus",
    "balanced": "sonnet",
    "fast": "haiku",
}
"""Claude's own name for each portable tier, as agent frontmatter accepts it."""


class ClaudeSpellings(NativeSpellings):
    """Spell everything portable prose names the way Claude Code spells it."""

    @property
    def runtime_name(self) -> Atom:
        return Atom("Claude Code")

    @property
    def native_identifiers(self) -> list[Atom]:
        return [
            Atom("AskUserQuestion"),
            Atom("subagent_type"),
            Atom("EnterWorktree"),
            Atom("ExitWorktree"),
            Atom("docs.claude.com"),
            Atom("code.claude.com"),
        ]

    def render(self, invocation: SkillInvocation) -> str:
        command = f"/{invocation.plugin}:{invocation.skill}"
        arguments = " ".join(
            f"{argument.name}={shlex.quote(argument_text(argument.value))}"
            for argument in invocation.arguments
        )
        return f"{command} {arguments}" if arguments else command

    def invocation_pattern(self, plugin: str, placeholder: str) -> Atom:
        return Atom(f"/{plugin}:{placeholder}")

    def ask_user(self, question: str) -> Instruction:
        return Instruction(
            "Ask the user with the AskUserQuestion tool, offering concrete "
            f"options plus a free-text choice: {question}"
        )

    def delegate(self, subagent_type: QualifiedAgentName, prompt: str) -> Instruction:
        return Instruction(
            f"Delegate with Agent(subagent_type={json.dumps(subagent_type)}"
            f", prompt={json.dumps(prompt)})"
        )

    def request_approval(self, action: str, reason: str) -> Instruction:
        return Instruction(
            f"Request explicit user approval before {action}. Reason: {reason}."
        )

    def relocate_session(self, path: str) -> Instruction:
        return Instruction(
            f"`EnterWorktree(path=<{path}>)`, returning afterwards "
            'with `ExitWorktree(action="keep")`'
        )

    def resolver_entry(self) -> Instruction:
        return Instruction(
            "Run `uv run lup-devtools harness resolve --adapter claude`. "
            "The command accepts optional flags: `--run-id <id>` resumes "
            "a persisted run and `--accept`/`--reject` records the human "
            "decision on its review branch. A headless run parks on "
            "material questions — relay them to the user verbatim, never "
            "answer them yourself, then rerun with the repeatable "
            "`--answer <question-id>=<value>` flag."
        )

    def arguments_ref(self) -> Atom:
        return Atom("$ARGUMENTS")

    def runtime_docs(self) -> Instruction:
        return Instruction(
            "the Claude Code and Agent SDK documentation at "
            "https://docs.claude.com/ and https://code.claude.com/"
        )

    def model_alias(self, tier: ModelTier) -> str | None:
        return CLAUDE_MODEL_ALIASES[tier]

    def tree(self, location: TreeLocation) -> Atom:
        match location:
            case "tree_root":
                return Atom(".claude/")
            case "guidance_file":
                return Atom(".claude/CLAUDE.md")
            case "ownership_manifest":
                return Atom(".claude/.lup-ownership.json")
            case "project_settings":
                return Atom(".claude/settings.json")
            case "personal_settings":
                return Atom(".claude/settings.local.json")
            case "marketplace":
                return Atom(".claude/plugins/.claude-plugin/marketplace.json")

    def plugin(self, plugin: str, location: PluginLocation, member: str | None) -> Atom:
        root = f".claude/plugins/{plugin}"
        match location:
            case "root":
                return Atom(f"{root}/")
            case "manifest":
                return Atom(f"{root}/.claude-plugin/plugin.json")
            case "skills":
                leaf = f"commands/{member}.md" if member else "commands/"
                return Atom(f"{root}/{leaf}")
            case "agents":
                leaf = f"agents/{member}.md" if member else "agents/"
                return Atom(f"{root}/{leaf}")
            case "hooks":
                return Atom(f"{root}/hooks/")
            case "guidance_template":
                return Atom(f"{root}/TEMPLATE_CLAUDE.md")


class ClaudeSkillRenderer(ArtifactRenderer[Skill]):
    """Render one portable skill as a Claude command Markdown artifact."""

    def __init__(self, prompts: PromptRenderer, plugin_name: str) -> None:
        self.prompts = prompts
        self.plugin_name = plugin_name

    def render(self, source: Skill) -> ArtifactTree:
        frontmatter = [f"description: {json.dumps(source.description)}"]
        if source.tools:
            frontmatter.append("allowed-tools: " + ", ".join(source.tools))
        if source.argument_hint is not None:
            frontmatter.append(f"argument-hint: {json.dumps(source.argument_hint)}")
        elif source.arguments:
            arguments = "\n".join(
                f"  - name: {argument.name}\n"
                f"    description: {json.dumps(argument.description)}\n"
                f"    required: {str(argument.required).lower()}"
                for argument in source.arguments
            )
            frontmatter.append(f"arguments:\n{arguments}")
        content = (
            "---\n" + "\n".join(frontmatter) + "\n"
            "---\n\n"
            f"{self.prompts.render(source.prompt)}"
        )
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/commands/{source.name}.md"
                    ),
                    content=content,
                    semantic_id=source.id,
                )
            ]
        )


class ClaudeAgentRenderer(ArtifactRenderer[Agent]):
    """Render one portable agent in Claude's Markdown format."""

    def __init__(
        self, prompts: PromptRenderer, plugin_name: str, spellings: NativeSpellings
    ) -> None:
        self.prompts = prompts
        self.plugin_name = plugin_name
        self.spellings = spellings

    def render(self, source: Agent) -> ArtifactTree:
        tools = ", ".join(source.tools)
        alias = (
            None if source.model is None else self.spellings.model_alias(source.model)
        )
        model = f"model: {alias}\n" if alias is not None else ""
        color = f"color: {source.color}\n" if source.color is not None else ""
        content = (
            "---\n"
            f"name: {source.name}\n"
            f"description: {json.dumps(source.description)}\n"
            f"tools: {tools}\n"
            f"{model}"
            f"{color}"
            "---\n\n"
            f"{self.prompts.render(source.prompt)}"
        )
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/agents/{source.name}.md"
                    ),
                    content=content,
                    semantic_id=source.id,
                )
            ]
        )


class ClaudePluginManifestRenderer(ArtifactRenderer[Plugin]):
    """Render Claude plugin metadata without importing shared native names."""

    def render(self, source: Plugin) -> ArtifactTree:
        payload = {
            "name": source.name,
            "version": source.version,
            "description": source.description,
        }
        marketplace = {
            "name": "lup-template",
            "owner": {"name": "Lup"},
            "plugins": [
                {
                    "name": source.name,
                    "description": source.description,
                    "source": f"./{source.name}",
                }
            ],
        }
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(
                        f".claude/plugins/{source.name}/.claude-plugin/plugin.json"
                    ),
                    content=json.dumps(payload, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(".claude/plugins/.claude-plugin/marketplace.json"),
                    content=json.dumps(marketplace, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
            ]
        )


class ClaudeGuidanceRenderer(ArtifactRenderer[Harness]):
    """Render project guidance at Claude's adapter-owned repository location."""

    def __init__(self, prompts: PromptRenderer) -> None:
        self.prompts = prompts

    def render(self, source: Harness) -> ArtifactTree:
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(".claude/CLAUDE.md"),
                    content=self.prompts.render(source.guidance),
                    semantic_id="harness.guidance",
                )
            ]
        )


CLAUDE_POLICY_DISPATCHER = (
    resources.files("lup.adapters.claude")
    .joinpath("assets/policy_dispatcher.py")
    .read_text("utf-8")
)
"""Hermetic hook dispatcher script, shipped verbatim into the plugin tree."""


class ClaudeHookRenderer(ArtifactRenderer[HookSet]):
    """Render Claude hooks, canonical kernel, and application policy rows."""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name

    def render(self, source: HookSet) -> ArtifactTree:
        hooks = {
            "description": "Lup semantic permission policy",
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "WebFetch|Bash|Edit|Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    'python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/policy.py"'
                                ),
                                "timeout": 30,
                            }
                        ],
                    }
                ]
            },
        }
        evidence = {"schemaVersion": 1, "policyIds": source.policy_ids}
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(f".claude/plugins/{self.plugin_name}/hooks/hooks.json"),
                    content=json.dumps(hooks, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/hooks/scripts/policy.py"
                    ),
                    content=CLAUDE_POLICY_DISPATCHER,
                    semantic_id=source.id,
                    executable=True,
                ),
                *[
                    Artifact(
                        path=Path(
                            f".claude/plugins/{self.plugin_name}/hooks/runtime/"
                            f"kernel/{module.name}"
                        ),
                        content=module.source,
                        semantic_id=source.id,
                    )
                    for module in policy_kernel_modules()
                ],
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/hooks/runtime/"
                        "policy_data.py"
                    ),
                    content=render_policy_data(
                        allowed_fetch_scopes=[
                            runtime_url_scope(
                                str(scope.origin),
                                scope.path_prefix,
                                include_subdomains=scope.include_subdomains,
                            )
                            for scope in source.allowed_fetch
                        ],
                        denied_fetch_scopes=[
                            runtime_url_scope(
                                str(scope.origin),
                                scope.path_prefix,
                                include_subdomains=scope.include_subdomains,
                            )
                            for scope in source.denied_fetch
                        ],
                        protected_roots=[
                            path.as_posix() for path in source.protected_edit_roots
                        ],
                        human_owned_files=[
                            path.as_posix() for path in source.human_owned_files
                        ],
                        autonomous_agent_identities=[
                            "resolve-editor",
                            "lup:resolve-editor",
                        ],
                        shell_rule_extension=list(source.shell_rules),
                    ),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/hooks/runtime/evidence.json"
                    ),
                    content=json.dumps(evidence, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
            ]
        )
