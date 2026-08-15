"""Move every `model_config` assignment into the class header that owns it.

The `model-config-assign` rule names the form this codebase wants: a config
key belongs beside the base it configures, in the class header, rather than in
a statement the reader meets somewhere after the docstring. Naming the form is
one rule; the sites that predate it are several hundred, and by hand is where
a convention that size gets abandoned — so the mechanical half is a command,
as repointing a module that moved already is.

Grammar decides, text applies. `ast` locates the assignment and the header
span it moves into, and each move is spliced over that one span, so a base
list running across several lines, a comment beside it, and the rest of the
file survive byte for byte. What grammar cannot settle is reported rather than
guessed at: an assignment whose value is neither a `ConfigDict` call, a dict
literal, nor a name bound to one is left where it stands, named in the report.

A shared alias — `FROZEN = ConfigDict(frozen=True)` declared once and bound in
thirty classes — is that same assignment one indirection out, so it converts
with the rest. The index resolves such a name through the module that declares
it, following the `from ... import` that carried it elsewhere, and the
declaration goes once nothing binds it. The imports that leaves dangling are
ruff's to remove, as every other unused name already is.
"""

import ast
from collections.abc import Iterator, Sequence, Set as AbstractSet
from itertools import accumulate
from pathlib import Path

from pydantic import BaseModel

from lup.codescan.common import PACKAGE_ROOTS, module_name

CONFIG_CALLS = ("ConfigDict", "SettingsConfigDict")
"""The config constructors whose keywords a class header carries instead.

Canonical rather than a judgement: these are pydantic's and pydantic-settings'
own spellings, and a call to anything else was never a pydantic config.
"""


class AliasBinding(BaseModel, frozen=True):
    """One dotted name a shared config alias is reachable by, and what it holds."""

    dotted: str
    keywords: list[str]


class ParsedModule(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One source file read once: where it lives, what it is called, its tree."""

    path: Path
    module: str
    text: str
    tree: ast.Module


class ClassFacts(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One class the sweep can see: where it lives and what its header says."""

    module: str
    node: ast.ClassDef
    frozen: bool


class Splice(BaseModel, frozen=True):
    """One replacement over a half-open character span of a file's text."""

    start: int
    end: int
    text: str


class Unsettled(BaseModel, frozen=True):
    """A config declaration grammar could not settle, left for a human to read."""

    path: Path
    line: int
    reason: str


class ClassConversion(BaseModel, frozen=True):
    """One class's move: the splices it needs, or the reason it has none."""

    splices: list[Splice]
    unsettled: Unsettled | None


class FileConversion(BaseModel, frozen=True):
    """One file's rewritten text, what moved into a header, and what stayed."""

    path: Path
    before: str
    text: str
    headers: int
    aliases: int
    unsettled: list[Unsettled]

    def changed(self) -> bool:
        """Whether the conversion actually rewrote anything in this file."""
        return self.text != self.before


class SourceOffsets(BaseModel, frozen=True):
    """Character offsets for the byte columns an AST position reports."""

    lines: list[str]
    starts: list[int]

    def at(self, line: int, column: int) -> int:
        """The character offset of a 1-based line and 0-based byte column."""
        prefix = self.lines[line - 1].encode()[:column]
        return self.starts[line - 1] + len(prefix.decode())

    def line_start(self, line: int) -> int:
        """The character offset a 1-based line begins at, end of file included."""
        return self.starts[min(line, len(self.starts)) - 1]

    def blank(self, line: int) -> bool:
        """Whether a 1-based line exists and holds nothing but whitespace."""
        return 1 <= line <= len(self.lines) and not self.lines[line - 1].strip()


def source_offsets(text: str) -> SourceOffsets:
    """Index a file's lines so an AST position becomes a character offset."""
    lines = text.splitlines(keepends=True)
    lengths = (len(line) for line in lines)
    return SourceOffsets(lines=lines, starts=list(accumulate(lengths, initial=0)))


def parsed_modules(
    paths: Sequence[Path], roots: AbstractSet[str] = PACKAGE_ROOTS
) -> Iterator[ParsedModule]:
    """Read and parse every file handed in, passing over what will not parse.

    A file whose grammar is unavailable is somebody else's report to make —
    the type check and the test suite both fail on it — and nothing here can
    rewrite source it cannot read.
    """
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        yield ParsedModule(
            path=path, module=module_name(path, roots), text=text, tree=tree
        )


def keyword_text(text: str, name: str, value: ast.expr) -> str | None:
    """One `name=value` keyword, or None where the value has no source span."""
    source = ast.get_source_segment(text, value)
    return None if source is None else f"{name}={source}"


def declared_keywords(value: ast.expr, text: str) -> list[str] | None:
    """The class keywords a config expression carries, or None if it is not one.

    Both spellings the codebase uses settle here: the `ConfigDict(...)` call
    and the bare dict literal, which pydantic accepts equally. A `**` splat or
    a computed key carries names no header can spell, so it settles as neither.
    """
    match value:
        case ast.Call(func=ast.Name(id=name), args=args, keywords=keywords) if (
            name in CONFIG_CALLS and not args
        ):
            rendered = [
                keyword_text(text, keyword.arg, keyword.value)
                for keyword in keywords
                if keyword.arg is not None
            ]
            expected = len(keywords)
        case ast.Dict(keys=keys, values=values):
            named = [
                key.value
                for key in keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            if len(named) != len(keys):
                return None
            rendered = [
                keyword_text(text, key, item)
                for key, item in zip(named, values, strict=True)
            ]
            expected = len(keys)
        case _:
            return None
    settled = [item for item in rendered if item is not None]
    return settled if len(settled) == expected else None


def module_aliases(parsed: ParsedModule) -> Iterator[AliasBinding]:
    """Each module-level config alias a module declares for others to bind."""
    for statement in alias_statements(parsed):
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                keywords = declared_keywords(value, parsed.text)
                if keywords is not None:
                    yield AliasBinding(
                        dotted=f"{parsed.module}.{name}", keywords=keywords
                    )


def alias_bindings(modules: Sequence[ParsedModule]) -> dict[str, AliasBinding]:
    """Every dotted name that reaches a shared config alias, declared or imported.

    Two passes, because an import resolves only once every declaration is
    known: the first collects `NAME = ConfigDict(...)` where it is written,
    the second binds the same keywords under the name each importing module
    knows them by. The same name declared differently in two modules —
    `FROZEN` is not the same dict everywhere — stays two entries, so a site
    resolves against the declaration its own module can see.
    """
    declared = {
        binding.dotted: binding
        for parsed in modules
        for binding in module_aliases(parsed)
    }

    def imported() -> Iterator[AliasBinding]:
        """The same keywords again, under the name an importing module uses."""
        for parsed in modules:
            for statement in parsed.tree.body:
                if not isinstance(statement, ast.ImportFrom):
                    continue
                for name in statement.names:
                    origin = f"{statement.module}.{name.name}"
                    if origin in declared:
                        yield AliasBinding(
                            dotted=f"{parsed.module}.{name.asname or name.name}",
                            keywords=declared[origin].keywords,
                        )

    return {**declared, **{binding.dotted: binding for binding in imported()}}


def resolved_keywords(
    value: ast.expr, parsed: ParsedModule, index: dict[str, AliasBinding]
) -> list[str] | None:
    """The keywords a config expression carries, following a shared alias."""
    match value:
        case ast.Name(id=name) if f"{parsed.module}.{name}" in index:
            return index[f"{parsed.module}.{name}"].keywords
        case _:
            return declared_keywords(value, parsed.text)


def config_statement(node: ast.ClassDef) -> ast.Assign | None:
    """The config assignment a class body declares, if it declares one."""

    def declared() -> Iterator[ast.Assign]:
        for statement in node.body:
            match statement:
                case ast.Assign(targets=[ast.Name(id="model_config")]):
                    yield statement

    return next(declared(), None)


def alias_statements(parsed: ParsedModule) -> Iterator[ast.Assign]:
    """Every module-level assignment that binds a config for classes to share.

    A call to a config constructor, and only that. The dict-literal spelling a
    class body may use is not available here: at module level it is how every
    ordinary mapping constant is written too, and nothing in the statement
    distinguishes a shared config from a table of environment variables.
    """
    for statement in parsed.tree.body:
        match statement:
            case ast.Assign(
                targets=[ast.Name()], value=ast.Call(func=ast.Name(id=name))
            ) if name in CONFIG_CALLS:
                yield statement


def header_splice(
    node: ast.ClassDef, keywords: Sequence[str], offsets: SourceOffsets
) -> Splice | None:
    """Insert the keywords after the last base or keyword the header declares.

    After the last anchor rather than before the closing parenthesis, because
    the two differ wherever a base list wraps: appending to the anchor keeps
    the keywords inside the parentheses whatever the line breaks are doing,
    and leaves the formatter to decide where the result wraps.
    """
    anchors = [*node.bases, *node.keywords]
    if not anchors:
        return None
    last = max(
        anchors,
        key=lambda anchor: (anchor.end_lineno or 0, anchor.end_col_offset or 0),
    )
    at = offsets.at(last.end_lineno or last.lineno, last.end_col_offset or 0)
    return Splice(
        start=at, end=at, text="".join(f", {keyword}" for keyword in keywords)
    )


def removal_splice(statement: ast.stmt, offsets: SourceOffsets) -> Splice:
    """Delete a statement's lines, and the blank line the gap would double."""
    first = statement.lineno
    last = statement.end_lineno or first
    doubled = offsets.blank(first - 1) and offsets.blank(last + 1)
    tail = last + 1 if doubled else last
    return Splice(
        start=offsets.line_start(first), end=offsets.line_start(tail + 1), text=""
    )


def class_conversion(
    parsed: ParsedModule,
    index: dict[str, AliasBinding],
    offsets: SourceOffsets,
    node: ast.ClassDef,
    statement: ast.Assign,
) -> ClassConversion:
    """Move one class's config into its header, or say why it cannot move."""

    def refused(reason: str) -> ClassConversion:
        return ClassConversion(
            splices=[],
            unsettled=Unsettled(path=parsed.path, line=statement.lineno, reason=reason),
        )

    keywords = resolved_keywords(statement.value, parsed, index)
    if keywords is None:
        return refused("config is neither a config call, a dict, nor a name for one")
    if len(node.body) == 1:
        return refused("the config is the whole class body, which cannot go empty")
    header = header_splice(node, keywords, offsets)
    if header is None:
        return refused("class header declares no base for the keywords to join")
    return ClassConversion(
        splices=[header, removal_splice(statement, offsets)], unsettled=None
    )


def class_conversions(
    parsed: ParsedModule, index: dict[str, AliasBinding], offsets: SourceOffsets
) -> Iterator[ClassConversion]:
    """Each class in a module whose config moves, or refuses to."""
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.ClassDef):
            continue
        statement = config_statement(node)
        if statement is not None:
            yield class_conversion(parsed, index, offsets, node, statement)


def declared_classes(parsed: ParsedModule) -> Iterator[ClassFacts]:
    """Every class a module declares, and whether its own header freezes it."""
    for node in parsed.tree.body:
        if isinstance(node, ast.ClassDef):
            frozen = any(
                keyword.arg == "frozen"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            yield ClassFacts(module=parsed.module, node=node, frozen=frozen)


def visible_classes(modules: Sequence[ParsedModule]) -> dict[str, ClassFacts]:
    """Every dotted name a class is reachable by, declared or imported.

    The same two passes the alias index takes, for the same reason: a base
    named in one module is declared in another, and the name in the header is
    whatever the import called it.
    """
    declared = {
        f"{facts.module}.{facts.node.name}": facts
        for parsed in modules
        for facts in declared_classes(parsed)
    }

    def imported() -> Iterator[AliasBinding]:
        """Each import that names a class the sweep already knows."""
        for parsed in modules:
            for statement in parsed.tree.body:
                if not isinstance(statement, ast.ImportFrom):
                    continue
                for name in statement.names:
                    origin = f"{statement.module}.{name.name}"
                    if origin in declared:
                        yield AliasBinding(
                            dotted=f"{parsed.module}.{name.asname or name.name}",
                            keywords=[origin],
                        )

    return {
        **declared,
        **{binding.dotted: declared[binding.keywords[0]] for binding in imported()},
    }


def base_classes(
    facts: ClassFacts, visible: dict[str, ClassFacts]
) -> Iterator[ClassFacts]:
    """Each base of a class that the sweep can also see."""
    for base in facts.node.bases:
        if isinstance(base, ast.Name):
            key = f"{facts.module}.{base.id}"
            if key in visible:
                yield visible[key]


def frozen_anywhere(facts: ClassFacts, visible: dict[str, ClassFacts]) -> bool:
    """Whether a class is frozen, by its own header or by one it inherits."""
    return facts.frozen or any(
        frozen_anywhere(parent, visible) for parent in base_classes(facts, visible)
    )


def inherited_freezes(
    parsed: ParsedModule, visible: dict[str, ClassFacts], offsets: SourceOffsets
) -> Iterator[Splice]:
    """Restate `frozen=True` where a base declares it and the subclass does not.

    Pydantic inherits the key without being told, and a body assignment left
    the checker unable to see it either way. A header states it, and the
    checker models `frozen` through `dataclass_transform`, where a class
    carries only what its own header says — so a subclass left silent now
    reads as a mutable class inheriting a frozen one, which is an error rather
    than the inheritance that actually happens.
    """
    for facts in declared_classes(parsed):
        key = f"{parsed.module}.{facts.node.name}"
        if facts.frozen or key not in visible:
            continue
        if not frozen_anywhere(visible[key], visible):
            continue
        splice = header_splice(facts.node, ["frozen=True"], offsets)
        if splice is not None:
            yield splice


def freeze_module(
    parsed: ParsedModule, visible: dict[str, ClassFacts]
) -> FileConversion:
    """Restate every freeze one module inherits but does not declare."""
    offsets = source_offsets(parsed.text)
    splices = list(inherited_freezes(parsed, visible, offsets))
    return FileConversion(
        path=parsed.path,
        before=parsed.text,
        text=spliced(parsed.text, splices),
        headers=len(splices),
        aliases=0,
        unsettled=[],
    )


def spliced(text: str, splices: Sequence[Splice]) -> str:
    """Apply every splice, latest first, so the earlier offsets stay valid."""
    body = text
    for splice in sorted(splices, key=lambda splice: splice.start, reverse=True):
        body = body[: splice.start] + splice.text + body[splice.end :]
    return body


def convert_module(
    parsed: ParsedModule, index: dict[str, AliasBinding]
) -> FileConversion:
    """Rewrite one module: every class header, and the aliases nothing will bind."""
    offsets = source_offsets(parsed.text)
    conversions = list(class_conversions(parsed, index, offsets))
    moved = [conversion for conversion in conversions if conversion.unsettled is None]
    aliases = [
        removal_splice(statement, offsets) for statement in alias_statements(parsed)
    ]
    splices = [
        *[splice for conversion in moved for splice in conversion.splices],
        *aliases,
    ]
    return FileConversion(
        path=parsed.path,
        before=parsed.text,
        text=spliced(parsed.text, splices),
        headers=len(moved),
        aliases=len(aliases),
        unsettled=[
            conversion.unsettled
            for conversion in conversions
            if conversion.unsettled is not None
        ],
    )


def convert(
    paths: Sequence[Path], roots: AbstractSet[str] = PACKAGE_ROOTS
) -> list[FileConversion]:
    """Convert every config assignment in the given files, writing as it goes.

    The alias index spans every file the sweep was handed, because a class
    binding `FROZEN` and the module declaring it are rarely the same file: a
    sweep narrow enough to miss the declaration resolves the name against
    nothing and reports the site rather than guessing what it held.

    Two sweeps, because the second reads what the first wrote: which classes
    are frozen is only legible once the key sits in a header, and only then
    can a subclass be asked whether it restates what it inherits.
    """
    modules = list(parsed_modules(paths, roots))
    index = alias_bindings(modules)
    moved = written(convert_module(parsed, index) for parsed in modules)
    reread = list(parsed_modules(paths, roots))
    visible = visible_classes(reread)
    return moved + written(freeze_module(parsed, visible) for parsed in reread)


def written(conversions: Iterator[FileConversion]) -> list[FileConversion]:
    """Write each conversion that changed something, and report those alone."""
    kept = [
        conversion
        for conversion in conversions
        if conversion.changed() or conversion.unsettled
    ]
    for conversion in kept:
        if conversion.changed():
            conversion.path.write_text(conversion.text, encoding="utf-8")
    return kept
