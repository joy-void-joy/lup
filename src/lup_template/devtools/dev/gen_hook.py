"""Generate the edit hook's anti-pattern mirror from the single source of truth.

`.claude/plugins/lup/hooks/scripts/auto_allow_edits.py` cannot import a package
on its per-edit hot path, so it carries an inline copy of the
`lup.review.antipatterns` tables. This module renders those copies straight from
the importable source and splices them back into the committed hook, so the
mirror is generated rather than hand-maintained and can never drift.

`lup-devtools dev gen-hook` writes the regenerated hook;
`tests/unit/test_antipatterns.py` pins the committed file equal to this output,
so an added or edited rule that was not regenerated fails the suite.

The rendered blocks are piped through `ruff format` so the committed file is
already canonical — the repo-wide `ruff format` check leaves it untouched and
the pin test reproduces it byte for byte.
"""

from pathlib import Path

import sh
import typer

from lup.review.antipatterns import PYTHON_ANTI_PATTERNS, TS_ANTI_PATTERNS, AntiPattern

HOOK_PATH = (
    Path(__file__).resolve().parents[4]
    / ".claude"
    / "plugins"
    / "lup"
    / "hooks"
    / "scripts"
    / "auto_allow_edits.py"
)

# The generated tuples store compiled patterns; the token is held as data so
# rendering the mirror never itself reads as a regex call.
COMPILE_CALL = "re.compile"

# The generated region of each table runs from its `NAME:` assignment header
# down to the closing bracket that sits alone in the first column.
BLOCK_CLOSE = "]"


def py_string(value: str) -> str:
    """Render one string as a Python literal — raw for regex patterns, repr otherwise.

    Regex sources read best as raw strings, and every pattern here is raw-safe
    (no embedded double quote or newline, no trailing backslash). Everything
    else falls back to ``repr``, which always yields a valid literal; the final
    `ruff format` pass then normalises the quote style.
    """
    raw_safe = (
        "\\" in value
        and '"' not in value
        and "\n" not in value
        and not value.endswith("\\")
    )
    if raw_safe:
        return f'r"{value}"'
    return repr(value)


def render_rule(ap: AntiPattern) -> str:
    """Render one :class:`AntiPattern` as an ``(id, re.compile(...), message)`` tuple."""
    return "\n".join(
        [
            "    (",
            f"        {py_string(ap.id)},",
            f"        {COMPILE_CALL}({py_string(ap.pattern.pattern)}),",
            f"        {py_string(ap.message)},",
            "    ),",
        ]
    )


def splice_block(
    lines: list[str], header: str, patterns: list[AntiPattern]
) -> list[str]:
    """Replace one table's body (between its header and closing bracket) with rendered rules.

    The header line and the closing bracket are kept verbatim, so the block's
    declared type annotation stays wherever it is authored in the hook.
    """
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == BLOCK_CLOSE)
    body = [render_rule(ap) for ap in patterns]
    return lines[: start + 1] + body + lines[end:]


def render_hook_text() -> str:
    """The full hook source with both anti-pattern tables regenerated and ruff-formatted."""
    lines = HOOK_PATH.read_text(encoding="utf-8").splitlines()
    lines = splice_block(lines, "ANTI_PATTERNS:", PYTHON_ANTI_PATTERNS)
    lines = splice_block(lines, "TS_ANTI_PATTERNS:", TS_ANTI_PATTERNS)
    spliced = "\n".join(lines) + "\n"
    formatted = sh.Command("ruff")(
        "format", "--stdin-filename", str(HOOK_PATH), "-", _in=spliced
    )
    return str(formatted)


def regenerate() -> None:
    """Write the regenerated mirror back into the committed hook file."""
    HOOK_PATH.write_text(render_hook_text(), encoding="utf-8")
    typer.echo(f"Regenerated anti-pattern mirror in {HOOK_PATH}")
