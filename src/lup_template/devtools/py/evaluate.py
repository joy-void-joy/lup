"""Helpers for ``py eval`` — safe expression evaluation.

Named ``evaluate`` rather than ``eval`` to avoid shadowing the builtin.
"""

import ast
import importlib
import json
from pprint import pformat

# ---------------------------------------------------------------------------
# py eval — safe expression evaluation
# ---------------------------------------------------------------------------

BLOCKED_CALLS = frozenset(  # lup: ignore[frozenset-shape] — blocklist
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

BLOCKED_ATTRS = frozenset(  # lup: ignore[frozenset-shape] — blocklist
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

DANGEROUS_MODULES = frozenset(  # lup: ignore[frozenset-shape] — blocklist
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

SAFE_BUILTINS: dict[str, object] = {  # lup: ignore[dict-str-object] — live namespace
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
    "set": set,  # lup: ignore[set-shape] — the builtin itself
    "frozenset": frozenset,  # lup: ignore[frozenset-shape] — the builtin
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


def auto_import_namespace(
    tree: ast.Expression,
) -> dict[str, object]:  # lup: ignore[dict-str-object] — live namespace
    """Build a namespace by importing modules referenced in the expression."""
    namespace = dict(SAFE_BUILTINS)

    root_names: list[str] = []  # lup: ignore[empty-collection] — walk fold
    attr_nodes: list[ast.Attribute] = []  # lup: ignore[empty-collection] — walk fold
    for node in ast.walk(tree.body):
        if isinstance(node, ast.Name) and node.id not in namespace:
            root_names.append(node.id)
        elif isinstance(node, ast.Attribute):
            attr_nodes.append(node)

    for name in dict.fromkeys(root_names):
        if name in DANGEROUS_MODULES:
            continue
        try:
            namespace[name] = importlib.import_module(name)
        except ImportError:
            pass

    dotted_paths: list[str] = []  # lup: ignore[empty-collection] — chain fold
    for node in attr_nodes:
        chain: list[str] = []  # lup: ignore[empty-collection] — attr-chain walk
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and current.id in namespace:
            chain.append(current.id)
            chain.reverse()
            for i in range(2, len(chain) + 1):
                dotted_paths.append(".".join(chain[:i]))

    for dotted in sorted(dict.fromkeys(dotted_paths)):
        root, _, _ = dotted.partition(".")
        if root in DANGEROUS_MODULES:
            continue
        try:
            importlib.import_module(dotted)
        except ImportError:
            pass

    return namespace


def format_eval_result(result: object) -> str:  # lup: ignore[bare-object]
    containers = (dict, list, tuple, set, frozenset)  # lup: ignore[frozenset-shape]
    if isinstance(result, containers):
        try:
            return json.dumps(result, indent=2, default=repr)
        except (TypeError, ValueError):
            return pformat(result, width=100)
    return pformat(result, width=100)
