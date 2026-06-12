"""Python introspection tools.

Vetted alternatives to ``python -c`` for package, type, and value exploration.

Examples::

    $ uv run lup-devtools py info claude_agent_sdk.types.ToolUseBlock
    $ uv run lup-devtools py info pydantic.BaseModel --schema
    $ uv run lup-devtools py source lup.mcp.lup_tool
    $ uv run lup-devtools py source claude_agent_sdk --tree
    $ uv run lup-devtools py eval "importlib.metadata.version('pydantic')"
    $ uv run lup-devtools py imports lup.mcp
    $ uv run lup-devtools py imports lup.mcp --reverse
    $ uv run lup-devtools py search ToolUseBlock
"""

import ast
import dataclasses
import enum
import functools
import importlib
import importlib.metadata
import importlib.util
import inspect
import json
import sys
import typing
from collections.abc import Callable
from pathlib import Path
from pprint import pformat
from typing import Annotated, cast

import typer
from pydantic import BaseModel

app = typer.Typer(no_args_is_help=True)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def resolve_object(path: str) -> tuple[object, str]:
    """Resolve a dotted or colon path to a Python object, returning (object, leaf_name).

    Accepts both ``module.sub.Object`` (dot form) and the entry-point
    ``module.sub:Object.attr`` (colon form, module left of the colon).
    """
    if ":" in path:
        module_path, _, attr_path = path.partition(":")
        attrs = [
            a for a in attr_path.split(".") if a
        ]  # claude: ignore — dotted attr path
        try:
            obj: object = importlib.import_module(module_path)
        except ImportError as e:
            raise ValueError(f"Could not import module '{module_path}': {e}") from e
        for attr in attrs:
            try:
                obj = getattr(obj, attr)
            except AttributeError as e:
                raise ValueError(f"'{module_path}' has no attribute '{attr}'") from e
        return obj, attrs[-1] if attrs else module_path.rsplit(".", 1)[-1]

    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        module_path = ".".join(parts[:i])
        try:
            obj = importlib.import_module(module_path)
            for attr in parts[i:]:
                obj = getattr(obj, attr)
            return obj, parts[-1]
        except ImportError, AttributeError:
            continue
    raise ValueError(f"Could not resolve: {path}")


def find_module_path(module_name: str) -> Path | None:
    """Find the file path for a module."""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin:
            return Path(spec.origin)
    except ImportError, ModuleNotFoundError, ValueError:
        pass
    try:
        mod = importlib.import_module(module_name)
        if hasattr(mod, "__file__") and mod.__file__:
            return Path(mod.__file__)
    except ImportError, ModuleNotFoundError:
        pass
    return None


def format_signature(obj: object, name: str) -> str:
    try:
        sig = inspect.signature(cast(Callable[..., object], obj))
        return f"{name}{sig}"
    except ValueError, TypeError:
        return name


def format_type(annotation: object) -> str:
    if annotation is inspect.Parameter.empty or annotation is None:
        return "?"
    if isinstance(annotation, type):
        return annotation.__qualname__
    s = str(annotation)
    for prefix in ("typing.", "typing_extensions."):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return s


def get_docstring(obj: object) -> str:
    doc = inspect.getdoc(obj)
    if not doc:
        return ""
    return doc.split("\n\n")[0]


def fail(msg: str) -> typing.NoReturn:
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)


@functools.cache
def find_project_root() -> Path | None:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


@functools.cache
def categorize_import(module_name: str) -> str:
    root = module_name.split(".")[0]
    if root in sys.stdlib_module_names:
        return "stdlib"
    path = find_module_path(root)
    if path is None:
        return "third-party"
    if "site-packages" in str(path):
        return "third-party"
    project_root = find_project_root()
    if project_root and str(path).startswith(str(project_root)):
        return "project"
    return "third-party"


# ---------------------------------------------------------------------------
# py info — unified introspection
# ---------------------------------------------------------------------------


def defined_in(mod: object, attr: str) -> bool:
    """Whether ``attr`` is defined in ``mod`` rather than imported into it.

    Classes and functions carry ``__module__`` pointing at their defining
    module — names imported from elsewhere are excluded. Imported submodules
    (whose own ``__name__`` differs) are excluded too. Plain values without a
    ``__module__`` (module-level constants assigned here) are kept.
    """
    obj = getattr(mod, attr)
    host = getattr(mod, "__name__", None)
    if inspect.ismodule(obj):
        return getattr(obj, "__name__", None) == host
    owner = getattr(obj, "__module__", None)
    if owner is None:
        return True
    return owner == host


def show_module(obj: object, path: str, private: bool) -> None:
    file_path = find_module_path(path)
    if file_path:
        typer.echo(f"File: {file_path}")

    version = getattr(obj, "__version__", None)
    if version:
        typer.echo(f"Version: {version}")

    doc = get_docstring(obj)
    if doc:
        typer.echo(f"\n{doc}")

    module_name = getattr(obj, "__name__", path)

    classes: list[str] = []
    functions: list[str] = []
    values: list[str] = []
    reexports: list[str] = []
    for name in sorted(dir(obj)):
        if name.startswith("_") and not private:
            continue
        if not private and not defined_in(obj, name):
            continue
        member = getattr(obj, name)
        if inspect.ismodule(member):
            continue
        is_class = inspect.isclass(member)
        is_function = inspect.isfunction(member) or inspect.isbuiltin(member)
        if is_class or is_function:
            origin = getattr(member, "__module__", None)
            if isinstance(origin, str) and origin != module_name:
                reexports.append(f"{name} (from {origin})")
            elif is_class:
                classes.append(name)
            else:
                functions.append(format_signature(member, name))
        else:
            values.append(f"{name}: {type(member).__name__}")

    if classes:
        typer.echo(f"\nClasses ({len(classes)}):")
        for c in classes:
            typer.echo(f"  {c}")
    if functions:
        typer.echo(f"\nFunctions ({len(functions)}):")
        for f in functions:
            typer.echo(f"  {f}")
    if values:
        typer.echo(f"\nValues ({len(values)}):")
        for v in values:
            typer.echo(f"  {v}")
    if reexports:
        typer.echo(f"\nRe-exports ({len(reexports)}, defined elsewhere):")
        for r in reexports:
            typer.echo(f"  {r}")


PYDANTIC_INTERNALS = frozenset(
    {
        "model_config",
        "model_fields",
        "model_computed_fields",
        "model_json_schema",
        "model_validate",
        "model_validate_json",
        "model_dump",
        "model_dump_json",
        "model_post_init",
        "model_rebuild",
        "model_copy",
        "model_construct",
        "model_fields_set",
        "model_extra",
        "model_parametrized_name",
    }
)


def show_class(cls: type, schema: bool, private: bool) -> None:
    try:
        source_file = inspect.getfile(cls)
        typer.echo(f"File: {source_file}")
    except TypeError:
        pass

    bases = [b.__qualname__ for b in cls.__mro__[1:] if b is not object]
    if bases:
        typer.echo(f"MRO: {' → '.join(bases)}")

    doc = get_docstring(cls)
    if doc:
        typer.echo(f"\n{doc}")

    is_pydantic = issubclass(cls, BaseModel)
    if is_pydantic:
        show_pydantic_fields(cast(type[BaseModel], cls), schema)

    if not is_pydantic:
        is_typed_dict = hasattr(cls, "__required_keys__") and hasattr(
            cls, "__optional_keys__"
        )
        if is_typed_dict:
            show_typed_dict_fields(cls)
        elif issubclass(cls, enum.Enum):
            show_enum_members(cast(type[enum.Enum], cls))
        elif dataclasses.is_dataclass(cls):
            show_dataclass_fields(cls)
        elif hasattr(cls, "__annotations__") and cls.__annotations__:
            typer.echo("\nAnnotations:")
            try:
                hints = typing.get_type_hints(cls)
            except NameError, AttributeError, TypeError, RecursionError:
                hints = dict(cls.__annotations__)
            for name, ann in hints.items():
                if name.startswith("_") and not private:
                    continue
                default = getattr(cls, name, inspect.Parameter.empty)
                if default is not inspect.Parameter.empty:
                    typer.echo(f"  {name}: {format_type(ann)} = {default!r}")
                else:
                    typer.echo(f"  {name}: {format_type(ann)}")

    show_methods_section(cls, private, exclude_pydantic=is_pydantic)


def show_pydantic_fields(cls: type, schema: bool) -> None:
    model_cls = cast(type[BaseModel], cls)

    if schema:
        typer.echo("\nJSON Schema:")
        try:
            typer.echo(json.dumps(model_cls.model_json_schema(), indent=2))
        except AttributeError, TypeError:
            typer.echo("  (cannot generate schema for this model)")
        return

    fields = model_cls.model_fields
    if fields:
        typer.echo(f"\nFields ({len(fields)}):")
        for name, field in fields.items():
            ann = format_type(field.annotation)
            parts = [f"  {name}: {ann}"]
            if not field.is_required():
                parts.append(f" = {field.default!r}")
            if field.description:
                parts.append(f"  — {field.description}")
            typer.echo("".join(parts))

    computed = model_cls.model_computed_fields
    if computed:
        typer.echo(f"\nComputed ({len(computed)}):")
        for name, field in computed.items():
            typer.echo(f"  {name}: {format_type(field.return_type)}")


def show_typed_dict_fields(cls: type) -> None:
    required: frozenset[str] = getattr(cls, "__required_keys__", frozenset())
    optional: frozenset[str] = getattr(cls, "__optional_keys__", frozenset())
    try:
        hints = typing.get_type_hints(cls)
    except NameError, AttributeError, TypeError, RecursionError:
        hints = dict(getattr(cls, "__annotations__", {}))

    typer.echo(f"\nFields ({len(hints)}):")
    for name, ann in hints.items():
        tag = "required" if name in required else "optional" if name in optional else ""
        suffix = f"  ({tag})" if tag else ""
        typer.echo(f"  {name}: {format_type(ann)}{suffix}")


def show_enum_members(cls: type[enum.Enum]) -> None:
    members = list(cls)
    typer.echo(f"\nMembers ({len(members)}):")
    for member in members:
        typer.echo(f"  {member.name} = {member.value!r}")


def show_dataclass_fields(cls: type) -> None:
    dc_fields = dataclasses.fields(cls)
    typer.echo(f"\nFields ({len(dc_fields)}):")
    for f in dc_fields:
        parts = [f"  {f.name}: {format_type(f.type)}"]
        if f.default is not dataclasses.MISSING:
            parts.append(f" = {f.default!r}")
        elif f.default_factory is not dataclasses.MISSING:
            factory_name = getattr(
                f.default_factory, "__name__", repr(f.default_factory)
            )
            parts.append(f" = {factory_name}()")
        typer.echo("".join(parts))


def show_methods_section(
    cls: type, private: bool, *, exclude_pydantic: bool = False
) -> None:
    methods: list[str] = []
    properties: list[str] = []
    for name in sorted(cls.__dict__):
        if name.startswith("_") and not private:
            continue
        if exclude_pydantic and name in PYDANTIC_INTERNALS:
            continue
        member = cls.__dict__[name]
        if isinstance(member, property):
            properties.append(name)
        elif callable(member):
            methods.append(format_signature(member, name))

    if properties:
        typer.echo(f"\nProperties ({len(properties)}):")
        for p in properties:
            typer.echo(f"  {p}")
    if methods:
        typer.echo(f"\nMethods ({len(methods)}):")
        for m in methods:
            typer.echo(f"  {m}")


def show_callable_info(obj: object, name: str) -> None:
    sig = format_signature(obj, name)
    typer.echo(f"\n{sig}")

    doc = get_docstring(obj)
    if doc:
        typer.echo(f"\n{doc}")

    callable_obj = cast(Callable[..., object], obj)
    try:
        source_file = inspect.getfile(callable_obj)
        _, start_lineno = inspect.getsourcelines(callable_obj)
        typer.echo(f"\nDefined at: {source_file}:{start_lineno}")
    except TypeError, OSError:
        pass


def show_value_info(obj: object) -> None:
    typer.echo(f"Type: {type(obj).__qualname__}")
    r = repr(obj)
    if len(r) > 500:
        r = r[:500] + "..."
    typer.echo(f"Value: {r}")

    doc = get_docstring(obj)
    if doc:
        typer.echo(f"\n{doc}")


@app.command("info")
def info_cmd(
    path: Annotated[
        str,
        typer.Argument(
            help="Dotted path: module, module.Class, module.func, module.CONST"
        ),
    ],
    schema: Annotated[
        bool,
        typer.Option("--schema", help="Show JSON schema (Pydantic models)"),
    ] = False,
    private: Annotated[
        bool,
        typer.Option("--private", "-p", help="Include private members"),
    ] = False,
) -> None:
    """Inspect a Python object — adapts to modules, classes, functions, values."""
    try:
        obj, name = resolve_object(path)
    except ValueError as e:
        fail(str(e))

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"  {path}")
    typer.echo(f"{'=' * 60}")

    if inspect.ismodule(obj):
        show_module(obj, path, private)
    elif isinstance(obj, type):
        show_class(obj, schema, private)
    elif callable(obj):
        show_callable_info(obj, name)
    else:
        show_value_info(obj)

    typer.echo()


# ---------------------------------------------------------------------------
# py source — view source code and package trees
# ---------------------------------------------------------------------------


def format_tree(root: Path, prefix: str = "") -> list[str]:
    """Build a tree display of Python files under a directory."""
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    dirs = [
        e
        for e in entries
        if e.is_dir() and not e.name.startswith(".") and e.name != "__pycache__"
    ]
    files = [e for e in entries if e.is_file() and e.suffix == ".py"]
    items: list[Path] = dirs + files
    lines: list[str] = []
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{prefix}{connector}{item.name}{suffix}")
        if item.is_dir():
            extension = "    " if is_last else "│   "
            lines.extend(format_tree(item, prefix + extension))
    return lines


@app.command("source")
def source_cmd(
    path: Annotated[
        str,
        typer.Argument(help="Dotted path: module, module.Class, or module.func"),
    ],
    tree: Annotated[
        bool,
        typer.Option("--tree", "-t", help="Show package file tree instead of source"),
    ] = False,
    lines: Annotated[
        int,
        typer.Option("--lines", "-n", help="Number of lines to show (0 = all)"),
    ] = 50,
    start: Annotated[
        int,
        typer.Option(
            "--start",
            "-s",
            help="Starting line (file line for modules, offset within the object)",
        ),
    ] = 1,
) -> None:
    """View source code for a Python object, or a package file tree with --tree."""
    if tree:
        file_path = find_module_path(path)
        if file_path is None:
            fail(f"Could not find module '{path}'")
        if file_path.name == "__init__.py":
            package_root = file_path.parent
        else:
            typer.echo(str(file_path))
            return
        typer.echo(f"{package_root.name}/")
        for line in format_tree(package_root):
            typer.echo(line)
        return

    try:
        obj, _ = resolve_object(path)
    except ValueError as e:
        fail(str(e))

    if inspect.ismodule(obj):
        file_path = find_module_path(path)
        if file_path is None or not file_path.exists():
            fail(f"No source file for '{path}'")
        typer.echo(f"# {file_path}")
        source_lines = file_path.read_text().splitlines()
        start_idx = max(0, start - 1)
        if lines > 0:
            selected = source_lines[start_idx : start_idx + lines]
        else:
            selected = source_lines[start_idx:]
        typer.echo(f"# Lines {start_idx + 1}–{start_idx + len(selected)}")
        typer.echo()
        for i, line in enumerate(selected, start=start_idx + 1):
            typer.echo(f"{i:4d}  {line}")
        return

    source_obj = cast(Callable[..., object], obj)
    try:
        source = inspect.getsource(source_obj)
        source_file = inspect.getfile(source_obj)
        _, start_lineno = inspect.getsourcelines(source_obj)
        typer.echo(f"# {source_file}:{start_lineno}")
    except (TypeError, OSError) as e:
        fail(f"Cannot get source for '{path}': {e}")

    obj_lines = source.splitlines()
    start_idx = max(0, start - 1)
    if lines > 0:
        selected = obj_lines[start_idx : start_idx + lines]
    else:
        selected = obj_lines[start_idx:]
    typer.echo(f"# {len(obj_lines)} lines")
    if len(selected) < len(obj_lines):
        first = start_lineno + start_idx
        last = first + len(selected) - 1
        typer.echo(f"# Showing lines {first}–{last} (--lines 0 for all)")
    typer.echo()
    for i, line in enumerate(selected, start=start_lineno + start_idx):
        typer.echo(f"{i:4d}  {line}")


# ---------------------------------------------------------------------------
# py eval — safe expression evaluation
# ---------------------------------------------------------------------------

BLOCKED_CALLS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "open",
        "breakpoint",
        "exit",
        "quit",
        "input",
        "__import__",
        "getattr",
        "hasattr",
        "vars",
    }
)

BLOCKED_ATTRS = frozenset(
    {
        "__builtins__",
        "__class__",
        "__subclasses__",
        "__globals__",
        "__code__",
        "__func__",
        "__self__",
        "__dict__",
        "__bases__",
        "__mro__",
        "__import__",
        "__loader__",
        "__spec__",
    }
)

DANGEROUS_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "signal",
        "ctypes",
        "socket",
        "http",
        "urllib",
        "pathlib",
        "multiprocessing",
        "threading",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
        "webbrowser",
        "tempfile",
        "glob",
        "io",
        "builtins",
    }
)

SAFE_BUILTINS: dict[str, object] = {
    "True": True,
    "False": False,
    "None": None,
    "dir": dir,
    "type": type,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "len": len,
    "callable": callable,
    "id": id,
    "hash": hash,
    "repr": repr,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "bytes": bytes,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
    "sorted": sorted,
    "reversed": reversed,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
    "print": print,
    "iter": iter,
    "next": next,
    "abs": abs,
    "round": round,
    "ord": ord,
    "chr": chr,
    "hex": hex,
    "bin": bin,
    "oct": oct,
}


def check_eval_safety(tree: ast.Expression) -> str | None:
    """Return an error message if the expression contains blocked patterns."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in BLOCKED_ATTRS:
            return f"Blocked attribute: .{node.attr}"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_CALLS:
                return f"Blocked call: {func.id}()"
            if isinstance(func, ast.Attribute) and func.attr in BLOCKED_CALLS:
                return f"Blocked call: .{func.attr}()"
    return None


def auto_import_namespace(tree: ast.Expression) -> dict[str, object]:
    """Build a namespace by importing modules referenced in the expression."""
    namespace = dict(SAFE_BUILTINS)

    root_names: set[str] = set()
    attr_nodes: list[ast.Attribute] = []
    for node in ast.walk(tree.body):
        if isinstance(node, ast.Name) and node.id not in namespace:
            root_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            attr_nodes.append(node)

    for name in root_names:
        if name in DANGEROUS_MODULES:
            continue
        try:
            namespace[name] = importlib.import_module(name)
        except ImportError:
            pass

    dotted_paths: set[str] = set()
    for node in attr_nodes:
        chain: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and current.id in namespace:
            chain.append(current.id)
            chain.reverse()
            for i in range(2, len(chain) + 1):
                dotted_paths.add(".".join(chain[:i]))

    for dotted in sorted(dotted_paths):
        root, _, _ = dotted.partition(".")
        if root in DANGEROUS_MODULES:
            continue
        try:
            importlib.import_module(dotted)
        except ImportError:
            pass

    return namespace


def format_eval_result(result: object) -> str:
    if isinstance(result, (dict, list, tuple, set, frozenset)):
        try:
            return json.dumps(result, indent=2, default=repr)
        except TypeError, ValueError:
            return pformat(result, width=100)
    return pformat(result, width=100)


@app.command("eval")
def eval_cmd(
    expression: Annotated[str, typer.Argument(help="Python expression to evaluate")],
) -> None:
    """Evaluate a Python expression with auto-imported modules.

    Only expressions are allowed (no statements). Dangerous calls like
    exec/eval/open are blocked. Modules referenced in the expression are
    imported automatically.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        fail(f"Invalid expression: {e}")

    problem = check_eval_safety(tree)
    if problem:
        fail(problem)

    namespace = auto_import_namespace(tree)

    try:
        code = compile(tree, "<eval>", "eval")
        result = eval(code, {"__builtins__": {}}, namespace)
    except (
        NameError,
        AttributeError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        ArithmeticError,
        RuntimeError,
        StopIteration,
        ImportError,
    ) as e:
        fail(f"{type(e).__name__}: {e}")

    typer.echo(format_eval_result(result))


# ---------------------------------------------------------------------------
# py imports — import graph exploration
# ---------------------------------------------------------------------------


class ImportEntry(typing.TypedDict):
    module: str
    names: list[str]
    category: str


def collect_imports_from_source(source: str) -> list[ImportEntry]:
    """Parse source and extract import statements."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    entries: list[ImportEntry] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                entries.append(
                    ImportEntry(
                        module=alias.name,
                        names=[],
                        category=categorize_import(alias.name),
                    )
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [alias.name for alias in node.names]
            entries.append(
                ImportEntry(
                    module=node.module,
                    names=names,
                    category=categorize_import(node.module),
                )
            )
    return entries


def format_import_entry(entry: ImportEntry) -> str:
    if entry["names"]:
        names = ", ".join(entry["names"])
        return f"from {entry['module']} import {names}"
    return f"import {entry['module']}"


def entry_matches_target(entry: ImportEntry, target: str) -> bool:
    module = entry["module"]
    if module == target or module.startswith(target + "."):
        return True
    if "." not in target:
        return False
    parent, _, leaf = target.rpartition(".")
    return leaf in entry["names"] and (
        module == parent or module.startswith(parent + ".")
    )


def find_reverse_imports(
    target_module: str, project_root: Path
) -> list[tuple[str, str]]:
    """Find project files that import the target module."""
    results: list[tuple[str, str]] = []
    search_dirs = [project_root / "src", project_root / "packages"]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for py_file in search_dir.rglob("*.py"):
            try:
                source = py_file.read_text()
            except OSError:
                continue

            for entry in collect_imports_from_source(source):
                if entry_matches_target(entry, target_module):
                    relative = py_file.relative_to(project_root)
                    results.append((str(relative), format_import_entry(entry)))
                    break

    return sorted(results)


@app.command("imports")
def imports_cmd(
    module: Annotated[str, typer.Argument(help="Module to analyze")],
    reverse: Annotated[
        bool,
        typer.Option("--reverse", "-r", help="Find what imports this module"),
    ] = False,
    depth: Annotated[
        int,
        typer.Option("--depth", "-d", help="Transitive import depth"),
    ] = 1,
) -> None:
    """Show what a module imports, or what imports it (--reverse)."""
    if reverse:
        root = find_project_root()
        if root is None:
            fail("Could not find project root (no pyproject.toml)")
        results = find_reverse_imports(module, root)
        if not results:
            typer.echo(f"No project files import '{module}'")
            return
        typer.echo(f"Files importing '{module}':\n")
        for file_path, import_line in results:
            typer.echo(f"  {file_path}")
            typer.echo(f"    {import_line}")
        return

    file_path = find_module_path(module)
    if file_path is None:
        fail(f"Could not find module '{module}'")
    if not file_path.exists():
        fail(f"Module file does not exist: {file_path}")

    seen: set[str] = set()
    current_modules = [module]

    for current_depth in range(1, depth + 1):
        next_modules: list[str] = []
        if current_depth > 1:
            typer.echo(f"\n--- Depth {current_depth} ---")

        all_entries: list[ImportEntry] = []
        for mod_name in current_modules:
            mod_path = find_module_path(mod_name)
            if mod_path is None or not mod_path.exists():
                continue
            try:
                source = mod_path.read_text()
            except OSError:
                continue
            all_entries.extend(collect_imports_from_source(source))

        grouped: dict[str, list[ImportEntry]] = {}
        for entry in all_entries:
            if entry["module"] in seen:
                continue
            seen.add(entry["module"])
            grouped.setdefault(entry["category"], []).append(entry)
            next_modules.append(entry["module"])

        for category in ("project", "third-party", "stdlib"):
            entries = grouped.get(category, [])
            if not entries:
                continue
            typer.echo(f"\n{category} ({len(entries)}):")
            for entry in sorted(entries, key=lambda e: e["module"]):
                typer.echo(f"  {format_import_entry(entry)}")

        current_modules = next_modules


# ---------------------------------------------------------------------------
# py search — find symbols across packages
# ---------------------------------------------------------------------------


class SearchMatch(typing.TypedDict):
    symbol: str
    kind: str
    import_path: str


def scan_module_symbols(module_name: str, pattern: str) -> list[SearchMatch]:
    """Import a module and search dir() for matching symbols."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError, AttributeError, TypeError, RuntimeError, OSError:
        return []

    pattern_lower = pattern.lower()
    matches: list[SearchMatch] = []

    for name in dir(mod):
        if name.startswith("_"):
            continue
        if pattern_lower not in name.lower():
            continue

        member = getattr(mod, name, None)
        if member is None:
            continue

        if inspect.isclass(member):
            kind = "class"
        elif inspect.isfunction(member) or inspect.isbuiltin(member):
            kind = "function"
        elif inspect.ismodule(member):
            continue
        else:
            kind = type(member).__name__

        matches.append(
            SearchMatch(symbol=name, kind=kind, import_path=f"{module_name}.{name}")
        )

    return matches


def get_top_level_packages() -> list[str]:
    """Get importable top-level package names from installed distributions."""
    try:
        mapping = importlib.metadata.packages_distributions()
        return sorted(mapping.keys())
    except AttributeError:
        pass

    packages: set[str] = set()
    for dist in importlib.metadata.distributions():
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for line in top_level.strip().splitlines():
                pkg = line.strip()
                if pkg and not pkg.startswith("_"):
                    packages.add(pkg)
        else:
            name = dist.metadata["Name"]
            if name:
                packages.add(name.replace("-", "_"))
    return sorted(packages)


@app.command("search")
def search_cmd(
    pattern: Annotated[str, typer.Argument(help="Symbol name to search for")],
    package: Annotated[
        list[str] | None,
        typer.Option("--package", "-P", help="Limit to specific packages"),
    ] = None,
) -> None:
    """Search for symbols across installed packages by name (case-insensitive)."""
    if package:
        packages = list(package)
    else:
        packages = get_top_level_packages()

    all_matches: list[SearchMatch] = []
    scanned = 0

    if not package:
        typer.echo(f"Scanning {len(packages)} installed packages...", err=True)

    for pkg in packages:
        scanned += 1
        all_matches.extend(scan_module_symbols(pkg, pattern))

    if not all_matches:
        typer.echo(f"No matches for '{pattern}' in {scanned} packages")
        return

    typer.echo(f"Matches for '{pattern}':\n")
    for match in sorted(all_matches, key=lambda m: m["import_path"]):
        typer.echo(f"  {match['kind']:10s}  {match['import_path']}")

    typer.echo(f"\n({len(all_matches)} matches in {scanned} packages)")
