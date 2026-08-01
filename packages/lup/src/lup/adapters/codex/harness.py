"""Codex-native prompt, plugin, skill, agent, and guidance renderers."""

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
    GUIDANCE_BYTE_BUDGET,
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
from lup.policy.kernel.words import (
    INTERPRETERS,
    PASS_THROUGH_WORDS,
    UV_RUN_ALLOWED_TARGETS,
)
from lup.policy.shell_rules import BASE_SHELL_RULES, ShellCommandRule


class CodexSpellings(NativeSpellings):
    """Spell everything portable prose names the way Codex spells it.

    Custom agents are the one location Codex keeps outside the plugin, so the
    plugin name is deliberately unused there. The model tier is declined
    outright: recorded evidence for Codex custom agents covers TOML parsing
    only, so there is no proven alias to spell a tier in.
    """

    @property
    def runtime_name(self) -> Atom:
        return Atom("Codex")

    @property
    def native_identifiers(self) -> list[Atom]:
        return [Atom("developers.openai.com"), Atom("learn.chatgpt.com")]

    def render(self, invocation: SkillInvocation) -> str:
        mention = f"${invocation.plugin}:{invocation.skill}"
        arguments = " ".join(
            f"{argument.name}={shlex.quote(argument_text(argument.value))}"
            for argument in invocation.arguments
        )
        return f"{mention} {arguments}" if arguments else mention

    def invocation_pattern(self, plugin: str, placeholder: str) -> Atom:
        return Atom(f"${plugin}:{placeholder}")

    def ask_user(self, question: str) -> Instruction:
        return Instruction(
            "Ask the user directly, offering concrete options, and wait "
            f"for the answer: {question}"
        )

    def delegate(self, subagent_type: QualifiedAgentName, prompt: str) -> Instruction:
        return Instruction(
            f"Delegate to the {subagent_type} custom agent with this task: {prompt}"
        )

    def request_approval(self, action: str, reason: str) -> Instruction:
        return Instruction(
            f"Request explicit user approval before {action}. Reason: {reason}."
        )

    def relocate_session(self, path: str) -> Instruction:
        return Instruction(
            f"start a session rooted at <{path}> and continue there — "
            "this runtime cannot move a running session, so work "
            "carried on here would land in the checkout it started from"
        )

    def resolver_entry(self) -> Instruction:
        return Instruction(
            "Run `uv run lup-devtools harness resolve --adapter codex`. "
            "The command accepts optional flags: `--run-id <id>` resumes "
            "a persisted run and `--accept`/`--reject` records the human "
            "decision on its review branch. It waits zero seconds by "
            "default and parks on material questions — relay them to "
            "the user verbatim, never answer them yourself, then rerun "
            "with the repeatable `--answer <question-id>=<value>` flag. "
            "Relay each question with everything printed alongside it — the "
            "`# lup:` notes it was raised from, the concern's spec, and its "
            "acceptance criteria — because a bare prompt reads as a decision "
            "with no stakes and cannot be judged. Choices are the planner's "
            "suggestions, not a menu: say so, and pass an answer in the "
            "user's own words when they give one. "
            "Never pass `--wait` or `--supervise`; both hold a run open "
            "for a human instead of parking — `--wait` at the mailbox, "
            "`--supervise` at the page it opens."
        )

    def arguments_ref(self) -> Atom:
        return Atom("the arguments supplied with this skill invocation")

    def runtime_docs(self) -> Instruction:
        return Instruction(
            "the Codex documentation at "
            "https://developers.openai.com/codex/ and "
            "https://learn.chatgpt.com/"
        )

    def model_alias(self, tier: ModelTier) -> str | None:
        return None

    def tree(self, location: TreeLocation) -> Atom:
        match location:
            case "tree_root":
                return Atom(".codex/")
            case "guidance_file":
                return Atom("AGENTS.md")
            case "ownership_manifest":
                return Atom(".codex/.lup-ownership.json")
            case "project_settings":
                return Atom(".codex/config.toml")
            case "personal_settings":
                return Atom(".codex/config.local.toml")
            case "marketplace":
                return Atom(".agents/plugins/marketplace.json")

    def plugin(self, plugin: str, location: PluginLocation, member: str | None) -> Atom:
        root = f".codex/plugins/{plugin}"
        match location:
            case "root":
                return Atom(f"{root}/")
            case "manifest":
                return Atom(f"{root}/.codex-plugin/plugin.json")
            case "skills":
                leaf = f"skills/{member}/SKILL.md" if member else "skills/"
                return Atom(f"{root}/{leaf}")
            case "agents":
                leaf = f"agents/{member}.toml" if member else "agents/"
                return Atom(f".codex/{leaf}")
            case "hooks":
                return Atom(f"{root}/hooks/")
            case "guidance_template":
                return Atom(f"{root}/TEMPLATE_AGENTS.md")


class CodexSkillRenderer(ArtifactRenderer[Skill]):
    """Render one portable declaration as a same-named Codex skill."""

    def __init__(self, prompts: PromptRenderer, plugin_name: str) -> None:
        self.prompts = prompts
        self.plugin_name = plugin_name

    def render(self, source: Skill) -> ArtifactTree:
        content = (
            "---\n"
            f"name: {source.name}\n"
            f"description: {json.dumps(source.description)}\n"
            "---\n\n"
            f"{self.prompts.render(source.prompt)}"
        )
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/skills/{source.name}/SKILL.md"
                    ),
                    content=content,
                    semantic_id=source.id,
                )
            ]
        )


class CodexAgentRenderer(ArtifactRenderer[Agent]):
    """Render one portable agent as project-scoped custom-agent TOML.

    The model row appears only where the vocabulary can spell the declared
    tier, and this one declines: omitting it lets the agent inherit the session
    model, which is honest where naming another runtime's alias would not be.
    """

    def __init__(self, prompts: PromptRenderer, spellings: NativeSpellings) -> None:
        self.prompts = prompts
        self.spellings = spellings

    def render(self, source: Agent) -> ArtifactTree:
        alias = (
            None if source.model is None else self.spellings.model_alias(source.model)
        )
        rows = [
            "# Generated file — do not edit directly. Rendered from the portable",
            f"# agent declaration {source.id} by "
            "`uv run lup-devtools harness generate all`.",
            f"name = {json.dumps(source.name)}",
            f"description = {json.dumps(source.description)}",
            (
                "developer_instructions = "
                f"{json.dumps(self.prompts.render(source.prompt))}"
            ),
        ]
        if alias is not None:
            rows.append(f"model = {json.dumps(alias)}")
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(f".codex/agents/{source.name}.toml"),
                    content="\n".join(rows),
                    semantic_id=source.id,
                )
            ]
        )


class CodexPluginManifestRenderer(ArtifactRenderer[Plugin]):
    """Render the required Codex manifest and repository marketplace entry."""

    def render(self, source: Plugin) -> ArtifactTree:
        manifest = {
            "name": source.name,
            "version": source.version,
            "description": source.description,
            "skills": "./skills/",
        }
        if source.hooks is not None:
            manifest["hooks"] = "./hooks/hooks.json"
        marketplace = {
            "name": source.marketplace,
            "plugins": [
                {
                    "name": source.name,
                    "category": "development",
                    "interface": {"displayName": "Lup"},
                    "source": {
                        "source": "local",
                        "path": f"./.codex/plugins/{source.name}",
                    },
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                }
            ],
        }
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(
                        f".codex/plugins/{source.name}/.codex-plugin/plugin.json"
                    ),
                    content=json.dumps(manifest, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(".agents/plugins/marketplace.json"),
                    content=json.dumps(marketplace, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
            ]
        )


class CodexGuidanceRenderer(ArtifactRenderer[Harness]):
    """Render root project guidance at Codex's documented repository location."""

    def __init__(
        self, prompts: PromptRenderer, budget: int = GUIDANCE_BYTE_BUDGET
    ) -> None:
        self.prompts = prompts
        self.budget = budget

    def render(self, source: Harness) -> ArtifactTree:
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path("AGENTS.md"),
                    content=self.prompts.render(source.guidance),
                    semantic_id="harness.guidance",
                ),
                Artifact(
                    path=Path(".codex/config.toml"),
                    content=(
                        "# Generated file — do not edit directly. Rendered from\n"
                        "# lup.adapters.codex.harness by "
                        "`uv run lup-devtools harness generate all`.\n"
                        "# Personal sandbox and approval defaults stay in "
                        "~/.codex/config.toml.\n"
                        "# Native shell allows are generated under "
                        ".codex/rules/.\n"
                        "[features]\nhooks = true\n"
                        "\n# The ceiling the guidance check enforces at "
                        "generation time, stated\n"
                        "# here too so the runtime cannot silently truncate "
                        "what generation passed.\n"
                        f"project_doc_max_bytes = {self.budget}\n"
                    ),
                    semantic_id="harness.project-config",
                ),
            ]
        )


CODEX_POLICY_DISPATCHER = (
    resources.files("lup.adapters.codex")
    .joinpath("assets/policy_dispatcher.py")
    .read_text("utf-8")
)
"""Hermetic hook dispatcher script, shipped verbatim into the plugin tree."""

CODEX_PATCH_RUNTIME = (
    resources.files("lup.adapters.codex").joinpath("patch.py").read_text("utf-8")
)
"""Envelope decoder, shipped beside the kernel for the dispatcher to import."""


CODEX_DYNAMIC_COMMANDS = (
    *INTERPRETERS,
    *PASS_THROUGH_WORDS,
    "awk",
    "curl",
    "find",
    "gawk",
    "git",
    "mawk",
    "rm",
    "sed",
    "uv",
    "uvx",
    "xargs",
)
"""Executables whose semantic decision cannot be represented by one prefix."""


def codex_allow_prefixes(extension: list[ShellCommandRule]) -> list[list[str]]:
    """Compile semantic allows that stay allowed for every suffix.

    Codex prefix rules bypass the sandbox, so flag-guarded rows cannot be
    widened into a native allow. The runtime hook continues to classify those
    forms, along with every command whose safety depends on parsed content.
    """

    def add(prefix: list[str]) -> None:
        if prefix not in prefixes:
            prefixes.append(prefix)

    prefixes: list[list[str]] = []
    for command in [*BASE_SHELL_RULES, *extension]:
        if not command.subcommands:
            if (
                command.name not in CODEX_DYNAMIC_COMMANDS
                and command.default_effect == "allow"
                and not command.ask_flags
            ):
                add([command.name])
            continue
        for subcommand in command.subcommands:
            if subcommand.operations:
                for operation in subcommand.operations:
                    if operation.effect == "allow" and not operation.ask_flags:
                        add([command.name, subcommand.name, operation.name])
                continue
            if subcommand.effect == "allow" and not subcommand.ask_flags:
                add([command.name, subcommand.name])
    for target in UV_RUN_ALLOWED_TARGETS:
        add(["uv", "run", target])
    return sorted(prefixes)


def render_codex_rules(source: HookSet) -> str:
    """Render project-local native execution rules for prefix-safe allows."""
    rows = [
        "# Generated file — do not edit directly. Rendered from the canonical",
        "# Lup semantic shell policy by `uv run lup-devtools harness generate all`.",
        "",
    ]
    for prefix in codex_allow_prefixes(source.shell_rules):
        rows.append(
            f"prefix_rule(pattern = {json.dumps(prefix)}, decision = "
            '"allow", justification = "Allowed by Lup semantic shell policy")'
        )
    return "\n".join([*rows, ""])


class CodexHookRenderer(ArtifactRenderer[HookSet]):
    """Render Codex hooks, canonical kernel, and application policy rows."""

    def __init__(self, plugin_name: str, worker_identity: str) -> None:
        self.plugin_name = plugin_name
        self.worker_identity = worker_identity

    def render(self, source: HookSet) -> ArtifactTree:
        policy_hook = {
            "type": "command",
            "command": 'python3 "$PLUGIN_ROOT/hooks/scripts/policy.py"',
            "statusMessage": "Checking Lup policy",
            "timeout": 30,
        }
        hooks = {
            "hooks": {
                "PermissionRequest": [
                    {
                        "matcher": "Bash|apply_patch|web_fetch",
                        "hooks": [policy_hook],
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "Bash|apply_patch|web_fetch",
                        "hooks": [policy_hook],
                    }
                ],
            }
        }
        evidence = {
            "schemaVersion": 1,
            "policyIds": source.policy_ids,
            "askApproximation": "PermissionRequest defers asks to native approval",
        }
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(f".codex/plugins/{self.plugin_name}/hooks/hooks.json"),
                    content=json.dumps(hooks, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(f".codex/rules/{self.plugin_name}.rules"),
                    content=render_codex_rules(source),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/scripts/policy.py"
                    ),
                    content=CODEX_POLICY_DISPATCHER,
                    semantic_id=source.id,
                    executable=True,
                ),
                *[
                    Artifact(
                        path=Path(
                            f".codex/plugins/{self.plugin_name}/hooks/runtime/"
                            f"kernel/{module.name}"
                        ),
                        content=module.source,
                        semantic_id=source.id,
                    )
                    for module in policy_kernel_modules()
                ],
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/runtime/"
                        "codex_patch.py"
                    ),
                    content=CODEX_PATCH_RUNTIME,
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/runtime/"
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
                        autonomous_agent_identities=[self.worker_identity],
                        shell_rule_extension=list(source.shell_rules),
                    ),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/runtime/evidence.json"
                    ),
                    content=json.dumps(evidence, indent=2, sort_keys=True),
                    semantic_id=source.id,
                ),
            ]
        )
