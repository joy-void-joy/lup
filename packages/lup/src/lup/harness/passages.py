"""Prose a content module authors as Markdown, in a file beside the module.

Where a skill's words used to live: inside an ``r\"\"\"…\"\"\"`` in Python, with
every path, count and description spliced in by f-string. Two things were
wrong with that, and only one of them is about readability.

The first is that an f-string has no choke point. A value entering prose that
way arrives however it was spelled, and a backtick closes the code span it
landed in, a newline ends the heading, a pipe breaks the table row — silently,
in a file nobody reads until a model does. Here every value is a node or a
part, rendered on the way in, so entering escaped is the only way to enter.

The second is that prose belongs in a file that is prose. Markdown beside the
module is edited as Markdown, diffed as Markdown, and carries no Python
escaping around what a reader is meant to see.

What a passage is *not* is a program. ``{%`` and ``{#`` are refused by
:func:`passage_text`, so a template can name a value and nothing else: prose
that varies by more than a value is two passages, or a declaration in Python
saying which one is read — where it is typed and reviewed.
"""

import importlib.util
from functools import cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from lup.types import StringMap

PASSAGE_SUFFIX = ".md"
"""What a passage file is named: its module's own stem, as Markdown."""


@cache
def environment() -> Environment:
    """The one environment every passage renders through.

    ``StrictUndefined`` is what makes a misspelled name a failure rather than
    a blank: generation runs inside `dev check`, so the name that never
    reached the context is reported where it was written instead of leaving a
    hole in a shipped prompt. Autoescaping is off because escaping here is a
    Markdown question, answered by the node that carries the value rather
    than by an HTML rule that would corrupt the prose around it.
    """
    return Environment(undefined=StrictUndefined, keep_trailing_newline=True)


def passage_path(module: str, name: str) -> Path:
    """Where the prose for one declaration is authored.

    Beside the module, under its own stem, so the two halves of a declaration
    are one file apart and neither is found without the other. A module
    declaring a second document names it.
    """
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise ValueError(f"no module {module} to read a passage beside")
    beside = Path(spec.origin)
    if not name:
        return beside.with_suffix(PASSAGE_SUFFIX)
    return beside.parent / f"{name}{PASSAGE_SUFFIX}"


@cache
def passage_text(module: str, name: str = "") -> str:
    """The Markdown authored for one declaration, refused where it holds logic.

    A statement or a comment tag would make the prose a program: what it says
    would depend on state no type checker reads and no reviewer sees rendered.
    Both are refused here rather than by a scan elsewhere, because this is the
    one place every passage passes through.
    """
    path = passage_path(module, name)
    text = path.read_text(encoding="utf-8")
    for tag in ("{%", "{#"):
        if tag in text:
            raise ValueError(
                f"{path} holds `{tag}`: a passage names values and nothing else. "
                "Prose that varies by more than a value is two passages, or a "
                "declaration in Python saying which one is read"
            )
    return text


def rendered(module: str, name: str, values: StringMap) -> str:
    """One passage with its values placed, each already spelled by its own kind.

    The values arrive rendered: a node has escaped itself and a part has been
    spelled in the vocabulary of the runtime reading it, so what happens here
    is placement and nothing else.
    """
    return environment().from_string(passage_text(module, name)).render(values)
