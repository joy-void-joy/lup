"""Behavior tests for `lup-devtools dev pr create`.

`gh pr create` has no --json flag; the command must parse the URL that
gh prints (last URL-like line) and derive the PR number from its final
path segment — no extra gh round-trip. These tests pin that contract
with a stubbed gh.
"""

import pytest

from lup_template.devtools.dev import pr


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        match args[:2]:
            case ("pr", "create"):
                assert "--json" not in args, "gh pr create has no --json flag"
                return (
                    "Creating pull request for feat in example/repo\n"
                    "https://github.com/example/repo/pull/123\n"
                )
            case _:
                raise AssertionError(f"unexpected gh call: {args}")


def test_create_parses_url_and_fetches_structured_data(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeGh()
    monkeypatch.setattr(pr, "gh", fake)

    pr.create(base="dev", title="t", body="b", as_json=True)

    assert len(fake.calls) == 1, "URL parsing must not need a second gh call"
    create_call = fake.calls[0]
    assert create_call[:2] == ("pr", "create")

    out = capsys.readouterr().out
    assert '"number": 123' in out
    assert "https://github.com/example/repo/pull/123" in out
