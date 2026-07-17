"""Validated canonical harness, prompt, artifact, and ownership models.

Placement policy: only models genuinely shared across the declaration graph —
renderers, reconcilers, adapters, and devtools — live here. A type consumed by
essentially one module lives next to that module instead (process launching in
:mod:`lup.harness.process`, tree validation in :mod:`lup.harness.validation`).
"""

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lup.policy.models import PolicyId, UrlPathPrefix
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


class Agent(BaseModel):
    model_config = FROZEN

    id: str
    name: NativeName
    description: str = Field(min_length=1, max_length=1024)
    prompt: PromptDocument
    tools: list[ToolName] = Field(default_factory=list)
    model: str | None = None
    color: str | None = None


class HookUrlScope(BaseModel):
    """Portable generated-hook URL scope configured by the application."""

    model_config = FROZEN

    origin: AnyHttpUrl
    path_prefix: UrlPathPrefix = "/"


class HookSet(BaseModel):
    model_config = FROZEN

    id: str
    policy_ids: list[PolicyId]
    allowed_fetch: list[HookUrlScope] = Field(default_factory=list)
    denied_fetch: list[HookUrlScope] = Field(default_factory=list)
    protected_edit_roots: list[Path] = Field(default_factory=list)


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


class Artifact(BaseModel):
    model_config = FROZEN

    path: Path
    content: str
    semantic_id: str = Field(min_length=1)
    executable: bool = False

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: Path) -> Path:
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

    @field_validator("content")
    @classmethod
    def normalized_content(cls, value: str) -> str:
        if "\r" in value:
            raise ValueError("artifact content must use LF newlines")
        return value if not value or value.endswith("\n") else value + "\n"


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


type OwnershipCategory = Literal[
    "generated",
    "backpropagation_candidate",
    "local_only",
    "sensitive_local_only",
    "unknown_conflict",
    "obsolete_generated",
]


class OwnedArtifact(BaseModel):
    model_config = FROZEN

    path: Path
    category: OwnershipCategory
    sha256: str
    semantic_id: str
    executable: bool = False


class OwnershipManifest(BaseModel):
    model_config = FROZEN

    schema_version: int
    generator_version: str
    source_digest: str
    target_requirements: list[str]
    files: list[OwnedArtifact]


class CurrentArtifact(BaseModel):
    model_config = FROZEN

    path: Path
    content: str
    category: OwnershipCategory
    sha256: str
    executable: bool = False


class CurrentTree(BaseModel):
    model_config = FROZEN

    root: Path
    artifacts: list[CurrentArtifact]


class ProposedWrite(BaseModel):
    model_config = FROZEN

    artifact: Artifact
    previous_sha256: str | None = None
    previous_executable: bool | None = None


class ProposedDelete(BaseModel):
    model_config = FROZEN

    path: Path
    prior_ownership_sha256: str


class ReconciliationConflict(BaseModel):
    model_config = FROZEN

    path: Path
    category: OwnershipCategory
    message: str
    sensitive: bool = False


class ReconciliationProposal(BaseModel):
    model_config = FROZEN

    id: str
    root: Path
    writes: list[ProposedWrite] = Field(default_factory=list)
    deletes: list[ProposedDelete] = Field(default_factory=list)
    conflicts: list[ReconciliationConflict] = Field(default_factory=list)
    base_digest: str


class MaterializationResult(BaseModel):
    model_config = FROZEN

    changed: list[Path]
    removed: list[Path]


class ReconciliationMetadata(BaseModel):
    model_config = FROZEN

    proposal_id: str
    base_digest: str
    source_patch_sha256: str
