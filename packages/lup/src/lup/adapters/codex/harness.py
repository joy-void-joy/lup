"""Codex-native prompt, plugin, skill, agent, and guidance renderers."""

import json
import shlex
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


class CodexSkillInvocationRenderer(SkillInvocationRenderer):
    """Render the complete qualified Codex skill mention."""

    def render(self, invocation: SkillInvocation) -> str:
        mention = f"${invocation.plugin}:{invocation.skill}"
        arguments = " ".join(
            f"{argument.name}={shlex.quote(argument_text(argument.value))}"
            for argument in invocation.arguments
        )
        return f"{mention} {arguments}" if arguments else mention


class CodexPromptRenderer:
    """Render typed operations directly into Codex prompt instructions."""

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
                    rendered.append(f"Delegate this task to the {role} agent: {task}")
                case RequestApproval(action=action, reason=reason):
                    rendered.append(
                        f"Request explicit user approval before {action}. Reason: {reason}"
                    )
                case ResolverEntry():
                    rendered.append(
                        "Run `uv run lup-devtools harness resolve --adapter codex`. "
                        "The command accepts optional flags: `--run-id <id>` resumes "
                        "a persisted run and `--accept`/`--reject` records the human "
                        "decision on its review branch."
                    )
                case ArgumentsRef():
                    rendered.append("the arguments supplied with this skill invocation")
        text = "".join(rendered)
        return text if text.endswith("\n") else text + "\n"


class CodexSkillRenderer(ArtifactRenderer[Skill]):
    """Render one portable declaration as a same-named Codex skill."""

    def __init__(self, prompts: CodexPromptRenderer, plugin_name: str) -> None:
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
    """Render one portable agent as project-scoped custom-agent TOML."""

    def __init__(self, prompts: CodexPromptRenderer) -> None:
        self.prompts = prompts

    def render(self, source: Agent) -> ArtifactTree:
        rows = [
            f"name = {json.dumps(source.name)}",
            f"description = {json.dumps(source.description)}",
            (
                "developer_instructions = "
                f"{json.dumps(self.prompts.render(source.prompt))}"
            ),
        ]
        if source.model is not None:
            rows.append(f"model = {json.dumps(source.model)}")
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
            "name": "lup-repository",
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

    def __init__(self, prompts: CodexPromptRenderer) -> None:
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
                    content="[features]\nhooks = true\n",
                    semantic_id="harness.project-config",
                ),
            ]
        )


CODEX_POLICY_DISPATCHER = '''#!/usr/bin/env python3
"""Generated Codex hook dispatcher over the canonical semantic kernel."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from kernel import KernelDecision, decide_fetch, decide_shell
from policy_data import ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    if name == "Bash":
        return decide_shell(tool_input["command"])
    if name == "web_fetch":
        return decide_fetch(
            tool_input["url"],
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
        )
    if name == "apply_patch":
        return KernelDecision(
            "ask",
            "opaque patch input requires native parsing before it can be auto-allowed",
        )
    return KernelDecision("ask", f"unknown tool {name!r} is not covered by policy")


def main():
    try:
        decision = dispatch(json.load(sys.stdin))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"Malformed hook input requires approval: {error}")
        raise SystemExit(2) from error
    if decision.effect == "allow":
        return
    sys.stderr.write(decision.reason)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
'''


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
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/runtime/kernel.py"
                    ),
                    content=policy_kernel_source(),
                    semantic_id=source.id,
                ),
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/runtime/"
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
                        autonomous_agent_identities=[],
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
