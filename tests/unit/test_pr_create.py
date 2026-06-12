"""Behavior tests for `lup-devtools dev pr create`.

`gh pr create` has no --json flag; the command must capture the URL that
gh prints and fetch structured data via `gh pr view --json`. These tests
pin that contract with a stubbed gh.
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
                return "https://github.com/example/repo/pull/123\n"
            case ("pr", "view"):
                return (
                    '{"number": 123, "url": "https://github.com/example/repo/pull/123"}'
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

    create_call = fake.calls[0]
    assert create_call[:2] == ("pr", "create")
    view_call = fake.calls[1]
    assert view_call[:2] == ("pr", "view")
    assert "https://github.com/example/repo/pull/123" in view_call

    out = capsys.readouterr().out
    assert '"number": 123' in out
