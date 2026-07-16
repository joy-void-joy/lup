"""Claude-native prompt and artifact renderers."""

import json
import shlex
from pathlib import Path

from lup.harness.contracts import ArtifactRenderer, SkillInvocationRenderer
from lup.harness.generation import argument_text
from lup.harness.models import (
    Agent,
    AskUser,
    Artifact,
    ArtifactTree,
    Delegate,
    Harness,
    HookSet,
    HookUrlScope,
    Plugin,
    PromptDocument,
    RequestApproval,
    ResolverEntry,
    Skill,
    SkillInvocation,
    TextPart,
)
from lup.policy.bundle import BUNDLED_POLICY_SOURCE


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
                        'resolve.js", args={}).'  # lup: ignore[empty-collection]
                    )
        text = "".join(rendered)
        return text if text.endswith("\n") else text + "\n"


class ClaudeSkillRenderer(ArtifactRenderer[Skill]):
    """Render one portable skill as a Claude command Markdown artifact."""

    def __init__(self, prompts: ClaudePromptRenderer, plugin_name: str) -> None:
        self.prompts = prompts
        self.plugin_name = plugin_name

    def render(self, source: Skill) -> ArtifactTree:
        arguments = (
            "\n".join(
                f"  - name: {argument.name}\n"
                f"    description: {json.dumps(argument.description)}\n"
                f"    required: {str(argument.required).lower()}"
                for argument in source.arguments
            )
            if source.arguments
            else "  []"
        )
        content = (
            "---\n"
            f"description: {json.dumps(source.description)}\n"
            f"arguments:\n{arguments}\n"
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
        content = (
            "---\n"
            f"name: {source.name}\n"
            f"description: {json.dumps(source.description)}\n"
            f"tools: {tools}\n"
            f"{model}"
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


CLAUDE_RESOLVER_ENTRY = """export const meta = {
  name: 'resolve',
  description: 'Enter Lup\\'s shared persisted Python resolver.',
  phases: [{ title: 'Resolve', detail: 'shared Python resolver core' }],
}

const input = typeof args === 'string' ? JSON.parse(args) : args || {}
const command = [
  'uv',
  'run',
  'lup-devtools',
  'harness',
  'resolve',
  '--adapter',
  'claude',
]
if (input.run_id) {
  command.push('--run-id', input.run_id)
}
if (input.accept === true) {
  command.push('--accept')
} else if (input.accept === false) {
  command.push('--reject')
}

const child = Bun.spawn(command, {
  cwd: process.cwd(),
  stdin: 'inherit',
  stdout: 'inherit',
  stderr: 'inherit',
})
const exitCode = await child.exited
if (exitCode !== 0) {
  throw new Error(`shared resolver exited with status ${exitCode}`)
}
return { exit_code: exitCode }
"""


CLAUDE_POLICY_DISPATCHER = '''#!/usr/bin/env python3
"""Generated Claude hook dispatcher over the bundled semantic runtime."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from policy import Decision, decide_edit, decide_fetch, decide_shell

ALLOWED_FETCH_SCOPES = __ALLOWED_FETCH_SCOPES__
DENIED_FETCH_SCOPES = __DENIED_FETCH_SCOPES__
PROTECTED_EDIT_ROOTS = __PROTECTED_EDIT_ROOTS__


def edit_documents(path, old_text, new_text):
    current = Path(path).read_text(encoding="utf-8")
    if current.count(old_text) != 1:
        raise ValueError("Edit preimage must occur exactly once")
    position = current.find(old_text)
    updated = current[:position] + new_text + current[position + len(old_text) :]
    return current, updated


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    agent_type = payload["agent_type"] if "agent_type" in payload else ""
    if name == "Bash":
        return decide_shell(tool_input["command"])
    if name == "WebFetch":
        return decide_fetch(
            tool_input["url"],
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
        )
    if name == "Edit":
        before, after = edit_documents(
            tool_input["file_path"],
            tool_input["old_string"],
            tool_input["new_string"],
        )
        return decide_edit(
            tool_input["file_path"],
            before,
            after,
            PROTECTED_EDIT_ROOTS,
            agent_type,
        )
    if name == "Write":
        path = Path(tool_input["file_path"])
        return decide_edit(
            tool_input["file_path"],
            path.read_text(encoding="utf-8") if path.exists() else None,
            tool_input["content"],
            PROTECTED_EDIT_ROOTS,
            agent_type,
        )
    return Decision("ask", "tool is not classified")


def rendered(decision):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.effect,
            "permissionDecisionReason": decision.reason,
        }
    }


def main():
    try:
        decision = dispatch(json.load(sys.stdin))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        decision = Decision("ask", f"Malformed hook input requires approval: {error}")
    json.dump(rendered(decision), sys.stdout)


if __name__ == "__main__":
    main()
'''


class ClaudeHookRenderer(ArtifactRenderer[HookSet]):
    """Render Claude plugin hooks and the shared dependency-free snapshot."""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name

    def render(self, source: HookSet) -> ArtifactTree:
        dispatcher = configured_dispatcher(CLAUDE_POLICY_DISPATCHER, source)
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
                    content=dispatcher,
                    semantic_id=source.id,
                    executable=True,
                ),
                Artifact(
                    path=Path(
                        f".claude/plugins/{self.plugin_name}/hooks/runtime/policy.py"
                    ),
                    content=BUNDLED_POLICY_SOURCE,
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


def configured_dispatcher(template: str, source: HookSet) -> str:
    """Render application-owned policy scopes into a hermetic native entry."""
    replacements = {
        "__ALLOWED_FETCH_SCOPES__": render_fetch_scopes(source.allowed_fetch),
        "__DENIED_FETCH_SCOPES__": render_fetch_scopes(source.denied_fetch),
        "__PROTECTED_EDIT_ROOTS__": render_string_list(
            [path.as_posix() for path in source.protected_edit_roots]
        ),
    }
    rendered = template
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)  # lup: ignore[string-replace]
    return rendered


def render_fetch_scopes(scopes: list[HookUrlScope]) -> str:
    """Render scopes in a stable formatter-compatible Python literal."""
    if not scopes:
        return "[]  # lup: ignore[empty-collection]"
    rows = [
        "    {\n"
        f'        "origin": {json.dumps(str(scope.origin))},\n'
        f'        "path_prefix": {json.dumps(scope.path_prefix)},\n'
        "    },"
        for scope in scopes
    ]
    return "[\n" + "\n".join(rows) + "\n]"


def render_string_list(values: list[str]) -> str:
    """Render strings in a stable formatter-compatible Python literal."""
    if not values:
        return "[]  # lup: ignore[empty-collection]"
    return "[\n" + "\n".join(f"    {json.dumps(value)}," for value in values) + "\n]"
