"""The console's sweep: what a person runs for a roster no server is up on.

Written against the roster this started from — every session that ever
joined reading as running — where nothing but a person's command could put
the record right, since the servers that would have swept it were gone.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lup.channels.models import utc_now
from lup.coordination.identity import member_ref, mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.coordination.roster import ActorJoined
from lup.devtools.coordination import app as coordination_app


def long_gone(root: Path, name: str) -> tuple[RepositoryPeers, str]:
    """One repository whose only session spoke an hour ago and never beat."""
    peers = RepositoryPeers(root)
    member = mint_member_id()
    peers.cohort.roster.stream.append(
        ActorJoined(
            actor=member_ref(member),
            task="working",
            worktree=str(root / "tree"),
            at=utc_now() - timedelta(hours=1),
        )
    )
    peers.names.rename(member, name)
    return peers, member


def test_a_dry_run_names_the_lapsed_and_retires_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coordination_app, "project_root", lambda: tmp_path)
    peers, member = long_gone(tmp_path, "stale")

    result = CliRunner().invoke(
        coordination_app.create_coordination_app(), ["sweep", "-n"]
    )

    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"stale — session:{member}#1 — unheard since ")
    assert result.output.endswith("would retire 1 session(s)\n")
    [recorded] = [one for one in peers.cohort.live() if one.actor.id == member]
    assert recorded.running


def test_a_sweep_retires_the_lapsed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coordination_app, "project_root", lambda: tmp_path)
    peers, member = long_gone(tmp_path, "stale")
    app = coordination_app.create_coordination_app()

    first = CliRunner().invoke(app, ["sweep"])
    second = CliRunner().invoke(app, ["sweep"])

    assert first.exit_code == 0, first.output
    assert first.output.endswith("retired 1 session(s)\n")
    assert second.output == "retired 0 session(s)\n"
    [recorded] = [one for one in peers.cohort.live() if one.actor.id == member]
    assert not recorded.running
    assert recorded.error.startswith("unheard since ")
