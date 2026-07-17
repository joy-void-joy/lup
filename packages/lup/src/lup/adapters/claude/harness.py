"""Claude-native prompt and artifact renderers."""

import json
import shlex
from importlib import resources
from pathlib import Path

from lup.harness.contracts import ArtifactRenderer, SkillInvocationRenderer
from lup.harness.generation import argument_text
from lup.harness.models import (
    Agent,
    ArgumentsRef,
    AskUser,
    Artifact,
    ArtifactTree,
    Delegate,
    Harness,
    HookSet,
    Plugin,
    PromptDocument,
    RequestApproval,
    ResolverEntry,
    Skill,
    SkillInvocation,
    TextPart,
)
from lup.policy.bundle import (
    policy_kernel_source,
    render_policy_data,
    runtime_url_scope,
)


class ClaudeSkillInvocationRenderer(SkillInvocationRenderer):
    """Render the entire Claude plugin command invocation."""

    def render(self, invocation: SkillInvocation) -> str:
        command = f"/{invocation.plugin}:{invocation.skill}"
        arguments = " ".join(
            f"{argument.name}={shlex.quote(argument_text(argument.value))}"
            for argument in invocation.arguments
        )
        return f"{command} {arguments}" if arguments else command


class ClaudePromptRenderer:
    """Render semantic prompt operations without a post-render rewrite pass."""

    def __init__(self, invocations: SkillInvocationRenderer) -> None:
        self.invocations = invocations

    def render(self, prompt: PromptDocument) -> str:
        rendered: list[str] = []  # lup: ignore[empty-collection]
        for part in prompt.parts:
            match part:
                case TextPart(text=text):
                    rendered.append(text)
                case SkillInvocation():
                    rendered.append(self.invocations.render(part))
                case AskUser(question=question):
                    rendered.append(f"Ask the user this material question: {question}")
                case Delegate(role=role, task=task):
                    rendered.append(f"Delegate to the {role} agent: {task}")
                case RequestApproval(action=action, reason=reason):
                    rendered.append(
                        f"Request explicit user approval before {action}. Reason: {reason}"
                    )
                case ResolverEntry():
                    rendered.append(
                        'Invoke Workflow(scriptPath=".claude/workflows/commands/'
                        'resolve.js", args={}).'
                    )
                case ArgumentsRef():
                    rendered.append("$ARGUMENTS")
        text = "".join(rendered)
        return text if text.endswith("\n") else text + "\n"


class ClaudeSkillRenderer(ArtifactRenderer[Skill]):
    """Render one portable skill as a Claude command Markdown artifact."""

    def __init__(self, prompts: ClaudePromptRenderer, plugin_name: str) -> None:
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

    def __init__(self, prompts: ClaudePromptRenderer, plugin_name: str) -> None:
        self.prompts = prompts
        self.plugin_name = plugin_name

    def render(self, source: Agent) -> ArtifactTree:
        tools = ", ".join(source.tools)
        model = f"model: {source.model}\n" if source.model is not None else ""
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

    def __init__(self, prompts: ClaudePromptRenderer) -> None:
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
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/hooks/runtime/kernel.py"
                    ),
                    content=policy_kernel_source(),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/hooks/runtime/"
                        "policy_data.py"
                    ),
                    content=render_policy_data(
                        allowed_fetch_scopes=[
                            runtime_url_scope(str(scope.origin), scope.path_prefix)
                            for scope in source.allowed_fetch
                        ],
                        denied_fetch_scopes=[
                            runtime_url_scope(str(scope.origin), scope.path_prefix)
                            for scope in source.denied_fetch
                        ],
                        protected_roots=[
                            path.as_posix() for path in source.protected_edit_roots
                        ],
                        autonomous_agent_identities=[
                            "resolve-editor",
                            "lup:resolve-editor",
                        ],
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
