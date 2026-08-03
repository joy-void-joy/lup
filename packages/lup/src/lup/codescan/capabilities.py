# lup: ignore[dict-str-payload, set-shape, empty-collection, string-split]
# Symbol tables, graph sets, and qualified-name parsing are this AST rule's domain.
"""Project-wide AST enforcement for Lup capability ABC composition.

Audits every resolved project import for the ``abc-capability`` shape
described in ``docs/architecture.md``: one narrow capability per ABC, no
concrete behavior, no multiple inheritance. The ``lup-devtools dev check
--antipatterns`` auditor runs :func:`audit_capabilities` across the tree; the
anti-pattern registry re-exports the rule id so deny messages name it.
"""

import ast
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from lup.codescan.common import (
    IGNORE_RE,
    PythonContext,
    file_level_ignore,
    ignore_rule_ids,
)

RULE_ID = "abc-capability"


class PythonSource(BaseModel):
    """One import-resolvable Python module supplied to the project index."""

    model_config = ConfigDict(frozen=True)

    path: Path
    module: str
    text: str


class CapabilityFinding(BaseModel):
    """One missing, untyped, or spurious architecture suppression verdict."""

    model_config = ConfigDict(frozen=True)

    kind: str
    path: Path
    line: int
    message: str
    rule_id: str = RULE_ID


class ClassSymbol(BaseModel):
    """Resolved class shape retained by the project-wide symbol index."""

    model_config = ConfigDict(frozen=True)

    qualified_name: str
    module: str
    name: str
    path: Path
    line: int
    bases: list[str]
    abstract_methods: list[str] = Field(default_factory=list)
    abstract_properties: list[str] = Field(default_factory=list)
    concrete_callables: list[str] = Field(default_factory=list)
    member_lines: dict[str, int] = Field(default_factory=dict)


class ArchitectureViolation(BaseModel):
    """One mechanical shape violation before suppression auditing."""

    model_config = ConfigDict(frozen=True)

    path: Path
    class_line: int
    line: int
    message: str


class Directive(BaseModel):
    """One actual comment suppression that may cover architecture findings."""

    model_config = ConfigDict(frozen=True)

    path: Path
    line: int
    rule_ids: set[str] | None
    file_level: bool = False


def module_name(path: Path) -> str:
    """Infer a dotted module name from a repository-relative Python path."""
    parts = list(PurePosixPath(path.as_posix()).parts)
    # The innermost match is the package root. Taking the first one made
    # `packages/lup/src/lup/x.py` resolve to `lup.src.lup.x` — the
    # distribution directory rather than the package — so every cross-module
    # symbol lookup missed. It degrades to fewer findings rather than wrong
    # ones, which is why it went unnoticed.
    roots = [
        index for index, part in enumerate(parts) if part in {"lup", "lup_template"}
    ]
    selected = parts[roots[-1] :] if roots else parts
    if selected[-1] == "__init__.py":
        selected = selected[:-1]
    else:
        selected[-1] = PurePosixPath(selected[-1]).stem
    return ".".join(selected)


def sources_from_paths(paths: list[Path]) -> list[PythonSource]:
    """Read source files and assign import-resolvable module names."""
    return [
        PythonSource(
            path=path,
            module=module_name(path),
            text=path.read_text(encoding="utf-8"),
        )
        for path in paths
    ]


def dotted_name(node: ast.expr) -> str | None:
    """Return a dotted syntax name without evaluating it."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            parent = dotted_name(value)
            return f"{parent}.{attribute}" if parent is not None else None
        case ast.Subscript(value=value):
            return dotted_name(value)
    return None


def imported_names(tree: ast.Module, module: str) -> dict[str, str]:
    """Resolve local import aliases to absolute symbols or modules."""
    aliases: dict[str, str] = {}
    package = module.split(".")
    for node in tree.body:
        match node:
            case ast.Import(names=names):
                for item in names:
                    local = item.asname or item.name.split(".")[0]
                    aliases[local] = item.name if item.asname else local
            case ast.ImportFrom(module=target, names=names, level=level):
                if level:
                    prefix = package[:-level]
                    resolved_module = ".".join(
                        [*prefix, *([target] if target is not None else [])]
                    )
                else:
                    resolved_module = target or ""
                for item in names:
                    local = item.asname or item.name
                    aliases[local] = f"{resolved_module}.{item.name}"
    return aliases


def resolve_name(name: str, module: str, aliases: dict[str, str]) -> str:
    """Resolve one base/decorator name through imports and local classes."""
    head, separator, tail = name.partition(".")
    if head in aliases:
        resolved = aliases[head]
        return f"{resolved}.{tail}" if separator else resolved
    if separator:
        return name
    return f"{module}.{name}"


def has_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    expected: str,
    module: str,
    aliases: dict[str, str],
) -> bool:
    """Recognize a decorator by its resolved terminal symbol."""
    for decorator in node.decorator_list:
        name = dotted_name(decorator)
        if name is None:
            continue
        if resolve_name(name, module, aliases).rsplit(".", 1)[-1] == expected:
            return True
    return False


def build_symbol_index(sources: list[PythonSource]) -> dict[str, ClassSymbol]:
    """Build import-resolved class symbols for all parseable supplied modules."""
    symbols: dict[str, ClassSymbol] = {}
    for source in sources:
        try:
            tree = ast.parse(source.text)
        except SyntaxError:
            continue
        aliases = imported_names(tree, source.module)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            abstract_methods: list[str] = []
            abstract_properties: list[str] = []
            concrete_callables: list[str] = []
            member_lines: dict[str, int] = {}
            for member in node.body:
                if not isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                member_lines[member.name] = member.lineno
                abstract = has_decorator(
                    member, "abstractmethod", source.module, aliases
                )
                property_member = has_decorator(
                    member, "property", source.module, aliases
                )
                if abstract and property_member:
                    if member.name not in abstract_properties:
                        abstract_properties.append(member.name)
                elif abstract:
                    if member.name not in abstract_methods:
                        abstract_methods.append(member.name)
                else:
                    if member.name not in concrete_callables:
                        concrete_callables.append(member.name)
            bases = [
                resolve_name(name, source.module, aliases)
                for base in node.bases
                if (name := dotted_name(base)) is not None
            ]
            qualified = f"{source.module}.{node.name}"
            symbols[qualified] = ClassSymbol(
                qualified_name=qualified,
                module=source.module,
                name=node.name,
                path=source.path,
                line=node.lineno,
                bases=bases,
                abstract_methods=abstract_methods,
                abstract_properties=abstract_properties,
                concrete_callables=concrete_callables,
                member_lines=member_lines,
            )
    return symbols


def capability_names(symbols: dict[str, ClassSymbol]) -> set[str]:
    """Find direct and invalid inherited capability ABC declarations.

    A subclass that leaves one of its base capability's abstract operations
    unimplemented is still an ABC even when it does not repeat the
    ``@abstractmethod`` decorator.  The project index therefore computes the
    effective abstract member set instead of looking only at methods declared
    in the subclass body.
    """
    effective_cache: dict[str, set[str]] = {}

    def effective_abstracts(name: str, visiting: set[str] | None = None) -> set[str]:
        cached = effective_cache.get(name)  # lup: ignore[dict-get]
        if cached is not None:
            return cached
        if name not in symbols:
            return set()
        active = set() if visiting is None else set(visiting)
        if name in active:
            return set()
        active.add(name)
        symbol = symbols[name]
        inherited = {
            member
            for base in symbol.bases
            if base in symbols
            for member in effective_abstracts(base, active)
        }
        implemented = set(symbol.concrete_callables)
        declared = set(symbol.abstract_methods) | set(symbol.abstract_properties)
        result = (inherited - implemented) | declared
        effective_cache[name] = result
        return result

    capabilities = {
        name
        for name, symbol in symbols.items()
        if "abc.ABC" in symbol.bases or "ABC" in symbol.bases
    }
    changed = True
    while changed:
        inherited = {
            name
            for name, symbol in symbols.items()
            if any(base in capabilities for base in symbol.bases)
            and effective_abstracts(name)
        }
        expanded = capabilities | inherited
        changed = expanded != capabilities
        capabilities = expanded
    return capabilities


def architecture_violations(
    symbols: dict[str, ClassSymbol], capabilities: set[str]
) -> list[ArchitectureViolation]:
    """Evaluate every capability declaration and concrete implementation."""
    violations: list[ArchitectureViolation] = []  # lup: ignore[empty-collection]
    typing_bases = {"abc.ABC", "ABC", "typing.Generic", "Generic"}

    def is_implementation(name: str, seen: set[str] | None = None) -> bool:
        if name in capabilities or name not in symbols:
            return False
        visited = set() if seen is None else seen
        if name in visited:
            return False
        visited.add(name)
        return any(
            base in capabilities or is_implementation(base, visited)
            for base in symbols[name].bases
        )

    for name, symbol in symbols.items():
        if name in capabilities:
            method_count = len(symbol.abstract_methods)
            if method_count == 0 or method_count > 3:
                violations.append(
                    ArchitectureViolation(
                        path=symbol.path,
                        class_line=symbol.line,
                        line=symbol.line,
                        message=(
                            f"capability {symbol.name} has {method_count} abstract behavior "
                            "methods; expected one to three"
                        ),
                    )
                )
            for member in symbol.abstract_properties:
                violations.append(
                    ArchitectureViolation(
                        path=symbol.path,
                        class_line=symbol.line,
                        line=symbol.member_lines[member],
                        message=f"capability {symbol.name} declares abstract property {member}",
                    )
                )
            for member in symbol.concrete_callables:
                violations.append(
                    ArchitectureViolation(
                        path=symbol.path,
                        class_line=symbol.line,
                        line=symbol.member_lines[member],
                        message=f"capability {symbol.name} has concrete callable {member}",
                    )
                )
            capability_bases = [base for base in symbol.bases if base in capabilities]
            if capability_bases:
                violations.append(
                    ArchitectureViolation(
                        path=symbol.path,
                        class_line=symbol.line,
                        line=symbol.line,
                        message=(
                            f"capability {symbol.name} inherits capability "
                            f"{capability_bases[0].rsplit('.', 1)[-1]}"
                        ),
                    )
                )
            invalid_bases = [
                base
                for base in symbol.bases
                if base not in typing_bases and base not in capabilities
            ]
            if invalid_bases:
                violations.append(
                    ArchitectureViolation(
                        path=symbol.path,
                        class_line=symbol.line,
                        line=symbol.line,
                        message=f"capability {symbol.name} inherits reusable behavior",
                    )
                )
            continue

        direct_capabilities = [base for base in symbol.bases if base in capabilities]
        inherited_implementations = [
            base for base in symbol.bases if is_implementation(base)
        ]
        if len(direct_capabilities) > 1:
            violations.append(
                ArchitectureViolation(
                    path=symbol.path,
                    class_line=symbol.line,
                    line=symbol.line,
                    message=f"implementation {symbol.name} implements multiple capabilities",
                )
            )
        if direct_capabilities and len(symbol.bases) > 1:
            violations.append(
                ArchitectureViolation(
                    path=symbol.path,
                    class_line=symbol.line,
                    line=symbol.line,
                    message=f"implementation {symbol.name} inherits reusable behavior",
                )
            )
        if inherited_implementations:
            violations.append(
                ArchitectureViolation(
                    path=symbol.path,
                    class_line=symbol.line,
                    line=symbol.line,
                    message=f"implementation {symbol.name} inherits an implementation",
                )
            )
    return violations


def directives_for(source: PythonSource) -> list[Directive]:
    """Collect actual inline and file-level suppression comments."""
    context = PythonContext.parse(source.text)
    file_ignore = file_level_ignore(source.text)
    directives: list[Directive] = []  # lup: ignore[empty-collection]
    if file_ignore is not None:
        directives.append(
            Directive(
                path=source.path,
                line=file_ignore.line,
                rule_ids=file_ignore.rule_ids,
                file_level=True,
            )
        )
    for line_number, line in enumerate(source.text.splitlines(), start=1):
        if file_ignore is not None and line_number == file_ignore.line:
            continue
        match = IGNORE_RE.search(line)
        if match is None or not context.comment_at(line_number, match.start()):
            continue
        directives.append(
            Directive(
                path=source.path,
                line=line_number,
                rule_ids=ignore_rule_ids(match),
            )
        )
    return directives


def audit_capabilities(sources: list[PythonSource]) -> list[CapabilityFinding]:
    """Build the project index, enforce the rule, and audit its suppressions."""
    symbols = build_symbol_index(sources)
    violations = architecture_violations(symbols, capability_names(symbols))
    directives = [
        directive for source in sources for directive in directives_for(source)
    ]
    used: set[int] = set()
    untyped_reported: set[int] = set()
    findings: list[CapabilityFinding] = []  # lup: ignore[empty-collection]
    for violation in violations:
        candidates = [
            (index, directive)
            for index, directive in enumerate(directives)
            if directive.path == violation.path
            and (
                directive.file_level
                or directive.line in {violation.line, violation.class_line}
            )
            and (directive.rule_ids is None or RULE_ID in directive.rule_ids)
        ]
        if not candidates:
            findings.append(
                CapabilityFinding(
                    kind="missing",
                    path=violation.path,
                    line=violation.line,
                    message=violation.message,
                )
            )
            continue
        index, directive = candidates[0]
        used.add(index)
        if directive.rule_ids is None and index not in untyped_reported:
            findings.append(
                CapabilityFinding(
                    kind="untyped",
                    path=directive.path,
                    line=directive.line,
                    message=(
                        f"bare suppression covers {RULE_ID}; use "
                        f"# lup: ignore[{RULE_ID}] with a reason"
                    ),
                )
            )
            untyped_reported.add(index)
    for index, directive in enumerate(directives):
        if (
            index in used
            or directive.rule_ids is None
            or RULE_ID not in directive.rule_ids
        ):
            continue
        findings.append(
            CapabilityFinding(
                kind="spurious",
                path=directive.path,
                line=directive.line,
                message=f"suppression names {RULE_ID} but guards no violation",
            )
        )
    return sorted(
        findings, key=lambda item: (item.path.as_posix(), item.line, item.kind)
    )
