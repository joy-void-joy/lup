"""Codex-native prompt, plugin, skill, agent, and guidance renderers."""

import json
import shlex
from importlib import resources
from pathlib import Path
from typing import assert_never

from lup.harness.contracts import (
    ArtifactRenderer,
    NativePathSpelling,
    PromptRenderer,
    SkillInvocationRenderer,
)
from lup.harness.generation import NativePaths, argument_text, plugin_path, tree_path
from lup.harness.models import (
    Agent,
    ArgumentsRef,
    AskUser,
    Artifact,
    ArtifactTree,
    Delegate,
    Harness,
    HookSet,
    NativePath,
    Plugin,
    PluginLocation,
    PluginPath,
    PromptDocument,
    RelocateSession,
    RequestApproval,
    ResolverEntry,
    RuntimeDocs,
    Skill,
    SkillInvocation,
    SkillPattern,
    TextPart,
    TreeLocation,
)
from lup.policy.bundle import (
    policy_kernel_modules,
    render_policy_data,
    runtime_url_scope,
)


class CodexSkillInvocationRenderer(SkillInvocationRenderer):
    """Render the complete qualified Codex skill mention."""

    def render(self, invocation: SkillInvocation) -> str:
        mention = f"${invocation.plugin}:{invocation.skill}"
        arguments = " ".join(
            f"{argument.name}={shlex.quote(argument_text(argument.value))}"
            for argument in invocation.arguments
        )
        return f"{mention} {arguments}" if arguments else mention


class CodexNativePathSpelling(NativePathSpelling):
    """Spell every harness-owned location the way Codex lays it out.

    Custom agents are the one location Codex keeps outside the plugin, so the
    plugin name is deliberately unused there.
    """

    @property
    def runtime_name(self) -> str:
        return "Codex"

    def tree(self, location: TreeLocation) -> str:
        match location:
            case "tree_root":
                return ".codex/"
            case "guidance_file":
                return "AGENTS.md"
            case "ownership_manifest":
                return ".codex/.lup-ownership.json"
            case "project_settings":
                return ".codex/config.toml"
            case "personal_settings":
                return ".codex/config.local.toml"
            case "marketplace":
                return ".agents/plugins/marketplace.json"

    def plugin(self, plugin: str, location: PluginLocation, member: str | None) -> str:
        root = f".codex/plugins/{plugin}"
        match location:
            case "root":
                return f"{root}/"
            case "manifest":
                return f"{root}/.codex-plugin/plugin.json"
            case "skills":
                return (
                    f"{root}/skills/{member}/SKILL.md" if member else f"{root}/skills/"
                )
            case "agents":
                return f".codex/agents/{member}.toml" if member else ".codex/agents/"
            case "hooks":
                return f"{root}/hooks/"
            case "guidance_template":
                return f"{root}/TEMPLATE_AGENTS.md"


class CodexPromptRenderer(PromptRenderer):
    """Render typed operations directly into Codex prompt instructions."""

    def __init__(
        self, invocations: SkillInvocationRenderer, paths: NativePaths
    ) -> None:
        self.invocations = invocations
        self.paths = paths

    def render(self, prompt: PromptDocument) -> str:
        rendered: list[str] = []  # lup: ignore[empty-collection]
        for part in prompt.parts:
            match part:
                case TextPart(text=text):
                    rendered.append(text)
                case SkillInvocation():
                    rendered.append(self.invocations.render(part))
                case NativePath():
                    rendered.append(tree_path(self.paths, part))
                case PluginPath():
                    rendered.append(plugin_path(self.paths, part))
                case SkillPattern(plugin=plugin, placeholder=placeholder):
                    rendered.append(f"${plugin}:{placeholder}")
                case RuntimeDocs():
                    rendered.append(
                        "the Codex documentation at "
                        "https://developers.openai.com/codex/ and "
                        "https://learn.chatgpt.com/"
                    )
                case AskUser(question=question):
                    rendered.append(
                        "Ask the user directly, offering concrete options, and wait "
                        f"for the answer: {question}"
                    )
                case Delegate(subagent_type=subagent_type, prompt=task):
                    rendered.append(
                        f"Delegate to the {subagent_type} custom agent with this "
                        f"task: {task}"
                    )
                case RequestApproval(action=action, reason=reason):
                    rendered.append(
                        f"Request explicit user approval before {action}. Reason: {reason}"
                    )
                case RelocateSession(path=path):
                    rendered.append(
                        f"start a session rooted at <{path}> and continue there — "
                        "this runtime cannot move a running session, so work "
                        "carried on here would land in the checkout it started from"
                    )
                case ResolverEntry():
                    rendered.append(
                        "Run `uv run lup-devtools harness resolve --adapter codex`. "
                        "The command accepts optional flags: `--run-id <id>` resumes "
                        "a persisted run and `--accept`/`--reject` records the human "
                        "decision on its review branch. A headless run parks on "
                        "material questions — relay them to the user verbatim, never "
                        "answer them yourself, then rerun with the repeatable "
                        "`--answer <question-id>=<value>` flag."
                    )
                case ArgumentsRef():
                    rendered.append("the arguments supplied with this skill invocation")
                case _ as unhandled:
                    assert_never(unhandled)
        text = "".join(rendered)
        return text if text.endswith("\n") else text + "\n"


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

    The declared model tier is left out. Recorded evidence for Codex custom
    agents covers TOML parsing only, so there is no probed alias table to spell
    a tier in; omitting the row lets the agent inherit the session model, which
    is honest where naming another runtime's alias would not be.
    """

    def __init__(self, prompts: PromptRenderer) -> None:
        self.prompts = prompts

    def render(self, source: Agent) -> ArtifactTree:
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

    def __init__(self, prompts: PromptRenderer) -> None:
        self.prompts = prompts

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
                        "[features]\nhooks = true\n"
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


class CodexHookRenderer(ArtifactRenderer[HookSet]):
    """Render Codex hooks, canonical kernel, and application policy rows."""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name

    def render(self, source: HookSet) -> ArtifactTree:
        hooks = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash|apply_patch|web_fetch",
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    'python3 "$PLUGIN_ROOT/hooks/scripts/policy.py"'
                                ),
                                "statusMessage": "Checking Lup policy",
                                "timeout": 30,
                            }
                        ],
                    }
                ]
            }
        }
        evidence = {
            "schemaVersion": 1,
            "policyIds": source.policy_ids,
            "askApproximation": "fail-closed exit code 2",
        }
        return ArtifactTree(
            artifacts=[
                Artifact(
                    path=Path(f".codex/plugins/{self.plugin_name}/hooks/hooks.json"),
                    content=json.dumps(hooks, indent=2, sort_keys=True),
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
                        autonomous_agent_identities=[],
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
