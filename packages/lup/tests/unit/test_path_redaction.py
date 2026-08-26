"""Rewriting a machine's directories out of a record that will be kept."""

from pathlib import Path

from lup.observability.audit import (
    KeyRedaction,
    PathRedaction,
    PortableRoot,
    Redactions,
)


def redaction() -> PathRedaction:
    """A home with a checkout inside it, which is the arrangement that matters."""
    return PathRedaction(
        [
            PortableRoot(label="<home>", path=Path("/home/someone")),
            PortableRoot(label="<project>", path=Path("/home/someone/work/repo")),
        ]
    )


def test_rewrites_a_path_standing_alone() -> None:
    assert redaction().rewrite("/home/someone/work/repo/src/a.py") == (
        "<project>/src/a.py"
    )


def test_rewrites_a_path_quoted_inside_prose() -> None:
    """The case a path-typed field would miss: a path is one word of a sentence."""
    message = "No such file: '/home/someone/.cache/thing' (while loading)"
    assert (
        redaction().rewrite(message)
        == "No such file: '<home>/.cache/thing' (while loading)"
    )


def test_nested_root_wins_over_the_one_enclosing_it() -> None:
    """Longest first, so a checkout is a checkout and not a folder in a home."""
    rewritten = redaction().rewrite("/home/someone/work/repo/x")
    assert rewritten.startswith("<project>")


def test_walks_into_containers_and_keys() -> None:
    payload = {
        "/home/someone/key": ["/home/someone/a", {"b": "/home/someone/work/repo/c"}],
        "untouched": 3,
    }
    assert redaction().apply(payload) == {
        "<home>/key": ["<home>/a", {"b": "<project>/c"}],
        "untouched": 3,
    }


def test_composes_after_the_key_rule_without_reviving_a_secret() -> None:
    """A redacted value stays redacted: the path rule must not undo the key rule."""
    rule = Redactions(KeyRedaction(), redaction())
    assert rule.apply({"api_key": "/home/someone/token", "cwd": "/home/someone"}) == {
        "api_key": "[REDACTED]",
        "cwd": "<home>",
    }


def test_leaves_a_path_naming_no_declared_root_alone() -> None:
    assert redaction().rewrite("/usr/lib/python3.14/json") == "/usr/lib/python3.14/json"
