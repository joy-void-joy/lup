"""Every `gh` query the branch commands make names the repository it means.

`gh` infers its repository from the origin remote, and an SSH alias — a host
a checkout writes as `alias:owner/name.git` and only the caller's ssh config
can expand — is not a URL it can parse. :mod:`lup.devtools.dev.branches`
threads :func:`repository_arguments` through for exactly that reason;
:mod:`lup.devtools.dev.pr` did not, so `dev pr create` failed with "none of
the git remotes configured for this repository point to a known GitHub host"
against a checkout where `dev retire` worked. Both are swept here, because
which of the two a query lives in is not what decides whether it needs one.

Naming the repository is half of it. Once `--repo` is given, `gh pr create`
no longer takes the checkout as saying which branch the request comes from,
so the head has to be named too — which is why both are pinned together.
"""

import ast
from pathlib import Path
from types import ModuleType

import pytest

from lup.devtools.dev import branches, pr
from lup.devtools import utils


class Recorder:
    """A stand-in for the `gh` command that keeps the arguments it was given."""

    def __init__(self, output: str = "") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.output = output

    def __call__(self, *arguments: str) -> str:
        self.calls.append(arguments)
        return self.output

    def out(self, *arguments: str) -> str:
        return self(*arguments)


@pytest.fixture
def named(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    """A `gh` whose repository is readable, branch known, and API authenticated.

    The credential gate is answered here rather than left live because it asks
    the host's own `gh` login, which no `pr.gh` stand-in intercepts: left alone
    these pass on a machine somebody signed in on and fail on every other one,
    reporting where they ran rather than what they pin. That the gate refuses
    an unauthenticated session is :mod:`test_remote_auth`'s to say.
    """
    monkeypatch.setattr(utils, "repository_slug", lambda: "owner/name")
    monkeypatch.setattr(pr, "current_branch", lambda: "feat-thing")
    recorder = Recorder(output="https://github.com/owner/name/pull/7\n")
    monkeypatch.setattr(pr, "gh", recorder)
    monkeypatch.setattr(pr, "check_forge_api", lambda: True)
    return recorder


def test_a_created_request_names_the_repository_and_the_head(
    named: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    pr.create(base="dev", title="feat: thing", body="why", as_json=False)

    arguments = named.calls[0]
    assert "--repo" in arguments
    assert arguments[arguments.index("--repo") + 1] == "owner/name"
    assert arguments[arguments.index("--head") + 1] == "feat-thing"
    assert "7" in capsys.readouterr().out


def test_a_checkout_with_no_readable_forge_asks_for_nothing(
    named: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent slug withholds the flag rather than passing an empty one."""
    monkeypatch.setattr(utils, "repository_slug", lambda: "")

    pr.create(base="dev", title="feat: thing", body="why", as_json=False)

    assert "--repo" not in named.calls[0]


def gh_calls(module: Path) -> list[ast.Call]:
    """Every `gh(...)` and `gh.out(...)` call written in a module."""

    def is_gh(func: ast.expr) -> bool:
        match func:
            case ast.Name(id="gh"):
                return True
            case ast.Attribute(value=ast.Name(id="gh")):
                return True
            case _:
                return False

    return [
        node
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and is_gh(node.func)
    ]


def names_repository(call: ast.Call) -> bool:
    """Whether a call spreads :func:`repository_arguments` into its arguments."""
    return any(
        isinstance(argument, ast.Starred)
        and isinstance(argument.value, ast.Call)
        and isinstance(argument.value.func, ast.Name)
        and argument.value.func.id == "repository_arguments"
        for argument in call.args
    )


def test_the_sweep_can_tell_an_inferred_repository_from_a_named_one(
    tmp_path: Path,
) -> None:
    """The precondition the sweep needs, so the pin below cannot pass idly."""
    written = tmp_path / "sample.py"
    written.write_text(
        'gh.out("pr", "view", "--json", "state")\n'
        'gh("pr", "close", *repository_arguments())\n',
        encoding="utf-8",
    )

    inferred, named = gh_calls(written)

    assert not names_repository(inferred)
    assert names_repository(named)


@pytest.mark.parametrize("module", [pr, branches])
def test_every_query_the_pr_commands_make_names_their_repository(
    module: ModuleType,
) -> None:
    """Pinned across each module, so a call site added later cannot omit it.

    One call written without it is one command that works everywhere except
    the checkouts an alias describes, and the failure surfaces as gh's own
    message about remotes rather than as anything naming these commands.
    """
    source = Path(module.__file__ or "")
    calls = gh_calls(source)

    assert calls, f"no gh calls found in {module} — the sweep found nothing to pin"
    unnamed = [call.lineno for call in calls if not names_repository(call)]
    assert not unnamed, f"gh calls inferring their repository at {module}:{unnamed}"
