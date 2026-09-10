"""The gate type-checks against the environment `uv` runs it in.

`uv run` maintains whatever ``UV_PROJECT_ENVIRONMENT`` names, and the base
configuration names ``.venv`` beside the manifest, so a session redirecting
its environment had Pyright reading a stale ``.venv`` — or, in a fresh
worktree with none, the interpreter on ``PATH``, which happened to agree.
The temporary configuration the gate hands Pyright names `uv`'s environment,
resolved the way `uv` resolves it, and names nothing when the variable is
unset so the base's answer stands.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from lup.devtools.dev import check


@pytest.fixture
def handed_to_pyright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], dict[str, object]]:
    """Run the gate's type check with `uv` faked, and read what it configured.

    The configuration is a temporary file the gate unlinks on its way out, so
    the fake reads it at the moment Pyright would have.
    """
    configured: dict[str, object] = {}

    def capture(*arguments: str, **_options: str) -> None:
        if arguments[1:3] == ("pyright", "--project"):
            configured.update(
                json.loads(Path(arguments[3]).read_text(encoding="utf-8"))
            )

    monkeypatch.setattr(check, "uv", capture)
    monkeypatch.setattr(check, "project_root", lambda: tmp_path)

    def run() -> dict[str, object]:
        check.pyright_check([])
        return configured

    return run


def test_relative_environment_resolves_against_the_project(
    handed_to_pyright: Callable[[], dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".venv-contained")

    assert handed_to_pyright() == {
        "include": ["."],
        "exclude": [],
        "venvPath": str(tmp_path),
        "venv": ".venv-contained",
    }


def test_absolute_environment_is_named_where_it_is(
    handed_to_pyright: Callable[[], dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elsewhere = tmp_path / "shared" / "environments" / "lup"
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(elsewhere))

    configured = handed_to_pyright()

    assert configured["venvPath"] == str(elsewhere.parent)
    assert configured["venv"] == "lup"


def test_unset_leaves_the_base_answer_standing(
    handed_to_pyright: Callable[[], dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    assert handed_to_pyright() == {"include": ["."], "exclude": []}
