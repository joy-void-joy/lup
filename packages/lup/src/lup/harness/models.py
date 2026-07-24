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


class AskUser(BaseModel):
    model_config = FROZEN

    type: Literal["ask_user"] = "ask_user"
    question: str


class Delegate(BaseModel):
    model_config = FROZEN

    type: Literal["delegate"] = "delegate"
    role: str
    task: str


class RequestApproval(BaseModel):
    model_config = FROZEN

    type: Literal["request_approval"] = "request_approval"
    action: str
    reason: str


class ResolverEntry(BaseModel):
    model_config = FROZEN

    type: Literal["resolver_entry"] = "resolver_entry"


class ArgumentsRef(BaseModel):
    model_config = FROZEN

    type: Literal["arguments_ref"] = "arguments_ref"


type PromptPart = Annotated[
    TextPart
    | SkillInvocation
    | AskUser
    | Delegate
    | RequestApproval
    | ResolverEntry
    | ArgumentsRef,
    Discriminator("type"),
]


class PromptDocument(BaseModel):
    model_config = FROZEN

    parts: list[PromptPart]


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


class Agent(BaseModel):
    model_config = FROZEN

    id: str
    name: NativeName
    description: str = Field(min_length=1, max_length=1024)
    prompt: PromptDocument
    tools: list[ToolName] = Field(default_factory=list)
    model: str | None = None
    color: AgentColor | None = None


class HookUrlScope(BaseModel):
    """Portable generated-hook URL scope configured by the application."""

    model_config = FROZEN

    origin: AnyHttpUrl
    path_prefix: UrlPathPrefix = "/"


class HookSandbox(BaseModel):
    """OS sandbox declaration compiled into native settings and launchers.

    Fetch-scope hostnames join extra_domains as the network allowlist, and
    human-owned files become OS-level write denials, so one declaration
    feeds both the semantic policy and the kernel-enforced boundary.
    """

    model_config = FROZEN

    extra_domains: list[str] = Field(default_factory=list)
    credential_paths: list[str] = Field(default_factory=list)


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
    worker_skill: SkillInvocation
    review_skill: SkillInvocation
    merge_skill: SkillInvocation


class Plugin(BaseModel):
    model_config = FROZEN

    id: str
    name: NativeName
    # Namespaces the plugin in a shared CODEX_HOME: one registration per
    # project, so sibling projects never contend for a single entry.
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

        guidance_size = sum(
            len(part.text) for part in self.guidance.parts if isinstance(part, TextPart)
        )
        if guidance_size > 32_768:
            raise ValueError("always-loaded guidance exceeds 32768 characters")
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
