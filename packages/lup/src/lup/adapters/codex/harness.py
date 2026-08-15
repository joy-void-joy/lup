"""Codex-native prompt, plugin, skill, agent, and guidance renderers."""

import json
import shlex
from importlib import resources
from pathlib import Path

import tomlkit
from lup.adapters.codex.login import CODEX_LOGIN
from lup.harness.banner import (
    PROMPT_TEXT,
    REGENERATE_COMMAND,
    VERBATIM_COPY,
    GeneratedBanner,
)
from lup.harness.contracts import (
    ArtifactRenderer,
    Atom,
    Instruction,
    NativeSpellings,
    PromptRenderer,
)
from lup.harness.generation import argument_text
from lup.harness.prompts import guidance_banner
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
    POLICY_DATA_BANNER,
    policy_kernel_modules,
    render_policy_data,
    runtime_url_scope,
)
from lup.policy.dispatcher import (
    DispatcherDeclaration,
    compile_dispatcher,
    dispatcher_banner,
)
from lup.policy.kernel.rows import PathRoleRow
from lup.policy.refused_tools import routed_for
from lup.policy.kernel.words import (
    INTERPRETERS,
    PASS_THROUGH_WORDS,
)
from lup.policy.shell_rules import (
    RunnerTargetRule,
    ShellCommandRule,
    erase_shell_rules,
)


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

    # lup: The Claude entry now tells the agent to launch the run outside the
    # sandbox, because a session spawned inside it loses every shell call. This
    # one says nothing, and inventing a flag would be worse than the silence:
    # the Codex overrides this repository knows are session-level flags on the
    # binary, not a per-call escape a skill can ask for. "Run this outside the
    # sandbox" is a portable idea with a per-runtime spelling, so it wants a
    # `NativeSpellings` method beside `ask_user` — and if Codex has no per-call
    # escape, the explicit unsupported declaration the adapter-parity concern
    # asks for, carrying the reason.
    def resolver_entry(self) -> Instruction:
        return Instruction(
            "Run `uv run lup-devtools harness resolve --adapter codex`. "
            "`uv run lup-devtools harness resolve intake` first prints what a "
            "run started now would plan from — every actionable note at its "
            "file and line, the deferred ones it would carry, and the ones it "
            "would leave to their generator — creating no run and leasing no "
            "worktree, so the inventory can be read before committing to it. "
            "The command accepts optional flags: `--run-id <id>` resumes "
            "a persisted run. Assembling the review branch is gated on the "
            "reserved `integration-assembly` question, so approving it is "
            "`--answer integration-assembly=approve` like any other answer. "
            "It waits zero seconds by "
            "default and parks on material questions, printing each one "
            "beside the `# lup:` notes it was raised from, the concern's "
            "spec, and its acceptance criteria; rerun with the repeatable "
            "`--answer <question-id>=<value>` flag to answer them. "
            "`--admit <text>` carries work in the human's own words: it seeds "
            "a run that does not exist yet, beside whatever notes the tree "
            "holds, and joins one already moving. `--admit-note <file>:<line>` "
            "names a note written in the tree and `--admit-issue <number>` an "
            "open issue; all three are repeatable. "
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

    def project_root(self) -> str:
        # Codex substitutes nothing into a server command, but it reads this
        # config only for the project the config sits in, so the launch
        # directory is that project by construction. Naming it explicitly is
        # what makes a server started anywhere else fail instead of resolving
        # up the tree into a neighbouring checkout.
        return "."

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
                    banner=PROMPT_TEXT,
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
                Artifact.generated(
                    path=Path(f".codex/agents/{source.name}.toml"),
                    body="\n".join(rows),
                    semantic_id=source.id,
                    banner=GeneratedBanner(
                        source=f"the portable agent declaration {source.id}",
                        command=REGENERATE_COMMAND,
                    ),
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


def codex_project_config(
    source: Harness, spellings: NativeSpellings, budget: int = GUIDANCE_BYTE_BUDGET
) -> str:
    """Render the project config: enabled features, then every tool server.

    Codex keeps a project's servers in the same file as the rest of its
    project configuration, so this is one document rather than the separate
    artifact the other runtime reads.

    The guidance ceiling generation already enforces is restated here as
    ``project_doc_max_bytes``: the runtime truncates project guidance at its
    own default, so a document that passed generation would still reach the
    model short if the two disagreed.
    """
    document = tomlkit.document()
    features = tomlkit.table()
    features["hooks"] = True
    document["features"] = features
    document["project_doc_max_bytes"] = budget
    servers = tomlkit.table(is_super_table=True)
    for plugin in source.plugins:
        for server in plugin.mcp_servers:
            entry = tomlkit.table()
            entry["command"] = server.command
            entry["args"] = server.command_line(spellings)
            servers[server.name] = entry
    if servers:
        document["mcp_servers"] = servers
    return tomlkit.dumps(document)


class CodexGuidanceRenderer(ArtifactRenderer[Harness]):
    """Render root project guidance at Codex's documented repository location."""

    def __init__(
        self,
        prompts: PromptRenderer,
        spellings: NativeSpellings,
        budget: int = GUIDANCE_BYTE_BUDGET,
    ) -> None:
        self.prompts = prompts
        self.spellings = spellings
        self.budget = budget

    def render(self, source: Harness) -> ArtifactTree:
        return ArtifactTree(
            artifacts=[
                Artifact.generated(
                    path=Path("AGENTS.md"),
                    body=self.prompts.render(source.guidance),
                    semantic_id="harness.guidance",
                    banner=guidance_banner(self.prompts, source.guidance),
                ),
                Artifact.generated(
                    path=Path(".codex/config.toml"),
                    body=codex_project_config(source, self.spellings, self.budget),
                    semantic_id="harness.project-config",
                    banner=GeneratedBanner(
                        source=__name__,
                        command=REGENERATE_COMMAND,
                        notes=[
                            "Personal sandbox and approval defaults stay in "
                            "~/.codex/config.toml.",
                            "Native shell allows are generated under .codex/rules/.",
                            "Tool servers start from this project, so start "
                            "the runtime at its root.",
                        ],
                    ),
                ),
            ]
        )


CODEX_DISPATCHER = DispatcherDeclaration(
    runtime_name="Codex",
    package="lup.adapters.codex",
    managed_root_env=CODEX_LOGIN.config_home_env,
    routed_tools=["Bash", "web_fetch", "apply_patch"],
    hook_events=["PermissionRequest", "PreToolUse"],
    failure="stderr_exit",
    runtime_modules=["codex_patch", "policy_data"],
)
"""Everything Codex spells differently from every other runtime.

Both hook events reach the same dispatcher: the permission request carries
the approval channel an ask needs, and the pre-tool event covers the paths
that never raise one. The tools named here are both what the plugin
registers the hook for and what the compiler proves the dispatcher routes.
"""

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


def codex_allow_prefixes(
    rules: list[ShellCommandRule], runner_targets: list[RunnerTargetRule]
) -> list[list[str]]:
    """Compile semantic allows that stay allowed for every suffix.

    Codex prefix rules bypass the sandbox, so flag-guarded rows cannot be
    widened into a native allow, and neither can one placed ``inside``, whose
    whole statement is that the call runs confined however the session is
    running. The runtime hook continues to classify those forms, along with
    every command whose safety depends on parsed content.

    The erased rows are what this reads rather than the declarations they came
    from, because the rows are where both axes have been resolved down the
    nesting: a level that inherited its effect is native-allowed on exactly the
    terms of one that spelled it out, which is the same reading the dispatcher
    and the canonical policy take.

    That bypass is also the whole of this runtime's escape, which is why a
    runner target's placement does not narrow what is emitted here: a target
    declared ``outside`` reaches the outside through its prefix rule or not at
    all. The forms this cannot widen — a target behind a global flag, or one
    joined into a compound command — reach the hook, where a confined session
    is stopped with the reason rather than left to fail on the first write.
    """

    def add(prefix: list[str]) -> None:
        if prefix not in prefixes:
            prefixes.append(prefix)

    rows = erase_shell_rules(rules)
    gated = dict.fromkeys(row["command"] for row in rows if row["subcommand"])
    operational = dict.fromkeys(
        f"{row['command']} {row['subcommand']}" for row in rows if row["operation"]
    )
    prefixes: list[list[str]] = []
    for row in rows:
        if row["effect"] != "allow" or row["ask_flags"] or row["sandbox"] == "inside":
            continue
        if not row["subcommand"]:
            dynamic = row["command"] in CODEX_DYNAMIC_COMMANDS
            if row["command"] not in gated and not dynamic:
                add([row["command"]])
        elif row["operation"]:
            add([row["command"], row["subcommand"], row["operation"]])
        elif f"{row['command']} {row['subcommand']}" not in operational:
            add([row["command"], row["subcommand"]])
    for target in runner_targets:
        add(["uv", "run", target.name])
    return sorted(prefixes)


def render_codex_rules(source: HookSet) -> str:
    """Render project-local native execution rules for prefix-safe allows."""
    rows = [
        f"prefix_rule(pattern = {json.dumps(prefix)}, decision = "
        '"allow", justification = "Allowed by Lup semantic shell policy")'
        for prefix in codex_allow_prefixes(
            source.shell_rules, list(source.runner_targets)
        )
    ]
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
        registration = [
            {
                "matcher": "|".join(
                    routed_for(CODEX_DISPATCHER.routed_tools, source.refused_tools)
                ),
                "hooks": [policy_hook],
            }
        ]
        hooks = {
            "hooks": {event: registration for event in CODEX_DISPATCHER.hook_events}
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
                Artifact.generated(
                    path=Path(f".codex/rules/{self.plugin_name}.rules"),
                    body=render_codex_rules(source),
                    semantic_id=source.id,
                    banner=GeneratedBanner(
                        source="lup.policy.shell_rules",
                        command=REGENERATE_COMMAND,
                    ),
                ),
                Artifact(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/scripts/policy.py"
                    ),
                    content=compile_dispatcher(CODEX_DISPATCHER),
                    semantic_id=source.id,
                    executable=True,
                    banner=dispatcher_banner(CODEX_DISPATCHER),
                ),
                *[
                    Artifact(
                        path=Path(
                            f".codex/plugins/{self.plugin_name}/hooks/runtime/"
                            f"kernel/{module.name}"
                        ),
                        content=module.source,
                        semantic_id=source.id,
                        banner=VERBATIM_COPY,
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
                    banner=VERBATIM_COPY,
                ),
                Artifact.generated(
                    path=Path(
                        f".codex/plugins/{self.plugin_name}/hooks/runtime/"
                        "policy_data.py"
                    ),
                    banner=POLICY_DATA_BANNER,
                    body=render_policy_data(
                        allowed_fetch_scopes=[
                            runtime_url_scope(
                                str(scope.origin),
                                scope.path_prefix,
                                reason=scope.reason,
                                include_subdomains=scope.include_subdomains,
                            )
                            for scope in source.allowed_fetch
                        ],
                        denied_fetch_scopes=[
                            runtime_url_scope(
                                str(scope.origin),
                                scope.path_prefix,
                                reason=scope.reason,
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
                        path_roles=[
                            PathRoleRow(root=role.root.as_posix(), role=role.role)
                            for role in source.path_roles
                        ],
                        shell_rules=list(source.shell_rules),
                        refused_tools=list(source.refused_tools),
                        recoverable_target_limit=source.recoverable_target_limit,
                        runner_targets=list(source.runner_targets),
                        sandbox_excluded_commands=source.excluded_commands(),
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
