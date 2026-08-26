"""Genuinely shared harness vocabulary: declarations and rendered artifacts.

The canonical declaration graph (``Harness`` down to prompt parts) that the
application declares and the adapter renderers, devtools generation flows, and
resolver consume, plus the rendered ``Artifact``/``ArtifactTree`` and probe
evidence shared by every pipeline stage. A model owned by one concern lives
beside its managing module instead (see the package docstring).
"""

import re  # lup: ignore[import-re] — prose has no parser; its shape is the rule
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    Discriminator,
    Field,
    StringConstraints,
    model_validator,
)

from lup.codescan.common import AntiPattern, RuleSelection
from lup.devtools.launcher import DEFAULT_ENVIRONMENT
from lup.harness.banner import ArtifactBanner, GeneratedBanner
from lup.harness.image import Image
from lup.harness.requirements import Manifest
from lup.markdown import CodeCell, PlainCell, TableCell, escaped
from lup.tools.mcp import ToolDeclaration
from lup.policy.kernel.rows import AcceptanceGuardRow, PathRoleName
from lup.policy.models import PolicyId, UrlPathPrefix
from lup.policy.refused_tools import RefusedTool
from lup.policy.edit_rules import EditRule
from lup.policy.shell_rules import RunnerTargetRule, ShellCommandRule
from lup.policy.vocabulary import default_vocabulary
from lup.selection import Selection
from lup.types import JsonValue, ToolGrant, ToolName

if TYPE_CHECKING:
    from lup.harness.contracts import NativeSpellings, PromptRenderer

type NativeName = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")
]
"""A declaration name portable across adapters: lowercase alphanumerics with
interior hyphens or underscores."""

type QualifiedAgentName = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]*:[a-z0-9][a-z0-9_-]*$")
]
"""A delegation target, ``<plugin>:<agent>``, as a runtime addresses one."""

# lup: ignore[constant-declaration] — the characters the runtimes actually write,
# each of which proves its own sigil is one of these
INVOCATION_SIGILS = "/$"
"""Every character a runtime writes in front of a skill invocation.

Which words a runtime spells is the adapter's to know, but that an invocation
is a sigil followed by a qualified name is a shape prose can be held to on its
own — no plugin registry required. Each runtime proves its own sigil is one of
these, so the syntax the declaration layer refuses cannot drift from the syntax
the adapters render.
"""

RENDERED_INVOCATION = re.compile(  # lup: ignore[re-call] — a shape, not a parse
    f"[{INVOCATION_SIGILS}]"
    r"[a-z0-9][a-z0-9_-]*:(?:[a-z0-9][a-z0-9_-]*|\*|<[a-z][a-z0-9-]*>)"
)
"""What ``SkillInvocation`` and ``SkillPattern`` render to, in either sigil."""


def portable_prose(value: str) -> str:
    """Refuse text spelling an invocation only one runtime would understand."""
    spelled = RENDERED_INVOCATION.search(value)
    if spelled is None:
        return value
    raise ValueError(
        f"portable prose spells the invocation {spelled.group()!r}, which the "
        "other runtime's reader cannot use: issue one with SkillInvocation, or "
        "teach its shape with SkillPattern"
    )


type PortableText = Annotated[str, AfterValidator(portable_prose)]
"""Free text proven to spell no runtime's invocation syntax.

Every declaration field a native tree renders as prose is one of these, so the
invariant is answered where an author writes the words rather than by a scan
over the harness they eventually compose into."""


class SemanticPart(BaseModel, ABC, frozen=True):
    """One element of a prompt document, answering every question about itself.

    Whatever the rest of the harness needs to know about a part is declared
    here and answered — or declined — by the part, so a new kind of part is one
    class rather than an edit to every walk that would have to notice it. The
    declining answers are what make omission safe: a caller asking
    ``text_payload`` reaches every kind that carries prose, including kinds
    written long after the caller was.

    Pydantic's metaclass is an ``ABCMeta``, so ``spell`` binds like any
    abstract method: a subtype that does not answer it cannot be constructed.
    """

    @abstractmethod
    def spell(self, renderer: "PromptRenderer") -> str:
        """Render this part in the vocabulary of the runtime that reads it."""

    @property
    def text_payload(self) -> str | None:
        """Portable prose this part carries verbatim, if it carries any.

        Everything that weighs or reads what a declaration literally says asks
        this instead of naming the kinds of part that hold text.
        """
        return None

    @property
    def invocation(self) -> "SkillInvocation | None":
        """The skill invocation this part issues, if it issues one."""
        return None

    @property
    def named_plugin(self) -> NativeName | None:
        """The plugin this part names, which the harness must have declared."""
        return None

    @property
    def named_agent(self) -> QualifiedAgentName | None:
        """The agent this part delegates to, which must also be declared."""
        return None

    @property
    def references_arguments(self) -> bool:
        """Whether this part reaches the arguments its invocation supplied."""
        return False

    @property
    def shell_command(self) -> str | None:
        """The shell command this part tells its reader to run, if it names one.

        A part that names a command is asking the agent to run it, so the
        skill carrying it has to have granted the shell that takes. Asking
        the part is what lets that be checked where the two are declared,
        rather than discovered by an agent whose own instructions are denied.
        """
        return None


class TextPart(SemanticPart, frozen=True):
    type: Literal["text"] = "text"
    text: PortableText

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.text

    @property
    def text_payload(self) -> str:
        return self.text


class SpellingExample(SemanticPart, frozen=True):
    """Prose whose subject is a runtime's own spelling, quoted verbatim.

    Ordinary prose refuses a rendered invocation because a reader on the other
    runtime cannot use one. A document *comparing* the runtimes has to quote
    both, so the exemption is declared here rather than left as a rule that
    quietly does not fire. It is deliberately narrow: the same words reach
    every tree, so this can only ever exhibit a spelling — never issue one,
    which is what :class:`SkillInvocation` is for.
    """

    type: Literal["spelling_example"] = "spelling_example"
    text: str

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.text

    @property
    def text_payload(self) -> str:
        return self.text


class MarkdownTable(SemanticPart, frozen=True):
    """A table derived from declarations, laid out and escaped as it renders.

    Rows arrive as the values they stand for rather than as finished Markdown,
    so the escaping that keeps a pipe or a newline from breaking the row it
    lands in happens here — a caller composes a table into a document the way
    it composes any other part, and has no way to splice one in wrong. Every
    runtime reads the same Markdown, so this spells itself.

    Headers and cells hold data rather than authored prose — a rule's matching
    shape, a path a document already renders to — so they are not held to the
    portable-prose invariant a :class:`TextPart` answers for. What the table
    renders still reaches ``text_payload``, so a native spelling that arrived
    through a cell is caught where the assembled document is checked.
    """

    type: Literal["markdown_table"] = "markdown_table"
    headers: list[str]
    rows: list[list[TableCell]]

    @model_validator(mode="after")
    def rows_match_the_header(self) -> "MarkdownTable":
        ragged = [len(row) for row in self.rows if len(row) != len(self.headers)]
        if ragged:
            raise ValueError(
                f"table rows hold {ragged} cells under {len(self.headers)} headers"
            )
        return self

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.text_payload

    @property
    def text_payload(self) -> str:
        """The table as Markdown, one line per row, newline-terminated."""
        lines = [
            [escaped(header) for header in self.headers],
            ["---"] * len(self.headers),
            *[[cell.render() for cell in row] for row in self.rows],
        ]
        return "".join(f"| {' | '.join(line)} |\n" for line in lines)


class ToolRoster(SemanticPart, frozen=True):
    """Agent-facing tool metadata rendered from registration declarations."""

    type: Literal["tool_roster"] = "tool_roster"
    tools: list[ToolDeclaration]

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.text_payload

    @property
    def text_payload(self) -> str:
        return MarkdownTable(
            headers=["Tool", "Contract"],
            rows=[
                [CodeCell(text=tool.name), PlainCell(text=tool.description)]
                for tool in self.tools
            ],
        ).text_payload


class InvocationArgument(BaseModel, frozen=True):
    name: NativeName
    value: JsonValue


class SkillInvocation(SemanticPart, frozen=True):
    type: Literal["skill_invocation"] = "skill_invocation"
    plugin: NativeName
    skill: NativeName
    arguments: list[InvocationArgument] = []

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.render(self)

    @property
    def invocation(self) -> "SkillInvocation":
        return self

    @property
    def named_plugin(self) -> NativeName:
        return self.plugin


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


class LocatedPart(SemanticPart, ABC, frozen=True):
    """One path a prompt names, spelled by whichever adapter renders it.

    Scope is the same question for every location — whether the reader's own
    tree answers it or every tree must be taught at once — so the renderer asks
    it once and each kind only says how it spells itself in one vocabulary.
    """

    scope: PathScope = "this_tree"

    @abstractmethod
    def spell_in(self, runtime: "NativeSpellings") -> str:
        """Spell this location in one runtime's own vocabulary."""

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.location(self)


class NativePath(LocatedPart, frozen=True):
    """One harness-tree location, spelled by whichever adapter renders it."""

    type: Literal["native_path"] = "native_path"
    location: TreeLocation

    def spell_in(self, runtime: "NativeSpellings") -> str:
        return runtime.tree(self.location)


class PluginPath(LocatedPart, frozen=True):
    """One plugin-owned location, spelled by whichever adapter renders it.

    ``member`` selects a leaf whose whole path differs per runtime — a skill is
    one file under one runtime and a directory under another — while omitting
    it names the containing directory.
    """

    type: Literal["plugin_path"] = "plugin_path"
    plugin: NativeName
    location: PluginLocation
    member: PathMember | None = None

    def spell_in(self, runtime: "NativeSpellings") -> str:
        return runtime.plugin(self.plugin, self.location, self.member)

    @property
    def named_plugin(self) -> NativeName:
        return self.plugin


class SkillPattern(SemanticPart, frozen=True):
    """An invocation shape standing in for a skill the reader will name.

    ``SkillInvocation`` resolves against the declaration registry, so it cannot
    express the placeholder or wildcard a prompt uses when it teaches the shape
    of an invocation rather than issuing one.
    """

    type: Literal["skill_pattern"] = "skill_pattern"
    plugin: NativeName
    placeholder: PathMember

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.invocation_pattern(self.plugin, self.placeholder)

    @property
    def named_plugin(self) -> NativeName:
        return self.plugin


class RuntimeDocs(SemanticPart, frozen=True):
    """The reader's own runtime documentation, wherever that runtime is."""

    type: Literal["runtime_docs"] = "runtime_docs"

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.runtime_docs()


class AskUser(SemanticPart, frozen=True):
    type: Literal["ask_user"] = "ask_user"
    question: PortableText

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.ask_user(self.question)


class Delegate(SemanticPart, frozen=True):
    type: Literal["delegate"] = "delegate"
    subagent_type: QualifiedAgentName
    prompt: PortableText

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.delegate(self.subagent_type, self.prompt)

    @property
    def named_agent(self) -> QualifiedAgentName:
        return self.subagent_type


class RequestApproval(SemanticPart, frozen=True):
    type: Literal["request_approval"] = "request_approval"
    action: PortableText
    reason: PortableText

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.request_approval(self.action, self.reason)


class RelocateSession(SemanticPart, frozen=True):
    """Continue work inside an already-created worktree.

    Runtimes differ on whether a running session can move: one relocates in
    place, another can only be replaced by a session started there. Naming
    the intent lets each adapter spell the move it actually supports -- and
    lets one that supports both spell the cheaper of them, which is why every
    adapter currently answers with a launch. Relocation is not free where it
    exists: it arms a runtime's own worktree isolation, whose refusals are
    about command shape rather than about anything this policy judges.
    """

    type: Literal["relocate_session"] = "relocate_session"
    path: PortableText
    """Where the reader finds the path, e.g. "the path step 1 prints"."""

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.relocate_session(self.path)


class WatchOutput(SemanticPart, frozen=True):
    """Wait on a command that reports progress before it exits.

    Runtimes differ in what waiting *is*: one pushes each line to the agent,
    another hands it a live session to read. Prose that named the idea
    without naming the mechanism left a reader to guess, and the guess is an
    ordinary command with a long timeout — which reports once, at the end.
    """

    type: Literal["watch_output"] = "watch_output"
    command: PortableText
    """The command to watch, as the reader will run it."""

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.watch_output(self.command)

    @property
    def shell_command(self) -> str:
        return self.command


class ResolverEntry(SemanticPart, frozen=True):
    type: Literal["resolver_entry"] = "resolver_entry"

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.resolver_entry()


class ArgumentsRef(SemanticPart, frozen=True):
    type: Literal["arguments_ref"] = "arguments_ref"

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.arguments_ref()

    @property
    def references_arguments(self) -> bool:
        return True


type PromptPart = Annotated[
    TextPart
    | SpellingExample
    | MarkdownTable
    | ToolRoster
    | SkillInvocation
    | NativePath
    | PluginPath
    | SkillPattern
    | RuntimeDocs
    | AskUser
    | Delegate
    | RequestApproval
    | RelocateSession
    | WatchOutput
    | ResolverEntry
    | ArgumentsRef,
    Discriminator("type"),
]


class PromptDocument(BaseModel, frozen=True):
    parts: list[PromptPart]
    source: str | None = None
    """The module declaring this document, and where a reader edits it.

    Every document reaching a file of its own carries one — a skill's or an
    agent's prompt included, whose artifact renders the frontmatter and the
    prose out of the single module declaring both. What names no source is a
    document composed into another rather than compiled: a shared section
    several skills fold in has no file of its own to point anybody at."""

    def declared_source(self) -> str:
        """The declaring module, required because this document becomes a file."""
        if self.source is None:
            raise ValueError("a document rendered to its own artifact needs a source")
        return self.source

    def prose(self) -> list[str]:
        """Every literal prose payload this document carries, in reading order."""
        return [text for part in self.parts if (text := part.text_payload) is not None]

    def text_size(self) -> int:
        """Lower bound on what this document costs a session, in UTF-8 bytes.

        Every part renders to something, so the rendered document is never
        smaller. This is the share a neutral module can measure without
        reaching for an adapter to spell the rest.
        """
        return sum(document_byte_size(text) for text in self.prose())


class Document(BaseModel, frozen=True):
    """One generated repository document and where it renders.

    Separate from the roster that lists them: which documents a project
    publishes is its own decision, but that each is a prompt document with a
    path, an identity, and a declaring module is what makes the roster
    renderable by machinery no project writes.
    """

    path: Path
    semantic_id: str
    source: str
    document: PromptDocument


GUIDANCE_BYTE_BUDGET = 32_768
"""Default ceiling, in UTF-8 bytes, on the always-loaded guidance document.

Codex stops adding project documentation once the combined size reaches
``project_doc_max_bytes``, whose own default is 32 KiB — so exceeding this is
not an error a reader ever sees, it is *silent truncation*. The unit is bytes
for the same reason: that is what the vendor limits, and UTF-8 punctuation
makes a document's byte count exceed its character count, so a character-based
check runs looser than the real cap and passes documents that would be cut.

Claude has no equivalent setting — its guidance file is loaded in full
whatever its length. Lup applies one number to both trees anyway, so the two
runtimes read the same document rather than one reading a longer one.

This is a default rather than a constant: the number mirrors a real vendor
default, but which ceiling a given project wants is its own call. Pass
``budget`` to the checks below to state a different one. See § A Constant
Should Probably Be An Overridable Default in ``docs/patterns.md``.

What a session pays for is the rendered document, so that is what the adapters
check as they compile it. A typed part costs whatever its adapter spells it as,
however little literal text the declaration holds. Reference material that a
skill or a denial message surfaces at the right moment belongs in a generated
document under ``docs/`` instead, reached by a file-path pointer."""

TEMPLATE_GUIDANCE_HEADROOM = 12_288
"""Bytes a scaffold holds back, out of the budget above, for its adopter.

The ceiling above is what a *runtime* will load. This is what a **template**
may spend of it, and the difference is the whole point: a repository that is
still the scaffold is writing guidance every domain built on it inherits, and
that domain then has to describe its own architecture, conventions and
workflow inside whatever is left. A scaffold that fills the runtime's ceiling
has not passed its budget on, it has spent it — and the adopter discovers this
by writing three paragraphs about its own project and being refused.

12 KiB because that is what this repository's own architecture, conventions
and tooling sections cost together: enough for a domain to say the equivalent
about itself, rather than a round number that sounds generous.

Only ``dev check`` weighs this, and only while ``[tool.lup] template = true``.
It must never reach ``budget`` on the checks above: those decide what a real
runtime is told to load, and a scaffold's self-restraint is not a fact about
any runtime's ceiling."""


def document_byte_size(text: str) -> int:
    """What a rendered document costs the runtime that loads it, in UTF-8 bytes."""
    return len(text.encode("utf-8"))


class Argument(BaseModel, frozen=True):
    name: NativeName
    description: PortableText = Field(min_length=1, max_length=1024)
    required: bool = False


class BashGrant(BaseModel, frozen=True):
    """What one declared ``Bash`` grant lets its holder run.

    A grant reaches a declaration as a constrained string, because that is the
    vocabulary the runtimes read it back in. The shape inside it still has to
    be understood to answer whether a command is covered, and reading it once
    here is what keeps each caller from re-deriving it with its own slicing.
    """

    prefixes: list[str] = []
    """Command prefixes admitted, empty when the grant admits every command."""

    def admits(self, command: str) -> bool:
        """Whether this grant lets its holder run ``command``."""
        if not self.prefixes:
            return True
        return any(command.startswith(prefix) for prefix in self.prefixes)

    @classmethod
    def read(cls, grant: ToolGrant) -> "BashGrant | None":
        """This grant as Bash coverage, or ``None`` when it grants another tool."""
        if grant == "Bash":
            return cls()
        if not grant.startswith("Bash(") or not grant.endswith(")"):
            return None
        scoped = grant.removeprefix("Bash(").removesuffix(")")
        # lup: ignore[string-split] — the parenthesized specifier is a runtime's
        # own grant syntax, which no stdlib parser reads
        specifiers = scoped.split(",")
        return cls(prefixes=[scope.strip().removesuffix(":*") for scope in specifiers])


class Skill(BaseModel, frozen=True):
    id: str
    name: NativeName
    description: PortableText = Field(min_length=1, max_length=1024)
    arguments: list[Argument] = []
    tools: list[ToolGrant] = []
    argument_hint: PortableText | None = None
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
            part.references_arguments for part in self.prompt.parts
        )
        if bool(self.arguments) != references_arguments:
            raise ValueError(
                f"skill {self.id!r} argument declarations and ArgumentsRef disagree"
            )
        return self

    @model_validator(mode="after")
    def commands_it_names_are_commands_it_may_run(self) -> "Skill":
        """A command this skill tells its reader to run must be one it granted.

        The two are declared side by side and nothing made them agree, so a
        skill could instruct a step its own `tools` list forbids — and did:
        one told the agent to watch a `dev check` while granting no shell at
        all. That failure surfaces as a denial mid-run, to an agent following
        instructions correctly, which is the worst place to learn it. An empty
        grant list restricts nothing and is left alone.
        """
        if not self.tools:
            return self
        granted = [
            read for grant in self.tools if (read := BashGrant.read(grant)) is not None
        ]
        for part in self.prompt.parts:
            command = part.shell_command
            if command is None:
                continue
            if not any(grant.admits(command) for grant in granted):
                raise ValueError(
                    f"skill {self.id!r} names the command {command!r} but grants "
                    "no Bash that runs it: add the grant, or stop naming it"
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


class Agent(BaseModel, frozen=True):
    id: str
    name: NativeName
    description: PortableText = Field(min_length=1, max_length=1024)
    prompt: PromptDocument
    tools: list[ToolName] = []
    model: ModelTier | None = None
    color: AgentColor | None = None


class ContentSelection(BaseModel, frozen=True):
    """Which of the skills and agents a library ships a project's plugin carries.

    Subtractive for the reason ``RuleSelection`` and ``SubAppSelection`` are: a
    project declining two should name those two, because a restated roster is
    re-copied on every addition and the copy that fell behind looks like a
    decision. Skills and agents share one selection because they share one
    namespace of stable ids, and a project retiring a skill that a retired
    agent existed to serve should not have to say so in two places.
    """

    retired: list[str] = []
    """Declaration ids this project's plugin does not ship."""

    def keeps(self, declaration_id: str) -> bool:
        """Whether a declaration is live here, for a roster composing itself."""
        return declaration_id not in self.retired


class ContentRoster(BaseModel, frozen=True):
    """The skills and agents one plugin ships, as the pair every reader wants.

    A pair rather than two lists because every consumer takes both — the
    compiled plugin, the roster documents, the drift check — and a project
    composing them separately is two places for the same decision to be made
    differently.
    """

    skills: list[Skill] = []
    agents: list[Agent] = []

    def selected(self, selection: ContentSelection) -> "ContentRoster":
        """This roster with what a project retired taken out of both lists.

        Narrowing the roster rather than filtering at each surface is what
        keeps a retired declaration from reaching any of them: it is not
        compiled, not rendered into the documents that say what the plugin
        ships, and not named by prose describing a skill nobody can invoke.
        """
        return ContentRoster(
            skills=[skill for skill in self.skills if selection.keeps(skill.id)],
            agents=[agent for agent in self.agents if selection.keeps(agent.id)],
        )

    def extended(self, skills: list[Skill], agents: list[Agent]) -> "ContentRoster":
        """This roster followed by what only one project has."""
        return ContentRoster(
            skills=[*self.skills, *skills], agents=[*self.agents, *agents]
        )


class McpWord(BaseModel, ABC, frozen=True):
    """One word of the command line that starts an MCP server.

    A server the harness offers has to be reachable from wherever the runtime
    spawns it, and each runtime hands a spawned process a different way of
    naming the repository it belongs to. Declaring the words as parts rather
    than as a string keeps that difference in the adapters, the way a prompt
    keeps every other native spelling there.
    """

    @abstractmethod
    def spell_in(self, runtime: "NativeSpellings") -> str:
        """Spell this word in one runtime's own vocabulary."""


class LiteralWord(McpWord, frozen=True):
    """One word every runtime spells identically."""

    type: Literal["literal"] = "literal"
    text: str = Field(min_length=1)

    def spell_in(self, runtime: "NativeSpellings") -> str:
        return self.text


class ProjectRootWord(McpWord, frozen=True):
    """The repository root, as the runtime spawning the server can name it."""

    type: Literal["project_root"] = "project_root"

    def spell_in(self, runtime: "NativeSpellings") -> str:
        return runtime.project_root()


type McpCommandWord = Annotated[LiteralWord | ProjectRootWord, Discriminator("type")]


class McpServer(BaseModel, frozen=True):
    """One tool server a native tree offers the agent that reads it.

    The application owns which tools exist and how they are grouped; this
    declares only how a runtime starts one group and what to call it, so the
    same registry reaches an in-process session and a native harness session
    without either learning the other's assembly.
    """

    id: str
    name: NativeName
    description: PortableText = Field(min_length=1, max_length=1024)
    command: str = Field(min_length=1)
    arguments: list[McpCommandWord] = []

    env_vars: list[str] = []
    """Environment variable names that must reach this server from the launch.

    Names, never values: this is compiled into a committed tree, and a value
    belongs to one machine and one run. Which runtimes have to be told is a
    rendering decision, and they differ. One spawns a server as its own child
    and hands it the whole environment, so naming a variable changes nothing
    there. The other hands a spawned server a fixed base environment — a
    shell's worth of HOME and PATH and no more — and forwards exactly the
    names it was given, so a server needing a session relay, a credential or
    a configuration home reaches none of them unless they are named here.
    """

    startup_timeout_seconds: float | None = None
    """How long this server gets to come up before a runtime abandons it.

    Declared per server because the answer belongs to the server and not to
    the machine: a group that resolves its package before importing anything
    is slow on a cold checkout and instant on a warm one, while a runtime's
    own default is chosen for a server already installed. Unset leaves that
    default in force, which is right for a server whose start costs nothing.

    Only a runtime that spawns under a deadline reads it; one that waits
    renders nothing. What makes the deadline worth declaring is the shape of
    missing it — the server is dropped and the session keeps the rest, so it
    arrives as a group that is simply absent rather than as an error naming a
    limit.
    """

    def command_line(self, runtime: "NativeSpellings") -> list[str]:
        """Spell every argument for the runtime that will spawn this server."""
        return [argument.spell_in(runtime) for argument in self.arguments]


class HookUrlScope(BaseModel, frozen=True):
    """Portable generated-hook URL scope configured by the application."""

    origin: AnyHttpUrl
    path_prefix: UrlPathPrefix = "/"
    reason: str = Field(
        default="",
        description=(
            "Why this origin is reachable, carried into the decision the "
            "kernel returns — the field the policy surface already had and "
            "this declaration could not supply"
        ),
    )
    include_subdomains: bool = Field(
        default=False,
        description=(
            "Extend the scope to every host beneath the origin, rendered as a "
            "*.host wildcard in the OS sandbox network allowlist"
        ),
    )
    any_port: bool = Field(
        default=False,
        description=(
            "Extend the scope to every port on the origin, for a host whose "
            "port the caller chooses rather than the service"
        ),
    )


class HookPathRole(BaseModel, frozen=True):
    """One repository root and the purpose the tree beneath it serves.

    Production is the default and needs no declaration: it is what the
    conventions are written about. A ``test`` root is judged by whether it
    exercises production rather than by production's own shape, and a
    ``scratch`` root holds files that are disposable by construction, so the
    verbs that ask before destroying something have nothing to protect there.

    ``root`` is a pattern, which says how far the declaration reaches. A bare
    root is anchored at the repository top, which is what a laid-out tree
    means; a directory that is what it is wherever it sits — a scratch
    directory beside whichever package opened it — is named ``**/<name>``.
    """

    root: Path
    role: PathRoleName


class AcceptanceGuard(BaseModel, frozen=True):
    """A project's decision to hold the tests its work is measured against.

    Declaring one turns every ``test``-role root into a gate: an ordinary
    session is asked before it edits a test, and a session declared
    autonomous — the resolver worker, the implementer — is refused outright.
    Undeclared, tests are judged by the ordinary lattice, which is what a
    project that does not work against fixed acceptance tests wants.

    Both reasons default to wording that says what to do instead, because a
    refusal an agent cannot act on becomes a retry. A project with its own
    workflow to name replaces them; a project without one should not have to
    invent them to turn the gate on.
    """

    ask_reason: str = (
        "editing a test changes what the implementation is measured against —"
        " approve this only if the test encodes the wrong behaviour, and fix"
        " the implementation otherwise"
    )
    autonomous_reason: str = (
        "this session implements against these tests, so they are its"
        " specification rather than its material — report what the test"
        " demands and why it cannot be met, and leave the change to whoever"
        " can weigh it"
    )

    def erased(self) -> AcceptanceGuardRow:
        """This guard as the kernel reads it, primitive and dependency-free.

        The single projection to the runtime shape, so the live policy and
        the hermetic runtime compiled into each plugin cannot come to hold
        different wording of the same refusal.
        """
        return AcceptanceGuardRow(
            ask_reason=self.ask_reason, autonomous_reason=self.autonomous_reason
        )


class HookSandbox(BaseModel, frozen=True):
    """OS sandbox declaration compiled into native settings and launchers.

    Fetch-scope hostnames join extra_domains as the network allowlist,
    human-owned files become OS-level write denials, and writable_paths become
    the grants that let a sandboxed toolchain reach its caches, so one
    declaration feeds both the semantic policy and the kernel-enforced
    boundary. excluded_commands travels the same pair in the other direction:
    it widens the settings and narrows what the policy will hand to the OS,
    because work the boundary never confined cannot be deferred to it.

    That makes allowed_fetch the home for any origin an agent should be able
    to read: declaring it there grants both the fetch and the egress. Reserve
    extra_domains for hosts that need egress but are not readable sources —
    an authenticated API a library calls, never a document the agent opens.
    Listing a readable origin here instead is what lets the two boundaries
    disagree, with the OS admitting a host the fetch policy still asks about.
    """

    extra_domains: list[str] = []
    credential_paths: list[str] = []
    excluded_commands: list[str] = Field(
        default=[],
        description=(
            "Commands the OS boundary does not confine at all. This is the "
            "only per-command lever a sandbox offers: it takes the command "
            "out of isolation rather than lifting one rule, so it is what a "
            "requirement no path or domain can express has to be stated as — "
            "a daemon socket the isolation blocks outright, or egress over a "
            "protocol an HTTP proxy cannot carry. Each entry is a command "
            "prefix written with a trailing ``*``, matching that word run "
            "alone or followed by arguments."
        ),
    )
    writable_paths: list[str] = Field(
        default=[],
        description=(
            "Paths outside the workspace a sandboxed toolchain must write. "
            "A tool that cannot reach its cache fails only when the cache is "
            "cold, so an undeclared path reads as an intermittent fault rather "
            "than a boundary; declaring it here states the requirement where "
            "the rest of the boundary is stated."
        ),
    )


class HookSet(BaseModel, frozen=True):
    id: str
    policy_ids: list[PolicyId]
    allowed_fetch: list[HookUrlScope] = []
    denied_fetch: list[HookUrlScope] = []
    protected_edit_roots: list[Path] = []
    path_roles: list[HookPathRole] = Field(
        default=[],
        description=(
            "What each repository root is for. The lattice judges an action by "
            "what it does; a role supplies what the thing acted upon is for, "
            "which is what decides how much of the lattice applies"
        ),
    )
    human_owned_files: list[Path] = Field(
        default=[],
        description=(
            "Files whose content the human author owns; every edit is surfaced "
            "as Ask so agents propose changes instead of applying them"
        ),
    )
    acceptance_guard: AcceptanceGuard | None = Field(
        default=None,
        description=(
            "Whether every test-role root is held still: an ordinary session "
            "is asked before editing a test and an autonomous one is refused. "
            "None declares no guard, which judges tests by the ordinary "
            "lattice — right for a project that does not implement against "
            "fixed acceptance tests, and wrong for one that runs the resolver"
        ),
    )
    shell_rules: Selection[ShellCommandRule] = Field(
        default=Selection[ShellCommandRule](),
        description=(
            "How this project differs from the shell vocabulary the library "
            "ships — a downstream toolchain to add, a command it judges "
            "differently, one it drops. An empty selection is "
            "`default_vocabulary()` unchanged, so a project declares `lake` "
            "without restating `ls`, `grep` and `git` around it"
        ),
    )
    edit_rules: Selection[EditRule] = Field(
        default=Selection[EditRule](),
        description=(
            "How this project moves the edit gates the kernel decides on its "
            "own — which whole-file writes it reviews at the hook, how much "
            "counts as a small change, and for which files. An empty "
            "selection decides exactly what the kernel decides unaided, so a "
            "project states only its differences and every gate it says "
            "nothing about keeps the library's answer"
        ),
    )
    diagnostics_command: list[str] = Field(
        default=[],
        description=(
            "How to type-check one edited file, run from the checkout that "
            "holds it with the file appended. Empty declares no checker, and "
            "reports nothing rather than guessing at one"
        ),
    )
    resolution_command: list[str] = Field(
        default=[],
        description=(
            "How to resolve one edited file's receivers, run from the checkout "
            "that holds it with the proposed text on stdin and the file named "
            "by --path. Empty declares no resolver, and a rule whose verdict "
            "turns on a declaration then asks rather than refusing"
        ),
    )
    refused_tools: list[RefusedTool] = Field(
        default=[],
        description=(
            "Native calls this project has decided against outright, each "
            "carrying the surface to reach for instead. Whether a tool is "
            "against the point of a project is that project's judgement, so "
            "an empty list — the library's own answer — refuses nothing"
        ),
    )
    runner_targets: list[RunnerTargetRule] = Field(
        default=[],
        description=(
            "Which bare targets `uv run <target>` may reach without a question, "
            "and where each has to run. A project's own toolchain, so the "
            "library holds no opinion: an "
            "empty list judges every runner invocation by the ordinary shell "
            "vocabulary instead"
        ),
    )
    rules: RuleSelection = Field(
        default=RuleSelection(),
        description=(
            "Which of the scan rules the library ships this project holds "
            "itself to, named subtractively so a project states the few it "
            "retired rather than restating the many it keeps. One selection "
            "reaches the edit hook compiled from this set, the repository "
            "sweep, and the generated rule reference, so none of the three "
            "can enforce a rule the others stopped enforcing"
        ),
    )
    anti_patterns: list[AntiPattern] = Field(
        default=[],
        description=(
            "Code shapes only this project refuses, added to the tables the "
            "library ships. Declare one here the way shell_rules declares a "
            "downstream toolchain: the library settles what every project "
            "wants and holds no opinion on the rest, so a repository that "
            "named a defect of its own enforces it instead of waiting to be "
            "adopted. Additive, because `rules` already says what a project "
            "drops — between them a project states only where it differs"
        ),
    )
    recoverable_target_limit: int = Field(
        default=20,
        ge=0,
        description=(
            "How many committed, unmodified files one command may destroy "
            "without asking. Git restores each of them, but restoring is a "
            "repair somebody has to know to perform, so past this count a "
            "delete reads as a sweep and is worth a question. The line sits "
            "where an ordinary refactor stops and a sweep starts: deleting a "
            "package's worth of tracked, unmodified files is a normal edit "
            "whose worst case is one checkout, and pricing it at an approval "
            "buys a prompt that teaches nobody anything"
        ),
    )
    sandbox: HookSandbox | None = None

    @model_validator(mode="after")
    def a_toolchain_is_named_rather_than_located(self) -> "HookSet":
        """Refuse a declared program that spells the environment holding it.

        Resolution already asks the checkout where its environment is, and so
        answers for the ones no path can reach: a redirected
        ``UV_PROJECT_ENVIRONMENT``, a conda or pyenv install found on
        ``PATH``. Spelling that directory here re-derives what resolution
        derives, and gets it wrong for every layout but the one spelled —
        where the program resolves to nothing, the gate reports no findings,
        and silence is exactly what a clean file looks like. Nothing
        downstream is placed to say otherwise, which is why this is refused
        at construction rather than reported later.

        A path stays declarable, for a program a project genuinely vendors at
        a fixed place of its own. Naming *the environment* is what is
        refused, because that question already has a better answer.
        """
        for field, command in (
            ("diagnostics_command", self.diagnostics_command),
            ("resolution_command", self.resolution_command),
        ):
            program = PurePosixPath(command[0] if command else "")
            if DEFAULT_ENVIRONMENT in program.parts:
                raise ValueError(
                    f"{field} spells {DEFAULT_ENVIRONMENT!r} in {command[0]!r}; "
                    f"declare {program.name!r} and let the checkout answer "
                    "where its environment is"
                )
        return self

    def excluded_commands(self) -> list[str]:
        """Commands no OS boundary confines, declared sandbox or not.

        Undeclared reads the same as declared-with-nothing-excluded here,
        which is what lets every compiled dispatcher take the answer without
        first asking whether a sandbox exists to have an opinion.
        """
        return list(self.sandbox.excluded_commands) if self.sandbox else []

    def resolved_shell_rules(self) -> list[ShellCommandRule]:
        """The shell vocabulary this project actually judges by.

        Asked here rather than resolved at each caller, because the canonical
        policy and both generated dispatchers have to walk the same table. A
        second place that knew which defaults a selection layers over is the
        shape of a policy that decides one way in a session and another way in
        the plugin that session's own declaration generated.
        """
        return self.shell_rules.over(default_vocabulary())

    def resolved_edit_rules(self) -> list[EditRule]:
        """The edit table this project layers over the kernel's own verdicts.

        Resolved over an empty library table on purpose: the defaults for this
        family live in the gates themselves, where a selection cannot retire
        one out from under the project that never asked to.
        """
        return self.edit_rules.over([])


class ResolveSpec(BaseModel, frozen=True):
    id: str
    worker_identity: NativeName
    """The identity a worker session declares, and the one the edit policy
    grants autonomy to. Both adapters derive their autonomous list from this
    single fact, so a runtime cannot silently ship an empty one."""

    worker_skill: SkillInvocation
    review_skill: SkillInvocation
    merge_skill: SkillInvocation


class Plugin(BaseModel, frozen=True):
    id: str
    name: NativeName
    # Namespaces the plugin inside the selected CODEX_HOME and remains required
    # for callers that deliberately share one home across projects.
    marketplace: NativeName
    version: str
    description: PortableText = Field(min_length=1, max_length=1024)
    skills: list[Skill]
    agents: list[Agent]
    mcp_servers: list[McpServer] = []
    hooks: HookSet | None = None

    @model_validator(mode="after")
    def unique_effective_names(self) -> "Plugin":
        skill_names = [skill.name for skill in self.skills]
        agent_names = [agent.name for agent in self.agents]
        server_names = [server.name for server in self.mcp_servers]
        if len(skill_names) != len(dict.fromkeys(skill_names)):
            raise ValueError(f"plugin {self.id!r} has duplicate skill names")
        if len(agent_names) != len(dict.fromkeys(agent_names)):
            raise ValueError(f"plugin {self.id!r} has duplicate agent names")
        if len(server_names) != len(dict.fromkeys(server_names)):
            raise ValueError(f"plugin {self.id!r} has duplicate MCP server names")
        return self


class Harness(BaseModel, frozen=True):
    schema_version: int = 1
    generator_version: str
    source_evidence: dict[str, str] = {}  # lup: ignore[dict-str-payload]
    plugins: list[Plugin]
    guidance: PromptDocument
    resolver: ResolveSpec
    requirements: Manifest = Manifest()
    """The external programs this project needs, exercised before a launch.

    Empty declares no requirement and checks nothing, which is right for a
    project whose toolchain is entirely Python: a preflight that invented
    prerequisites would refuse machines that were fine. What a project does
    declare here is checked by the launch, printed by the standalone command,
    and installed into any image built from this harness -- one roster, so
    the three cannot describe different toolchains.
    """
    image: Image = Image()
    """The container an agent session runs in, built from the roster above.

    Separate from ``requirements`` because it answers a different question:
    that says *what* the toolchain is, this says how a container carrying it
    is assembled and started. The package list is not repeated here -- it is
    read off the manifest, so an image cannot be built from a roster the
    preflight never exercised.
    """

    @property
    def declared_hooks(self) -> HookSet:
        """The hook set this harness enforces, wherever a plugin declares it.

        A session composed in process reaches the same declaration the
        generated plugins are compiled from, so what a launched tree enforces
        and what an in-process session enforces cannot come apart.
        """
        return next(plugin.hooks for plugin in self.plugins if plugin.hooks is not None)

    def holding(self, rules: RuleSelection) -> "Harness":
        """This harness compiled against a different selection of scan rules.

        One way in, for the one caller that has a reason: a launch opening a
        session the rules are not the point of. Every plugin is rewritten
        together, because one selection reaches the sweep, the edit hook and
        the generated reference — and a tree relaxed on one runtime and not
        another would be two policies wearing one name.

        A copy rather than a mutation, and only generation reads it. What a
        repository holds itself to stays the declaration in its catalog,
        which is where a durable answer belongs and where `dev seams` writes
        one.
        """
        return self.model_copy(
            update={
                "plugins": [
                    plugin
                    if plugin.hooks is None
                    else plugin.model_copy(
                        update={
                            "hooks": plugin.hooks.model_copy(update={"rules": rules})
                        }
                    )
                    for plugin in self.plugins
                ]
            }
        )

    @property
    def rendered_ids(self) -> list[str]:
        """Every declaration a target renders as an artifact of its own.

        The roster as the source states it, before any target has shaped it
        into files. Each id is what a rendered artifact carries back, so this
        is the one list both trees can be measured against — which is how a
        target that silently renders one fewer skill than another is caught
        without either tree's own path shapes entering the comparison.

        The tool servers are absent because they are not rendered as
        artifacts: each target writes its whole server table into one shared
        configuration file, which carries that file's own id. So a dropped
        server is a difference in an artifact's content rather than a missing
        artifact, and asking for one by id would report every server missing
        from every tree.

        That difference is answered where the format is known, by one test
        per adapter reading the whole table back out of the artifact it was
        written into. Asking it here instead would mean parsing both formats,
        which is the runtime spelling this list exists to stay clear of.
        """
        return [
            declaration_id
            for plugin in self.plugins
            for declaration_id in [
                plugin.id,
                *[skill.id for skill in plugin.skills],
                *[agent.id for agent in plugin.agents],
            ]
        ]

    @property
    def declared_ids(self) -> list[str]:
        """Every semantic id this source names anywhere, in declaration order.

        Wider than :attr:`rendered_ids` by the tool servers, because this
        answers whether two declarations collide rather than whether a target
        rendered one, and a server's id collides with a skill's exactly as a
        skill's does.
        """
        return [
            declaration_id
            for plugin in self.plugins
            for declaration_id in [
                plugin.id,
                *[skill.id for skill in plugin.skills],
                *[agent.id for agent in plugin.agents],
                *[server.id for server in plugin.mcp_servers],
            ]
        ]

    @model_validator(mode="after")
    def unique_semantic_ids(self) -> "Harness":
        ids = self.declared_ids
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
            issued
            for prompt in prompts
            for part in prompt.parts
            if (issued := part.invocation) is not None
        ]
        invocations.extend(
            [
                self.resolver.worker_skill,
                self.resolver.review_skill,
                self.resolver.merge_skill,
            ]
        )
        for invocation in invocations:
            skill = skills.get((invocation.plugin, invocation.skill))
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
            named
            for part in parts
            if (named := part.named_plugin) is not None and named not in plugin_names
        ]
        if unknown_plugins:
            raise ValueError(f"prompt parts name unknown plugins: {unknown_plugins}")
        unknown_agents = [
            delegated
            for part in parts
            if (delegated := part.named_agent) is not None
            and delegated not in declared_agents
        ]
        if unknown_agents:
            raise ValueError(f"delegations name unknown agents: {unknown_agents}")

        used = self.guidance.text_size()
        if used > GUIDANCE_BYTE_BUDGET:
            raise ValueError(
                f"always-loaded guidance is {used} bytes, over the "
                f"{GUIDANCE_BYTE_BUDGET} budget by "
                f"{used - GUIDANCE_BYTE_BUDGET}. Move a section to a "
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


class Artifact(BaseModel, frozen=True):
    path: ArtifactPath
    content: NormalizedText
    semantic_id: str = Field(min_length=1)
    executable: bool = False
    banner: ArtifactBanner | None = None
    """This artifact's provenance, or its declared reason for carrying none.
    Leaving it unset states nothing, which :mod:`lup.harness.validation`
    accepts only for a format that admits no comment at all."""

    @classmethod
    def generated(
        cls,
        *,
        path: ArtifactPath,
        body: str,
        semantic_id: str,
        banner: GeneratedBanner,
        executable: bool = False,
    ) -> "Artifact":
        """Compose one artifact beneath the banner naming what produced it."""
        return cls(
            path=path,
            content=banner.applied_to(path, body),
            semantic_id=semantic_id,
            executable=executable,
            banner=banner,
        )

    @model_validator(mode="after")
    def banner_opens_content(self) -> "Artifact":
        if self.banner is not None and not self.banner.opens(self.path, self.content):
            raise ValueError(
                f"artifact {self.path.as_posix()} does not open with the banner "
                "it declares"
            )
        return self


class ArtifactTree(BaseModel, frozen=True):
    artifacts: list[Artifact]

    @model_validator(mode="after")
    def unique_paths(self) -> "ArtifactTree":
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(dict.fromkeys(paths)):
            raise ValueError("artifact paths must be unique")
        return self


class CapabilityReport(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """A runtime probe's verdict, without the payload that proves it.

    Split from the evidence because the commands that report readiness read
    only the verdict — which capability, whether it is there, at what
    version. The proof is the adapter's own shape, so a command typed
    against this stays free of every runtime it reports on, and one that
    genuinely needs the proof asks for :class:`CapabilityEvidence` instead.
    """

    capability: str
    supported: bool
    version: str


class CapabilityEvidence[C](CapabilityReport, frozen=True):
    """One probe's verdict together with the adapter-shaped proof of it."""

    evidence: C


class Resumption(BaseModel, frozen=True):
    """Which earlier session a launch reopens, if any.

    One shape for every launcher, because what an operator is asking for is
    the same whichever runtime answers and only the spelling differs — a flag
    on one, a subcommand on another. Declared once rather than as three loose
    booleans threaded through each launcher, so a runtime added later answers
    one question instead of being handed three that can disagree.

    Reopening matters beyond convenience, which is what makes it worth a
    declaration. The policy a session enforces is compiled into a plugin tree
    its runtime loads at startup, so widening that policy takes effect only in
    a new process — and a new process that started from nothing costs the whole
    conversation that established what the widening was for. That price is
    what pushes an agent toward a per-call escape, which helps once and
    evaporates. With reopening, the durable path is also the cheap one:
    propose the declaration edit, have it approved, regenerate, reopen.
    """

    latest: bool = False
    """Reopen the most recent session here, without choosing one."""

    pick: bool = False
    """Offer the runtime's own picker over this project's sessions."""

    session: str | None = None
    """Reopen one session by the id its runtime knows it as."""

    def wanted(self) -> bool:
        """Whether this launch is reopening anything at all."""
        return self.latest or self.pick or self.session is not None

    def contradicted(self) -> str | None:
        """The complaint, when more than one session was named at once.

        Refused rather than ranked: an order of precedence here would be this
        module deciding which of two things an operator meant, and being
        wrong about it silently.
        """
        asked = [
            name
            for name, given in (
                ("--continue", self.latest),
                ("--resume", self.pick),
                ("--session", self.session is not None),
            )
            if given
        ]
        if len(asked) < 2:
            return None
        return f"a launch reopens one session; got {', '.join(asked)}"
