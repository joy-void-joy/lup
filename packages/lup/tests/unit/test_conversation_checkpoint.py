"""Conversation checkpoints respect the repository's ignore boundary."""

from pathlib import Path

import pytest

from lup.devtools.conversation import checkpoint


class IgnoringGit:
    """A Git surface reporting the retained path as ignored."""

    def out(self, *arguments: str, **_options: object) -> str:
        assert arguments[:2] == ("check-ignore", "--")
        return arguments[-1]

    def add(self, *_arguments: str, **_options: object) -> None:
        raise AssertionError("ignored data must not be force-added")


def test_an_ignored_destination_is_not_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "tmp" / "conversations" / "chatgpt" / "one"
    destination.mkdir(parents=True)
    monkeypatch.setattr(checkpoint, "git", IgnoringGit())

    revision = checkpoint.checkpoint_delivery(
        tmp_path, [destination], provider="chatgpt"
    )

    assert revision is None
