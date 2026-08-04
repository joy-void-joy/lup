"""Compile one hook dispatcher per native runtime from type-checked source.

A dispatcher is the one artifact whose breakage is silent: a plugin host runs
it outside the workspace, so an unresolved name or a missing branch surfaces
as a permission decision that never happens, in a session that only sees the
tool go through. Shipping it as text would put the most safety-critical file
in the repository beyond every checker and leave each runtime holding its own
copy of the host-side half, so it is compiled instead — from
:mod:`lup.policy.assets.host`, which every runtime answers identically, plus
one :class:`DispatcherDeclaration` per runtime stating what genuinely differs.

Every field of that declaration is required, so a new axis — another routed
tool, another hook event, another failure shape — becomes a field no runtime
can be constructed without answering, the way a new prompt part becomes a
method no :class:`~lup.harness.contracts.NativeSpellings` can omit. Divergence
is a construction error rather than something a reviewer has to notice.

Compilation reads modules the workspace already type-checks and lints, selects
declared members from their syntax trees, and emits their exact source. It
never authors logic, so nothing reaches a generated script that pyright has
not read, and a traceback in a hook keeps the text a reviewer is looking at.
What the compiler owns is proof: that the script imports only what a bare
script beside its runtime can resolve, that neither half repeats the other,
and that the tools routed, events named, environment read, and failure taken
are the ones the declaration promised.
"""

import ast
from importlib import resources
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lup.harness.banner import REGENERATE_COMMAND, GeneratedBanner

SHARED_PACKAGE = "lup.policy"
SHARED_MEMBER = "host"
"""The half every runtime answers identically, compiled into both scripts."""

RUNTIME_MEMBER = "policy_dispatcher"
"""The half one adapter owns: its own words, and nothing another repeats."""

KERNEL_PACKAGE = "kernel"
DISPATCHER_STDLIB = (
    "json",
    "os",
    "sys",
    "pathlib",
)  # lup: ignore[library-default] — the stdlib a compiled dispatcher actually imports; widening it is the hazard the pin exists to prevent
"""The standard library a compiled dispatcher may reach.

Pinned rather than open: the script starts through a native CLI with
``python3``, outside Lup's import graph and any active virtual environment,
so a convenient project helper — or the ``lup`` package itself — would make
permissions disappear precisely where packaging differs.
"""

ROUTER = "dispatch"
ROUTER_SUBJECT = "name"
ENTRYPOINT = "main"
"""The router, the tool name it branches on, and the process entry point."""

EVENT_KEY = "hook_event_name"
EVENT_FIELD = "hookEventName"
"""How an arriving payload and a returned envelope each name a hook event."""

SHEBANG = "#!/usr/bin/env python3"
INVOCATION = 'if __name__ == "__main__":\n    main()'

DISPATCHER_SCRIPT = PurePath("policy.py")
"""The file this compiler emits, named to spell its banner as a comment."""

DispatcherFailure = Literal["conservative_ask", "stderr_exit"]
"""What a dispatcher does with input it cannot decide from.

``conservative_ask`` returns an approval question through the hook's own
decision channel; ``stderr_exit`` has no such channel and fails closed by
writing the reason to stderr and exiting non-zero.
"""


class DispatcherDeclaration(BaseModel):
    """Everything one native runtime spells differently from every other.

    Each field is required, so answering the whole set is what constructing a
    runtime means. Adding a field is how a new axis of divergence is opened,
    and both runtimes have to close it before the tree compiles again.
    """

    model_config = ConfigDict(frozen=True)

    runtime_name: str
    package: str
    managed_root_env: str
    relativizer: str
    routed_tools: list[str]
    hook_events: list[str]
    failure: DispatcherFailure
    runtime_modules: list[str]


class DispatcherImport(BaseModel):
    """One module a dispatcher half imports, with the names it takes."""

    model_config = ConfigDict(frozen=True)

    module: str
    names: list[str]


class SourceHalf(BaseModel):
    """One type-checked module the compiler reads rather than authors."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    module: str
    text: str
    tree: ast.Module


def source_half(package: str, member: str) -> SourceHalf:
    """Read and parse one dispatcher half from its owning package."""
    text = resources.files(package).joinpath(f"assets/{member}.py").read_text("utf-8")
    return SourceHalf(
        module=f"{package}.assets.{member}", text=text, tree=ast.parse(text)
    )


def import_statement(node: ast.stmt) -> list[DispatcherImport]:
    """Read one statement as the imports it performs, if it performs any."""
    match node:
        case ast.Import(names=names):
            return [DispatcherImport(module=alias.name, names=[]) for alias in names]
        case ast.ImportFrom(module=str(module), names=names):
            return [
                DispatcherImport(module=module, names=[alias.name for alias in names])
            ]
        case _:
            return []


def half_imports(half: SourceHalf) -> list[DispatcherImport]:
    """Every module one half imports, in source order."""
    return [item for node in half.tree.body for item in import_statement(node)]


def half_functions(half: SourceHalf) -> list[ast.FunctionDef]:
    """Every top-level function one half defines, in source order."""
    return [node for node in half.tree.body if isinstance(node, ast.FunctionDef)]


def function_source(half: SourceHalf, node: ast.FunctionDef) -> str:
    """The exact source of one function, comments and docstring intact."""
    segment = ast.get_source_segment(half.text, node)
    if segment is None:
        raise ValueError(f"{half.module} has no source for {node.name}")
    return segment


def named_function(half: SourceHalf, name: str) -> ast.FunctionDef | None:
    """The top-level function one half defines under this name, if any."""
    return next((node for node in half_functions(half) if node.name == name), None)


def string_constants(node: ast.AST) -> list[str]:
    """Every string literal beneath one node."""
    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def routed_tools(half: SourceHalf) -> list[str]:
    """Every native tool name the router branches on.

    Read from the syntax rather than trusted: a tool the declaration names
    but the router never reaches would otherwise be registered with the host
    and then silently fall through to the unclassified branch.
    """
    return sorted(
        {
            comparator.value
            for node in ast.walk(half.tree)
            if isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == ROUTER_SUBJECT
            for comparator in node.comparators
            if isinstance(comparator, ast.Constant)
            and isinstance(comparator.value, str)
        }
    )


def named_events(half: SourceHalf) -> list[str]:
    """Every hook event the runtime half branches on or answers as.

    Read from the syntax for the same reason the routed tools are: an event
    the script recognizes but nobody registered it for is a branch that never
    runs, and an event it answers as is what the host reads the reply under.
    """
    return sorted(
        {
            *[
                comparator.value
                for node in ast.walk(half.tree)
                if isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Subscript)
                and isinstance(node.left.slice, ast.Constant)
                and node.left.slice.value == EVENT_KEY
                for comparator in node.comparators
                if isinstance(comparator, ast.Constant)
                and isinstance(comparator.value, str)
            ],
            *[
                value.value
                for node in ast.walk(half.tree)
                if isinstance(node, ast.Dict)
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant)
                and key.value == EVENT_FIELD
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ],
        }
    )


def resolvable(module: str, declaration: DispatcherDeclaration) -> bool:
    """Whether a bare script beside its runtime can resolve this module."""
    return (
        module in DISPATCHER_STDLIB
        or module == SHARED_MEMBER
        or module == KERNEL_PACKAGE
        or module.startswith(f"{KERNEL_PACKAGE}.")
        or module in declaration.runtime_modules
    )


def breach(condition: bool, message: str) -> list[str]:
    """One breach or none, so a check reads as the condition it states."""
    return [message] if condition else []


def import_breaches(
    declaration: DispatcherDeclaration, shared: SourceHalf, runtime: SourceHalf
) -> list[str]:
    """Imports a compiled script could not resolve, or would arrive without.

    The shared half's own import block is not emitted — the runtime half's is,
    because that is the one a type checker read this dispatcher against — so
    every module and name the shared half stands on has to be in it.
    """
    imports = half_imports(runtime)
    carried = [item.module for item in imports]
    return [
        *[
            f"imports {item.module}, which a bare script cannot resolve"
            for item in imports
            if not resolvable(item.module, declaration)
        ],
        *[
            f"drops {item.module}, which the shared half needs"
            for item in half_imports(shared)
            if item.module not in carried
        ],
        *[
            f"drops {name} from {item.module}, which the shared half needs"
            for item in half_imports(shared)
            for name in item.names
            if not any(
                other.module == item.module and name in other.names for other in imports
            )
        ],
    ]


def sharing_breaches(shared: SourceHalf, runtime: SourceHalf) -> list[str]:
    """Places where the two halves overlap instead of composing."""
    offered = [node.name for node in half_functions(shared)]
    return [
        *[
            f"redefines {node.name}, which the shared half already answers"
            for node in half_functions(runtime)
            if node.name in offered
        ],
        *[
            f"takes {name} from {SHARED_MEMBER}, which does not offer it"
            for item in half_imports(runtime)
            if item.module == SHARED_MEMBER
            for name in item.names
            if name not in offered
        ],
    ]


def declaration_breaches(
    declaration: DispatcherDeclaration, shared: SourceHalf, runtime: SourceHalf
) -> list[str]:
    """Axes the declaration promised that the runtime half does not keep."""
    constants = string_constants(runtime.tree)
    entrypoint = named_function(runtime, ENTRYPOINT)
    closes = entrypoint is not None and any(
        isinstance(node, ast.Name) and node.id == "SystemExit"
        for node in ast.walk(entrypoint)
    )
    routed = routed_tools(runtime)
    declared = sorted(declaration.routed_tools)
    return [
        *breach(routed != declared, f"routes {routed}, not the declared {declared}"),
        *[
            f"names the {event} hook event it is not registered for"
            for event in named_events(runtime)
            if event not in declaration.hook_events
        ],
        *[
            f"declares {name} but defines no such function"
            for name in (declaration.relativizer, ROUTER, ENTRYPOINT)
            if named_function(runtime, name) is None
        ],
        *breach(
            declaration.managed_root_env not in constants,
            f"never reads {declaration.managed_root_env}",
        ),
        *breach(
            declaration.managed_root_env in string_constants(shared.tree),
            f"leaks {declaration.managed_root_env} into the shared half",
        ),
        *breach(
            closes != (declaration.failure == "stderr_exit"),
            f"does not fail the declared {declaration.failure} way",
        ),
    ]


def dispatcher_banner(declaration: DispatcherDeclaration) -> GeneratedBanner:
    """Name both halves one runtime's script is compiled from.

    The script is one file compiled from two sources, so a reader sent to
    either alone would edit the wrong half; the banner names them together.
    """
    return GeneratedBanner(
        source=(
            f"{SHARED_PACKAGE}.assets.{SHARED_MEMBER} and "
            f"{declaration.package}.assets.{RUNTIME_MEMBER}"
        ),
        command=REGENERATE_COMMAND,
    )


def compiled_docstring(declaration: DispatcherDeclaration) -> str:
    """Say what the compiled script is, leaving its provenance to the banner."""
    return (
        f'"""{declaration.runtime_name} hook dispatcher over the canonical '
        "semantic kernel.\n"
        "\n"
        "Runs as a bare script beside its own runtime directory, reaching only\n"
        "the standard library and the kernel copied beside it.\n"
        '"""'
    )


def runtime_prologue(half: SourceHalf) -> str:
    """The runtime half's imports, less the shared import the compiler links.

    The shared half arrives as source rather than as a module beside the
    script, so the import that let a type checker read this half against it
    has nothing left to resolve once both are one file.
    """
    docstring = half.tree.body[0]
    opening = half_functions(half)[0].lineno
    linked = [
        number
        for node in half.tree.body
        if isinstance(node, ast.ImportFrom) and node.module == SHARED_MEMBER
        for number in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    ]
    kept = [
        line
        for number, line in enumerate(half.text.splitlines(), start=1)
        if (docstring.end_lineno or 0) < number < opening and number not in linked
    ]
    return "\n".join(kept).strip()


def compile_dispatcher(declaration: DispatcherDeclaration) -> str:
    """Compile one runtime's hook dispatcher, or refuse to ship a broken one.

    Refusal is the point of the return type being a string rather than a
    report: a dispatcher that cannot be proven is not a weaker dispatcher, it
    is a session running without a permission boundary, so generation stops.
    """
    shared = source_half(SHARED_PACKAGE, SHARED_MEMBER)
    runtime = source_half(declaration.package, RUNTIME_MEMBER)
    breaches = [
        *import_breaches(declaration, shared, runtime),
        *sharing_breaches(shared, runtime),
        *declaration_breaches(declaration, shared, runtime),
    ]
    if breaches:
        raise ValueError(f"{runtime.module} " + "; ".join(breaches))
    header = "\n".join([SHEBANG, compiled_docstring(declaration)])
    blocks = [
        f"{header}\n\n{runtime_prologue(runtime)}",
        *[function_source(shared, node) for node in half_functions(shared)],
        *[function_source(runtime, node) for node in half_functions(runtime)],
        INVOCATION,
    ]
    script = "\n\n\n".join(blocks) + "\n"
    return dispatcher_banner(declaration).applied_to(DISPATCHER_SCRIPT, script)
