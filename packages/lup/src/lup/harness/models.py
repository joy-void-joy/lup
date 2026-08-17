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
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from lup.codescan.common import RuleSelection
from lup.harness.banner import ArtifactBanner, GeneratedBanner
from lup.markdown import TableCell, escaped
from lup.policy.kernel.rows import PathRoleName
from lup.policy.models import PolicyId, UrlPathPrefix
from lup.policy.refused_tools import RefusedTool
from lup.policy.shell_rules import RunnerTargetRule, ShellCommandRule
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


class PartPayload(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """What a part carries, as every walk across a document asks for it.

    One shape rather than a question per kind, because these are asked of a
    part whose kind the caller does not know: a walk weighing what a
    declaration literally says reaches every kind that holds prose, including
    kinds written long after it was. A kind carrying none of something leaves
    the default, which is what makes omission safe.
    """

    text: str | None = None
    """Portable prose this part carries verbatim, if it carries any."""

    invocation: "SkillRef | None" = None
    """The skill invocation this part issues, if it issues one."""

    named_plugin: NativeName | None = None
    """The plugin this part names, which the harness must have declared."""

    named_agent: QualifiedAgentName | None = None
    """The agent this part delegates to, which must also be declared."""

    references_arguments: bool = False
    """Whether this part reaches the arguments its invocation supplied."""


class PartRecord(BaseModel, frozen=True):
    """One part as a declaration digest writes it down.

    Not a wire format anybody reads back: it exists so the whole declaration
    graph has a canonical encoding, which is what tells a changed declaration
    from a changed renderer. ``kind`` names the class and ``fields`` its own
    data, both stable across runs — a part is not rebuilt from one of these,
    so nothing here has to be enough to reconstruct it, only enough to differ
    when the declaration differs.
    """

    kind: str
    fields: dict[str, JsonValue] = {}


class SemanticPart(ABC):
    """One element of a prompt document, answering every question about itself.

    Two projections and no state: what the part carries, and how the runtime
    reading it spells the part. A new kind of part is one class rather than an
    edit to every walk that would have to notice it.

    A kind holding portable prose passes it through :func:`portable_prose` as
    it is built, so text spelling one runtime's invocation is refused where it
    is written rather than wherever it is eventually rendered.
    """

    @abstractmethod
    def payload(self) -> PartPayload:
        """What this part carries, for a caller that does not know its kind."""

    @abstractmethod
    def spell(self, renderer: "PromptRenderer") -> str:
        """Render this part in the vocabulary of the runtime that reads it."""


class TextPart(SemanticPart):
    """Portable prose, refused if it spells any runtime's invocation."""

    def __init__(self, text: str) -> None:
        self.text = portable_prose(text)

    def payload(self) -> PartPayload:
        return PartPayload(text=self.text)

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.text


class SpellingExample(SemanticPart):
    """Prose whose subject is a runtime's own spelling, quoted verbatim.

    Ordinary prose refuses a rendered invocation because a reader on the other
    runtime cannot use one. A document *comparing* the runtimes has to quote
    both, so the exemption is declared here rather than left as a rule that
    quietly does not fire. It is deliberately narrow: the same words reach
    every tree, so this can only ever exhibit a spelling — never issue one,
    which is what :class:`SkillInvocation` is for.
    """

    def __init__(self, text: str) -> None:
        self.text = text

    def payload(self) -> PartPayload:
        return PartPayload(text=self.text)

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.text


class MarkdownTable(SemanticPart):
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

    def __init__(self, headers: list[str], rows: list[list[TableCell]]) -> None:
        ragged = [len(row) for row in rows if len(row) != len(headers)]
        if ragged:
            raise ValueError(
                f"table rows hold {ragged} cells under {len(headers)} headers"
            )
        self.headers = headers
        self.rows = rows

    def rendered(self) -> str:
        """The table as Markdown, one line per row, newline-terminated."""
        lines = [
            [escaped(header) for header in self.headers],
            ["---"] * len(self.headers),
            *[[cell.render() for cell in row] for row in self.rows],
        ]
        return "".join(f"| {' | '.join(line)} |\n" for line in lines)

    def payload(self) -> PartPayload:
        return PartPayload(text=self.rendered())

    def spell(self, renderer: "PromptRenderer") -> str:
        return self.rendered()


class InvocationArgument(BaseModel, frozen=True):
    name: NativeName
    value: JsonValue


class SkillRef(BaseModel, frozen=True):
    """Which skill to issue, and with what — the value, not the part.

    A part is an object a document holds; this is data a declaration stores.
    They were one class until ``ResolveSpec`` had to name three of them and a
    resolver run started saving its state, which put a prompt part inside a
    file. Split, each is only what it is: the ref persists, the part spells.
    """

    plugin: NativeName
    skill: NativeName
    arguments: list[InvocationArgument] = []


class SkillInvocation(SemanticPart):
    """One skill this prompt issues, resolved against the declarations."""

    def __init__(
        self,
        plugin: NativeName,
        skill: NativeName,
        arguments: list[InvocationArgument] | None = None,
    ) -> None:
        self.ref = SkillRef(
            plugin=plugin, skill=skill, arguments=arguments if arguments else []
        )

    def payload(self) -> PartPayload:
        return PartPayload(invocation=self.ref, named_plugin=self.ref.plugin)

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.render(self.ref)


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


# lup: ignore[abc-capability] — a located kind is a part before it is a
# location, so the two seams nest rather than compose: the document holds it as
# a part and only the renderer asks it to spell a place
class LocatedPart(SemanticPart):
    """One path a prompt names, spelled by whichever adapter renders it.

    Scope is the same question for every location — whether the reader's own
    tree answers it or every tree must be taught at once — so the renderer asks
    it once and each kind only says how it spells itself in one vocabulary.
    """

    scope: PathScope = "this_tree"

    @abstractmethod
    def spell_in(self, runtime: "NativeSpellings") -> str:
        """Spell this location in one runtime's own vocabulary."""

    # lup: ignore[abc-capability] — scope is one question for every location, so
    # the renderer asks it once and each kind only spells itself
    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.location(self)

    # lup: ignore[abc-capability] — a location carries none of what a payload
    # asks about, and saying so once beats saying it in each located kind
    def payload(self) -> PartPayload:
        return PartPayload()


class NativePath(LocatedPart):
    """One harness-tree location, spelled by whichever adapter renders it."""

    def __init__(self, location: TreeLocation, scope: PathScope = "this_tree") -> None:
        self.location: TreeLocation = location
        self.scope: PathScope = scope

    def spell_in(self, runtime: "NativeSpellings") -> str:
        return runtime.tree(self.location)


class PluginPath(LocatedPart):
    """One plugin-owned location, spelled by whichever adapter renders it.

    ``member`` selects a leaf whose whole path differs per runtime — a skill is
    one file under one runtime and a directory under another — while omitting
    it names the containing directory.
    """

    def __init__(
        self,
        plugin: NativeName,
        location: PluginLocation,
        member: PathMember | None = None,
        scope: PathScope = "this_tree",
    ) -> None:
        self.plugin = plugin
        self.location: PluginLocation = location
        self.member = member
        self.scope: PathScope = scope

    def spell_in(self, runtime: "NativeSpellings") -> str:
        return runtime.plugin(self.plugin, self.location, self.member)

    def payload(self) -> PartPayload:
        return PartPayload(named_plugin=self.plugin)


class SkillPattern(SemanticPart):
    """An invocation shape standing in for a skill the reader will name.

    ``SkillInvocation`` resolves against the declaration registry, so it cannot
    express the placeholder or wildcard a prompt uses when it teaches the shape
    of an invocation rather than issuing one.
    """

    def __init__(self, plugin: NativeName, placeholder: PathMember) -> None:
        self.plugin = plugin
        self.placeholder = placeholder

    def payload(self) -> PartPayload:
        return PartPayload(named_plugin=self.plugin)

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.invocation_pattern(self.plugin, self.placeholder)


class RuntimeDocs(SemanticPart):
    """The reader's own runtime documentation, wherever that runtime is."""

    def payload(self) -> PartPayload:
        return PartPayload()

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.runtime_docs()


class AskUser(SemanticPart):
    """A question the reader puts to whoever asked for the work."""

    def __init__(self, question: str) -> None:
        self.question = portable_prose(question)

    def payload(self) -> PartPayload:
        return PartPayload()

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.ask_user(self.question)


class Delegate(SemanticPart):
    """Work handed to a declared agent rather than done in this session."""

    def __init__(self, subagent_type: QualifiedAgentName, prompt: str) -> None:
        self.subagent_type = subagent_type
        self.prompt = portable_prose(prompt)

    def payload(self) -> PartPayload:
        return PartPayload(named_agent=self.subagent_type)

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.delegate(self.subagent_type, self.prompt)


class RequestApproval(SemanticPart):
    """An action the reader asks approval for before taking it."""

    def __init__(self, action: str, reason: str) -> None:
        self.action = portable_prose(action)
        self.reason = portable_prose(reason)

    def payload(self) -> PartPayload:
        return PartPayload()

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.request_approval(self.action, self.reason)


class RelocateSession(SemanticPart):
    """Continue work inside an already-created worktree.

    Runtimes differ on whether a running session can move: one relocates in
    place, another can only be replaced by a session started there. Naming
    the intent lets each adapter spell the move it actually supports.
    """

    def __init__(self, path: str) -> None:
        self.path = portable_prose(path)
        """Where the reader finds the path, e.g. "the path step 1 prints"."""

    def payload(self) -> PartPayload:
        return PartPayload()

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.relocate_session(self.path)


class ResolverEntry(SemanticPart):
    """The reader's way into a resolver run, spelled by its own runtime."""

    def payload(self) -> PartPayload:
        return PartPayload()

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.resolver_entry()


class ArgumentsRef(SemanticPart):
    """The arguments this skill's invocation supplied, wherever they land."""

    def payload(self) -> PartPayload:
        return PartPayload(references_arguments=True)

    def spell(self, renderer: "PromptRenderer") -> str:
        return renderer.own.arguments_ref()


def part_record(part: SemanticPart) -> PartRecord:
    """One part written down, for a digest over the whole declaration graph.

    Read off the part's own attributes rather than answered by each kind,
    because writing a value down is what a digest does to a part rather than
    something a part does to itself — and a per-kind answer is one more thing
    a new kind could forget.

    An attribute of a shape this cannot encode raises rather than falling back
    to ``str``: a default repr carries an address, and a digest that changes
    when a value moves in memory reports a declaration change on every run.
    """

    def written(value: object) -> JsonValue:  # lup: ignore[bare-object]
        match value:
            case str() | int() | float() | bool() | None:
                return value
            case Path() | PurePosixPath():
                return value.as_posix()
            case BaseModel():
                return value.model_dump(mode="json")
            case list():
                return [written(item) for item in value]
        raise TypeError(
            f"{type(part).__name__} holds {type(value).__name__}, which a "
            "declaration digest has no stable encoding for"
        )

    return PartRecord(
        kind=type(part).__name__,
        fields={name: written(value) for name, value in vars(part).items()},
    )


type PromptPart = Annotated[SemanticPart, PlainSerializer(part_record)]
"""One element of a document, whatever kind it is.

Formerly a discriminated union of every kind, because a pydantic field holding
the base rebuilt each part as that base and dropped its payload. Nothing
validates a part into being — a catalog constructs one directly — so the base
is what a field names, and the kinds answer for themselves.

The serializer is what keeps the declaration graph digestible: parts are
objects, and a digest over the graph is how a changed declaration is told from
a changed renderer.
"""


class PromptDocument(BaseModel, frozen=True, arbitrary_types_allowed=True):
    parts: list[PromptPart]
    source: str | None = None
    """The module declaring this document, for the banner of an artifact
    rendered from it alone. A document folded into a skill or agent prompt
    reaches no artifact of its own and names no source."""

    def declared_source(self) -> str:
        """The declaring module, required because this document becomes a file."""
        if self.source is None:
            raise ValueError("a document rendered to its own artifact needs a source")
        return self.source

    def prose(self) -> list[str]:
        """Every literal prose payload this document carries, in reading order."""
        return [
            text for part in self.parts if (text := part.payload().text) is not None
        ]

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


def document_byte_size(text: str) -> int:
    """What a rendered document costs the runtime that loads it, in UTF-8 bytes."""
    return len(text.encode("utf-8"))


class Argument(BaseModel, frozen=True):
    name: NativeName
    description: PortableText = Field(min_length=1, max_length=1024)
    required: bool = False


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
            part.payload().references_arguments for part in self.prompt.parts
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


class Agent(BaseModel, frozen=True):
    id: str
    name: NativeName
    description: PortableText = Field(min_length=1, max_length=1024)
    prompt: PromptDocument
    tools: list[ToolName] = []
    model: ModelTier | None = None
    color: AgentColor | None = None


class McpWord(BaseModel, frozen=True):
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
    """

    root: Path
    role: PathRoleName


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

    # lup: solved: This cannot declare `excludedCommands`, which is the only per-command
    # lever the sandbox has — it takes a command out of isolation entirely
    # rather than lifting one rule. Two things here need it and neither can say
    # so: docker, which the harness documents as incompatible with the sandbox
    # ("add `docker *` to excludedCommands"), so `py eval` fails on a blocked
    # socket for a documented reason rather than a wiring bug; and ssh/git/gh,
    # whose egress the HTTP proxy cannot carry. It is an array key merged across
    # scopes, so project settings can declare it.
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
    shell_rules: list[ShellCommandRule] = Field(
        default=[],
        description=(
            "The whole shell vocabulary this project judges safe, asked, or "
            "denied; declare a downstream toolchain here, not in the kernel"
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
    recoverable_target_limit: int = Field(
        default=5,
        ge=0,
        description=(
            "How many committed, unmodified files one command may destroy "
            "without asking. Git restores each of them, but restoring is a "
            "repair somebody has to know to perform, so past this count a "
            "delete reads as a sweep and is worth a question"
        ),
    )
    sandbox: HookSandbox | None = None

    def excluded_commands(self) -> list[str]:
        """Commands no OS boundary confines, declared sandbox or not.

        Undeclared reads the same as declared-with-nothing-excluded here,
        which is what lets every compiled dispatcher take the answer without
        first asking whether a sandbox exists to have an opinion.
        """
        return list(self.sandbox.excluded_commands) if self.sandbox else []


class ResolveSpec(BaseModel, frozen=True):
    id: str
    worker_identity: NativeName
    """The identity a worker session declares, and the one the edit policy
    grants autonomy to. Both adapters derive their autonomous list from this
    single fact, so a runtime cannot silently ship an empty one."""

    worker_skill: SkillRef
    review_skill: SkillRef
    merge_skill: SkillRef


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

    @property
    def declared_hooks(self) -> HookSet:
        """The hook set this harness enforces, wherever a plugin declares it.

        A session composed in process reaches the same declaration the
        generated plugins are compiled from, so what a launched tree enforces
        and what an in-process session enforces cannot come apart.
        """
        return next(plugin.hooks for plugin in self.plugins if plugin.hooks is not None)

    @model_validator(mode="after")
    def unique_semantic_ids(self) -> "Harness":
        ids = [
            declaration_id
            for plugin in self.plugins
            for declaration_id in [
                plugin.id,
                *[skill.id for skill in plugin.skills],
                *[agent.id for agent in plugin.agents],
                *[server.id for server in plugin.mcp_servers],
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
            issued
            for prompt in prompts
            for part in prompt.parts
            if (issued := part.payload().invocation) is not None
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
            named
            for part in parts
            if (named := part.payload().named_plugin) is not None
            and named not in plugin_names
        ]
        if unknown_plugins:
            raise ValueError(f"prompt parts name unknown plugins: {unknown_plugins}")
        unknown_agents = [
            delegated
            for part in parts
            if (delegated := part.payload().named_agent) is not None
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
