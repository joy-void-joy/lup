"""Genuinely shared harness vocabulary: declarations and rendered artifacts.

The canonical declaration graph (``Harness`` down to prompt parts) that the
application declares and the adapter renderers, devtools generation flows, and
resolver consume, plus the rendered ``Artifact``/``ArtifactTree`` and probe
evidence shared by every pipeline stage. A model owned by one concern lives
beside its managing module instead (see the package docstring).
"""

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    model_validator,
)

from lup.policy.models import PolicyId, UrlPathPrefix
from lup.policy.shell_rules import ShellCommandRule
from lup.types import JsonValue, ToolGrant, ToolName

FROZEN = ConfigDict(frozen=True)

type NativeName = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")
]
"""A declaration name portable across adapters: lowercase alphanumerics with
interior hyphens or underscores."""

type QualifiedAgentName = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]*:[a-z0-9][a-z0-9_-]*$")
]
"""A delegation target, ``<plugin>:<agent>``, as a runtime addresses one."""


class TextPart(BaseModel):
    model_config = FROZEN

    type: Literal["text"] = "text"
    text: str


class InvocationArgument(BaseModel):
    model_config = FROZEN

    name: NativeName
    value: JsonValue


class SkillInvocation(BaseModel):
    model_config = FROZEN

    type: Literal["skill_invocation"] = "skill_invocation"
    plugin: NativeName
    skill: NativeName
    arguments: list[InvocationArgument] = Field(default_factory=list)


type TreeLocation = Literal[
    "tree_root",
    "guidance_file",
    "ownership_manifest",
    "project_settings",
    "personal_settings",
    "marketplace",
]
"""One harness-tree location every runtime spells for itself."""


type PluginLocation = Literal[
    "root",
    "manifest",
    "skills",
    "agents",
    "hooks",
    "guidance_template",
]
"""One location an installed plugin owns, or that a runtime keeps beside it."""


type PathScope = Literal["this_tree", "every_tree"]
"""Whether a path addresses the reader's own tree or teaches every tree."""


type PathMember = Annotated[
    str, StringConstraints(pattern=r"^(\*|<[a-z][a-z0-9-]*>|[a-z0-9][a-z0-9-]*)$")
]
"""One leaf inside a location: a name, a ``<placeholder>``, or ``*``."""


class NativePath(BaseModel):
    """One harness-tree location, spelled by whichever adapter renders it."""

    model_config = FROZEN

    type: Literal["native_path"] = "native_path"
    location: TreeLocation
    scope: PathScope = "this_tree"


class PluginPath(BaseModel):
    """One plugin-owned location, spelled by whichever adapter renders it.

    ``member`` selects a leaf whose whole path differs per runtime — a skill is
    one file under one runtime and a directory under another — while omitting
    it names the containing directory.
    """

    model_config = FROZEN

    type: Literal["plugin_path"] = "plugin_path"
    plugin: NativeName
    location: PluginLocation
    member: PathMember | None = None
    scope: PathScope = "this_tree"


class SkillPattern(BaseModel):
    """An invocation shape standing in for a skill the reader will name.

    ``SkillInvocation`` resolves against the declaration registry, so it cannot
    express the placeholder or wildcard a prompt uses when it teaches the shape
    of an invocation rather than issuing one.
    """

    model_config = FROZEN

    type: Literal["skill_pattern"] = "skill_pattern"
    plugin: NativeName
    placeholder: PathMember


class RuntimeDocs(BaseModel):
    """The reader's own runtime documentation, wherever that runtime is."""

    model_config = FROZEN

    type: Literal["runtime_docs"] = "runtime_docs"


class AskUser(BaseModel):
    model_config = FROZEN

    type: Literal["ask_user"] = "ask_user"
    question: str


class Delegate(BaseModel):
    model_config = FROZEN

    type: Literal["delegate"] = "delegate"
    subagent_type: QualifiedAgentName
    prompt: str


class RequestApproval(BaseModel):
    model_config = FROZEN

    type: Literal["request_approval"] = "request_approval"
    action: str
    reason: str


class RelocateSession(BaseModel):
    """Continue work inside an already-created worktree.

    Runtimes differ on whether a running session can move: one relocates in
    place, another can only be replaced by a session started there. Naming
    the intent lets each adapter spell the move it actually supports.
    """

    model_config = FROZEN

    type: Literal["relocate_session"] = "relocate_session"
    path: str
    """Where the reader finds the path, e.g. "the path step 1 prints"."""


class ResolverEntry(BaseModel):
    model_config = FROZEN

    type: Literal["resolver_entry"] = "resolver_entry"


class ArgumentsRef(BaseModel):
    model_config = FROZEN

    type: Literal["arguments_ref"] = "arguments_ref"


type PromptPart = Annotated[
    TextPart
    | SkillInvocation
    | NativePath
    | PluginPath
    | SkillPattern
    | RuntimeDocs
    | AskUser
    | Delegate
    | RequestApproval
    | RelocateSession
    | ResolverEntry
    | ArgumentsRef,
    Discriminator("type"),
]


class PromptDocument(BaseModel):
    model_config = FROZEN

    parts: list[PromptPart]


GUIDANCE_CHARACTER_BUDGET = 32_768
"""Ceiling on the guidance document every session loads before its first turn.

What a session pays for is the rendered document, so that is what the adapters
check as they compile it. A typed part costs whatever its adapter spells it as,
however little literal text the declaration holds. Reference material that a
skill or a denial message surfaces at the right moment belongs in a generated
document under ``docs/`` instead, reached by a file-path pointer."""


def document_text_size(document: PromptDocument) -> int:
    """Lower bound on what a document costs a session, in literal characters.

    Every part renders to something, so the rendered document is never smaller.
    This is the share a neutral module can measure without reaching for an
    adapter to spell the rest.
    """
    return sum(len(part.text) for part in document.parts if isinstance(part, TextPart))


class Argument(BaseModel):
    model_config = FROZEN

    name: NativeName
    description: str = Field(min_length=1, max_length=1024)
    required: bool = False


class Skill(BaseModel):
    model_config = FROZEN

    id: str
    name: NativeName
    description: str = Field(min_length=1, max_length=1024)
    arguments: list[Argument] = Field(default_factory=list)
    tools: list[ToolGrant] = Field(default_factory=list)
    argument_hint: str | None = None
    prompt: PromptDocument

    @model_validator(mode="after")
    def coherent_arguments(self) -> "Skill":
        names = [argument.name for argument in self.arguments]
        if len(names) != len(dict.fromkeys(names)):
            raise ValueError(f"skill {self.id!r} has duplicate argument names")
        optional_seen = False
        for argument in self.arguments:
            if not argument.required:
                optional_seen = True
            elif optional_seen:
                raise ValueError(
                    f"skill {self.id!r} has a required argument after an optional one"
                )
        references_arguments = any(
            isinstance(part, ArgumentsRef) for part in self.prompt.parts
        )
        if bool(self.arguments) != references_arguments:
            raise ValueError(
                f"skill {self.id!r} argument declarations and ArgumentsRef disagree"
            )
        return self


type AgentColor = Literal[
    "red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"
]
"""The closed agent accent-color palette native runtimes accept."""


type ModelTier = Literal["inherit", "strongest", "balanced", "fast"]
"""Portable model preference for one role.

Runtimes name and version their own model lineups, so a declaration states the
need and each adapter spells whichever tier it can honor — or omits the choice
where it has no proven vocabulary to spell it in."""


class Agent(BaseModel):
    model_config = FROZEN

    id: str
    name: NativeName
    description: str = Field(min_length=1, max_length=1024)
    prompt: PromptDocument
    tools: list[ToolName] = Field(default_factory=list)
    model: ModelTier | None = None
    color: AgentColor | None = None


class HookUrlScope(BaseModel):
    """Portable generated-hook URL scope configured by the application."""

    model_config = FROZEN

    origin: AnyHttpUrl
    path_prefix: UrlPathPrefix = "/"
    include_subdomains: bool = Field(
        default=False,
        description=(
            "Extend the scope to every host beneath the origin, rendered as a "
            "*.host wildcard in the OS sandbox network allowlist"
        ),
    )


class HookSandbox(BaseModel):
    """OS sandbox declaration compiled into native settings and launchers.

    Fetch-scope hostnames join extra_domains as the network allowlist,
    human-owned files become OS-level write denials, and writable_paths become
    the grants that let a sandboxed toolchain reach its caches, so one
    declaration feeds both the semantic policy and the kernel-enforced
    boundary.

    That makes allowed_fetch the home for any origin an agent should be able
    to read: declaring it there grants both the fetch and the egress. Reserve
    extra_domains for hosts that need egress but are not readable sources —
    an authenticated API a library calls, never a document the agent opens.
    Listing a readable origin here instead is what lets the two boundaries
    disagree, with the OS admitting a host the fetch policy still asks about.
    """

    model_config = FROZEN

    extra_domains: list[str] = Field(default_factory=list)
    credential_paths: list[str] = Field(default_factory=list)
    writable_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Paths outside the workspace a sandboxed toolchain must write. "
            "A tool that cannot reach its cache fails only when the cache is "
            "cold, so an undeclared path reads as an intermittent fault rather "
            "than a boundary; declaring it here states the requirement where "
            "the rest of the boundary is stated."
        ),
    )


class HookSet(BaseModel):
    model_config = FROZEN

    id: str
    policy_ids: list[PolicyId]
    allowed_fetch: list[HookUrlScope] = Field(default_factory=list)
    denied_fetch: list[HookUrlScope] = Field(default_factory=list)
    protected_edit_roots: list[Path] = Field(default_factory=list)
    human_owned_files: list[Path] = Field(
        default_factory=list,
        description=(
            "Files whose content the human author owns; every edit is surfaced "
            "as Ask so agents propose changes instead of applying them"
        ),
    )
    shell_rules: list[ShellCommandRule] = Field(
        default_factory=list,
        description=(
            "Application-specific shell command rules appended to the baseline "
            "vocabulary; extend a downstream toolchain here, not in the kernel"
        ),
    )
    sandbox: HookSandbox | None = None


class ResolveSpec(BaseModel):
    model_config = FROZEN

    id: str
    worker_identity: NativeName
    """The identity a worker session declares, and the one the edit policy
    grants autonomy to. Both adapters derive their autonomous list from this
    single fact, so a runtime cannot silently ship an empty one."""

    worker_skill: SkillInvocation
    review_skill: SkillInvocation
    merge_skill: SkillInvocation


class Plugin(BaseModel):
    model_config = FROZEN

    id: str
    name: NativeName
    # Namespaces the plugin inside the selected CODEX_HOME and remains required
    # for callers that deliberately share one home across projects.
    marketplace: NativeName
    version: str
    description: str = Field(min_length=1, max_length=1024)
    skills: list[Skill]
    agents: list[Agent]
    hooks: HookSet | None = None

    @model_validator(mode="after")
    def unique_effective_names(self) -> "Plugin":
        skill_names = [skill.name for skill in self.skills]
        agent_names = [agent.name for agent in self.agents]
        if len(skill_names) != len(dict.fromkeys(skill_names)):
            raise ValueError(f"plugin {self.id!r} has duplicate skill names")
        if len(agent_names) != len(dict.fromkeys(agent_names)):
            raise ValueError(f"plugin {self.id!r} has duplicate agent names")
        return self


class Harness(BaseModel):
    model_config = FROZEN

    schema_version: int = 1
    generator_version: str
    source_evidence: dict[str, str] = Field(  # lup: ignore[dict-str-payload]
        default_factory=dict
    )
    plugins: list[Plugin]
    guidance: PromptDocument
    resolver: ResolveSpec

    @model_validator(mode="after")
    def unique_semantic_ids(self) -> "Harness":
        ids = [
            declaration_id
            for plugin in self.plugins
            for declaration_id in [
                plugin.id,
                *[skill.id for skill in plugin.skills],
                *[agent.id for agent in plugin.agents],
            ]
        ]
        if len(ids) != len(dict.fromkeys(ids)):
            raise ValueError("harness semantic ids must be globally unique")
        plugin_names = [plugin.name for plugin in self.plugins]
        if len(plugin_names) != len(dict.fromkeys(plugin_names)):
            raise ValueError("harness plugin names must be unique")
        agent_names = [agent.name for plugin in self.plugins for agent in plugin.agents]
        if len(agent_names) != len(dict.fromkeys(agent_names)):
            raise ValueError("harness agent names must be globally unique")
        discovery_size = sum(
            len(declaration.description)
            for plugin in self.plugins
            for declaration in [plugin, *plugin.skills, *plugin.agents]
        )
        if discovery_size > 32_768:
            raise ValueError("harness discovery descriptions exceed 32768 characters")

        skills = {
            (plugin.name, skill.name): skill
            for plugin in self.plugins
            for skill in plugin.skills
        }
        prompts = [
            self.guidance,
            *[
                declaration.prompt
                for plugin in self.plugins
                for declaration in [*plugin.skills, *plugin.agents]
            ],
        ]
        invocations = [
            part
            for prompt in prompts
            for part in prompt.parts
            if isinstance(part, SkillInvocation)
        ]
        invocations.extend(
            [
                self.resolver.worker_skill,
                self.resolver.review_skill,
                self.resolver.merge_skill,
            ]
        )
        for invocation in invocations:
            skill = skills.get(  # lup: ignore[dict-get] — open declaration registry
                (invocation.plugin, invocation.skill)
            )
            if skill is None:
                raise ValueError(
                    "skill invocation refers to an unknown declaration: "
                    f"{invocation.plugin}:{invocation.skill}"
                )
            supplied = [argument.name for argument in invocation.arguments]
            if len(supplied) != len(dict.fromkeys(supplied)):
                raise ValueError(
                    f"skill invocation {invocation.plugin}:{invocation.skill} "
                    "has duplicate arguments"
                )
            declared = [argument.name for argument in skill.arguments]
            if any(name not in declared for name in supplied):
                raise ValueError(
                    f"skill invocation {invocation.plugin}:{invocation.skill} "
                    "has an unknown argument"
                )
            expected_order = [name for name in declared if name in supplied]
            if supplied != expected_order:
                raise ValueError(
                    f"skill invocation {invocation.plugin}:{invocation.skill} "
                    "arguments are not in declaration order"
                )
            missing = [
                argument.name
                for argument in skill.arguments
                if argument.required and argument.name not in supplied
            ]
            if missing:
                raise ValueError(
                    f"skill invocation {invocation.plugin}:{invocation.skill} "
                    f"is missing required arguments: {missing}"
                )

        declared_agents = [
            f"{plugin.name}:{agent.name}"
            for plugin in self.plugins
            for agent in plugin.agents
        ]
        parts = [part for prompt in prompts for part in prompt.parts]
        unknown_plugins = [
            part.plugin
            for part in parts
            if isinstance(part, PluginPath | SkillPattern)
            and part.plugin not in plugin_names
        ]
        if unknown_plugins:
            raise ValueError(f"prompt parts name unknown plugins: {unknown_plugins}")
        unknown_agents = [
            part.subagent_type
            for part in parts
            if isinstance(part, Delegate) and part.subagent_type not in declared_agents
        ]
        if unknown_agents:
            raise ValueError(f"delegations name unknown agents: {unknown_agents}")

        used = document_text_size(self.guidance)
        if used > GUIDANCE_CHARACTER_BUDGET:
            raise ValueError(
                f"always-loaded guidance is {used} characters, over the "
                f"{GUIDANCE_CHARACTER_BUDGET} budget by "
                f"{used - GUIDANCE_CHARACTER_BUDGET}. Move a section to a "
                "generated document under docs/ and leave a file-path pointer, "
                "the way Self-Improvement Loop and Permission Hooks were split."
            )
        return self


def path_beneath_root(value: Path) -> Path:
    raw = str(value)
    portable = PurePosixPath(value.as_posix())
    if (
        "\\" in raw
        or "\0" in raw
        or value.is_absolute()
        or ".." in portable.parts
        or portable == PurePosixPath(".")
    ):
        raise ValueError(f"artifact path must stay beneath its root: {value}")
    return value


type ArtifactPath = Annotated[Path, AfterValidator(path_beneath_root)]
"""A relative path proven unable to escape or alias the root it joins."""


def lf_normalized(value: str) -> str:
    if "\r" in value:
        raise ValueError("artifact content must use LF newlines")
    return value if not value or value.endswith("\n") else value + "\n"


type NormalizedText = Annotated[str, AfterValidator(lf_normalized)]
"""LF-only text, normalized to terminate in a newline."""


class Artifact(BaseModel):
    model_config = FROZEN

    path: ArtifactPath
    content: NormalizedText
    semantic_id: str = Field(min_length=1)
    executable: bool = False


class ArtifactTree(BaseModel):
    model_config = FROZEN

    artifacts: list[Artifact]

    @model_validator(mode="after")
    def unique_paths(self) -> "ArtifactTree":
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(dict.fromkeys(paths)):
            raise ValueError("artifact paths must be unique")
        return self


class CapabilityEvidence[C](BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    capability: str
    supported: bool
    evidence: C
    version: str
