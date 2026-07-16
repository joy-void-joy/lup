"""Project-owned canonical Pydantic declarations for the portable Lup harness."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.harness.models import (
    Agent,
    Argument,
    Artifact,
    ArtifactTree,
    CurrentTree,
    Harness,
    HookSet,
    HookUrlScope,
    Plugin,
    PromptDocument,
    PromptPart,
    ResolveSpec,
    Skill,
    SkillInvocation,
    TextPart,
)
from lup.harness.contracts import CurrentTreeReader
from lup_template.devtools.harness.native_overrides import (
    COMMAND_FRONTMATTER_OVERRIDES,
)
from lup_template.devtools.harness.native_catalog import (
    native_catalog_content,
    native_catalog_digest,
)


class SkillSeed(BaseModel):
    """Compact typed source row expanded into a complete semantic skill."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str


class AgentSeed(BaseModel):
    """Compact typed source row expanded into a complete semantic agent."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str


BASELINE_SKILLS = [
    SkillSeed(name="add-command", description="Create a new Lup harness command"),
    SkillSeed(name="brainstorm", description="Explore agent architecture and tools"),
    SkillSeed(name="bump", description="Review changes and bump the agent version"),
    SkillSeed(name="clean-gone", description="Clean merged branches and worktrees"),
    SkillSeed(name="close", description="Review, merge, and close an approved change"),
    SkillSeed(name="commit", description="Create well-scoped atomic commits"),
    SkillSeed(
        name="create-investigator", description="Create a diagnostic investigator skill"
    ),
    SkillSeed(name="debug", description="Trace an error to its root cause"),
    SkillSeed(name="fb-analyze", description="Analyze feedback-loop capability gaps"),
    SkillSeed(name="fb-implement", description="Implement approved feedback changes"),
    SkillSeed(name="fb-investigate", description="Investigate selected session traces"),
    SkillSeed(name="fb-reflect", description="Reflect on feedback process quality"),
    SkillSeed(name="fb-status", description="Report feedback-loop status and targets"),
    SkillSeed(name="feedback-loop", description="Run the complete feedback loop"),
    SkillSeed(
        name="hooks", description="Inspect and modify semantic permission policy"
    ),
    SkillSeed(name="import", description="Import an approved downstream pattern"),
    SkillSeed(name="init", description="Initialize a domain self-improvement loop"),
    SkillSeed(name="install", description="Install Lup into a target repository"),
    SkillSeed(name="merge", description="Semantically merge a branch or conflicts"),
    SkillSeed(name="meta", description="Review and improve the harness structure"),
    SkillSeed(name="modify-command", description="Modify an existing harness command"),
    SkillSeed(
        name="principle", description="Propagate a principle across a repository"
    ),
    SkillSeed(name="rebase", description="Clean feature history and prepare review"),
    SkillSeed(
        name="refactor", description="Rewrite a target around current conventions"
    ),
    SkillSeed(name="refactor-tools", description="Audit agent tools and subagents"),
    SkillSeed(
        name="resolve", description="Resolve inline feedback through isolated work"
    ),
    SkillSeed(name="review", description="Review a session trace for workflow quality"),
    SkillSeed(name="update", description="Review and apply upstream improvements"),
]

SKILLS = [
    *BASELINE_SKILLS,
    SkillSeed(
        name="implementer",
        description="Implement one resolver concern inside its leased worktree",
    ),
    SkillSeed(
        name="resolve-reviewer",
        description="Review one resolver concern against its acceptance criteria",
    ),
]

AGENTS = [
    AgentSeed(
        name="implementer",
        description="Implement production changes against established acceptance tests",
    ),
    AgentSeed(
        name="resolve-editor",
        description="Resolve one concern within its leased isolated worktree",
    ),
    AgentSeed(
        name="trace-explorer",
        description="Investigate trace evidence without changing production files",
    ),
    AgentSeed(
        name="version-explorer",
        description="Inventory version-impact evidence across the repository",
    ),
    AgentSeed(
        name="version-reviewer",
        description="Independently review a proposed version change",
    ),
]

CLAUDE_BASELINE_PATHS = [
    Path(".claude/CLAUDE.md"),
    Path(".claude/PATTERNS.md"),
    Path(".claude/plugins/.claude-plugin/marketplace.json"),
    Path(".claude/plugins/lup/.claude-plugin/plugin.json"),
    *[Path(f".claude/plugins/lup/commands/{seed.name}.md") for seed in BASELINE_SKILLS],
    *[Path(f".claude/plugins/lup/agents/{seed.name}.md") for seed in AGENTS],
    Path(".claude/plugins/lup/hooks/hooks.json"),
    Path(".claude/plugins/lup/scripts/file_suggest.sh"),
    Path(".claude/plugins/lup/TEMPLATE_CLAUDE.md"),
    Path(".claude/settings.json"),
    Path(".claude/workflows/commands/resolve.js"),
]

CLAUDE_RESOLVER_ENTRY = native_catalog_content(
    Path(".claude/workflows/commands/resolve.js")
)


class ClaudeParityCurrentTreeReader(CurrentTreeReader):
    """Accept only the locked baseline's one-time missing-LF normalization."""

    def __init__(
        self,
        inner: CurrentTreeReader,
        desired: ArtifactTree,
        *,
        bootstrap: bool,
    ) -> None:
        self.inner = inner
        self.desired = {artifact.path: artifact for artifact in desired.artifacts}
        self.bootstrap = bootstrap

    def read(self, root: Path) -> CurrentTree:
        current = self.inner.read(root)
        if not self.bootstrap:
            return current
        return current.model_copy(
            update={
                "artifacts": [
                    artifact.model_copy(update={"category": "generated"})
                    if (
                        artifact.path in self.desired
                        and artifact.content + "\n"
                        == self.desired[artifact.path].content
                    )
                    else artifact
                    for artifact in current.artifacts
                ]
            }
        )


def claude_parity_tree(root: Path) -> ArtifactTree:
    """Read the immutable locked baseline from Git, never from generated output."""
    artifacts: list[Artifact] = []  # lup: ignore[empty-collection]
    for path in CLAUDE_BASELINE_PATHS:
        artifacts.append(
            Artifact(
                path=path,
                content=baseline_content(root, path),
                semantic_id=f"claude-baseline:{path.as_posix()}",
                executable=(
                    path.suffix == ".sh" or "/hooks/scripts/" in f"/{path.as_posix()}"
                ),
            )
        )
    return ArtifactTree(
        artifacts=sorted(artifacts, key=lambda artifact: artifact.path.as_posix())
    )


def baseline_content(_root: Path, path: Path) -> str:
    """Read one immutable project-native catalog artifact."""
    content = native_catalog_content(path)
    override = COMMAND_FRONTMATTER_OVERRIDES.get(  # lup: ignore[dict-get]
        path.as_posix()
    )
    if override is None:
        return content
    return override_frontmatter_description(content, override.description)


def override_frontmatter_description(content: str, description: str) -> str:
    """Replace one recognized scalar field while preserving all native bytes."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("native command override requires frontmatter")
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("description:"):
            ending = "\n" if line.endswith("\n") else ""
            lines[index] = f"description: {description}{ending}"
            return "".join(lines)
        if line.strip() == "---":
            break
    raise ValueError("native command override requires a description field")


def markdown_body(content: str) -> str:
    """Extract Markdown after a leading frontmatter block with a line cursor."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[index + 1 :]).lstrip()
    raise ValueError("native Markdown frontmatter is not terminated")


def portable_guidance(content: str) -> str:
    """Select the operational guidance that fits the always-loaded size budget."""
    marker = "## Development Workflow"
    position = content.find(marker)
    if position < 0:
        raise ValueError("locked guidance is missing its workflow section")
    return (
        "# Lup repository guidance\n\n"
        "Lup is a reusable framework and template for autonomous, tool-using "
        "agents. Keep library code provider-neutral and keep provider syntax in "
        "generated adapter artifacts.\n\n" + content[position:]
    )


def portable_prompt(content: str) -> PromptDocument:
    """Import recognized native invocations into typed semantic prompt parts."""
    parts: list[PromptPart] = []  # lup: ignore[empty-collection]
    text_start = 0
    position = 0
    while position < len(content):
        if content.startswith("$ARGUMENTS", position):
            if text_start < position:
                parts.append(TextPart(text=content[text_start:position]))
            parts.append(
                TextPart(text="the arguments supplied with this skill invocation")
            )
            position += len("$ARGUMENTS")
            text_start = position
            continue
        if not content.startswith("/lup:", position):
            position += 1
            continue
        if text_start < position:
            parts.append(TextPart(text=content[text_start:position]))
        name_start = position + len("/lup:")
        name_end = name_start
        while name_end < len(content) and (
            content[name_end].isalnum() or content[name_end] == "-"
        ):
            name_end += 1
        name = content[name_start:name_end]
        if name and any(seed.name == name for seed in SKILLS):
            parts.append(SkillInvocation(plugin="lup", skill=name))
        else:
            parts.append(TextPart(text="the corresponding Lup skill"))
            if name_end == name_start:
                name_end += 1
        position = name_end
        text_start = position
    if text_start < len(content):
        parts.append(TextPart(text=content[text_start:]))
    return PromptDocument(parts=parts or [TextPart(text=content)])


def skill(seed: SkillSeed, root: Path) -> Skill:
    """Expand one canonical row without introducing native invocation spelling."""
    if seed.name == "resolve":
        instruction = (
            "Enter the shared Python resolver through the project devtools entry, "
            "supplying this adapter's session, invocation, question, process, and "
            "state-root composition. Do not implement scheduling, leases, review "
            "rounds, integration, or cleanup in this skill."
        )
    elif seed.name == "implementer":
        instruction = (
            "Implement exactly the supplied resolver assignment inside its leased "
            "worktree. Do not create branches or commits. Report every changed path, "
            "any work beyond the declared starting points, verification performed, "
            "and material questions through the resolver's typed report."
        )
    elif seed.name == "resolve-reviewer":
        instruction = (
            "Independently review the supplied concern commit against every persisted "
            "acceptance criterion. Inspect the complete diff, reject omissions and "
            "scope leaks, and return the typed review report without editing."
        )
    else:
        instruction = markdown_body(
            baseline_content(root, Path(f".claude/plugins/lup/commands/{seed.name}.md"))
        )
    native_path = f".claude/plugins/lup/commands/{seed.name}.md"
    override = COMMAND_FRONTMATTER_OVERRIDES.get(  # lup: ignore[dict-get]
        native_path
    )
    return Skill(
        id=f"skill.{seed.name}",
        name=seed.name,
        description=override.description if override is not None else seed.description,
        arguments=(
            [
                Argument(
                    name="arguments",
                    description="Optional arguments supplied with the skill invocation",
                )
            ]
            if "$ARGUMENTS" in instruction
            else []
        ),
        prompt=portable_prompt(instruction),
    )


def agent(seed: AgentSeed, root: Path) -> Agent:
    """Expand one portable project agent without provider tool names."""
    return Agent(
        id=f"agent.{seed.name}",
        name=seed.name,
        description=seed.description,
        prompt=portable_prompt(
            markdown_body(
                baseline_content(
                    root, Path(f".claude/plugins/lup/agents/{seed.name}.md")
                )
            )
        ),
    )


def portable_harness(version: str = "0.2.0", root: Path | None = None) -> Harness:
    """Build the canonical declaration graph consumed by every adapter."""
    source_root = root or Path.cwd()
    plugin = Plugin(
        id="plugin.lup",
        name="lup",
        version=version,
        description=(
            "Self-improvement harness with feedback, review, and safe resolution flows"
        ),
        skills=[skill(seed, source_root) for seed in SKILLS],
        agents=[agent(seed, source_root) for seed in AGENTS],
        hooks=HookSet(
            id="hooks.lup-policy",
            policy_ids=["fetch", "shell", "edit", "unknown-tool"],
            allowed_fetch=[
                HookUrlScope.model_validate({"origin": "https://docs.claude.com"}),
                HookUrlScope.model_validate({"origin": "http://docs.claude.com"}),
                HookUrlScope.model_validate({"origin": "https://ai.pydantic.dev"}),
                HookUrlScope.model_validate({"origin": "http://ai.pydantic.dev"}),
            ],
            protected_edit_roots=[
                Path(".claude"),
                Path("tmp"),
                Path("pyproject.toml"),
            ],
        ),
    )
    return Harness(
        generator_version=version,
        source_evidence={"claude-native-catalog": native_catalog_digest()},
        plugins=[plugin],
        guidance=portable_prompt(
            portable_guidance(baseline_content(source_root, Path(".claude/CLAUDE.md")))
        ),
        resolver=ResolveSpec(
            id="resolver.lup",
            worker_skill=SkillInvocation(plugin="lup", skill="implementer"),
            review_skill=SkillInvocation(plugin="lup", skill="resolve-reviewer"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
    )
