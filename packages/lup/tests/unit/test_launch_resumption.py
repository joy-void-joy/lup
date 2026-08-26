"""Reopening an earlier session, in each runtime's own spelling.

The policy a session enforces is compiled into a plugin tree its runtime
loads at startup, so widening that policy takes effect only on a new
process — and a new process started from nothing loses the conversation
that established what the widening was for. Reopening is what closes that
loop, which is why the request is one declaration and only the words differ.
"""

import pytest
import typer

from lup.devtools.harness.launch import (
    claude_resume_arguments,
    codex_resume_arguments,
)
from lup.harness.models import Resumption


def test_a_launch_that_reopens_nothing_adds_no_words() -> None:
    """The default is the ordinary launch, on both runtimes."""
    plain = Resumption()

    assert plain.wanted() is False
    assert claude_resume_arguments(plain) == []
    assert codex_resume_arguments(plain) == []


@pytest.mark.parametrize(
    ("resume", "claude", "codex"),
    [
        (Resumption(latest=True), ["--continue"], ["resume", "--last"]),
        (Resumption(pick=True), ["--resume"], ["resume"]),
        (Resumption(session="abc123"), ["--resume", "abc123"], ["resume", "abc123"]),
    ],
)
def test_each_runtime_spells_the_same_request_its_own_way(
    resume: Resumption, claude: list[str], codex: list[str]
) -> None:
    """One request, two vocabularies — a flag on one, a subcommand on the other.

    The shapes are genuinely different rather than differently named: a
    subcommand has to lead the vector where a flag does not, which is the
    whole reason the words are built per runtime and the request is not.
    """
    assert resume.wanted() is True
    assert claude_resume_arguments(resume) == claude
    assert codex_resume_arguments(resume) == codex


def test_naming_two_sessions_at_once_is_refused_rather_than_ranked() -> None:
    """A launch reopens one session, and picking for the operator would guess."""
    both = Resumption(latest=True, session="abc123")

    complaint = both.contradicted()

    assert complaint is not None
    assert "--continue" in complaint
    assert "--session" in complaint


def test_one_named_session_is_not_a_contradiction() -> None:
    for resume in (
        Resumption(),
        Resumption(latest=True),
        Resumption(pick=True),
        Resumption(session="abc123"),
    ):
        assert resume.contradicted() is None, resume


def test_a_contradicted_request_never_reaches_a_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refused before generation, on both launchers.

    Ahead of ``ready_to_open`` rather than after it, because a launch that
    cannot happen should not first rewrite the tree it was going to open.
    """
    from lup.devtools.harness import launch

    def unreachable(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("a contradicted launch generated artifacts")

    monkeypatch.setattr(launch, "ready_to_open", unreachable)
    contradicted = Resumption(pick=True, session="abc123")

    with pytest.raises(typer.BadParameter):
        launch.launch_claude(
            composition=None,  # type: ignore[arg-type]
            extra_args=[],
            profiles=None,  # type: ignore[arg-type]
            profile=None,
            model=None,
            generate_only=False,
            resume=contradicted,
        )

    with pytest.raises(typer.BadParameter):
        launch.launch_codex(
            composition=None,  # type: ignore[arg-type]
            extra_args=[],
            codex_home=None,
            profile=None,
            model=None,
            generate_only=False,
            force_install=False,
            resume=contradicted,
        )


def test_a_relaxed_launch_says_what_it_retired_and_what_it_did_not(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The launch is the only moment a relaxation is legible.

    The tree it compiles carries no rules, so nothing downstream can report
    their absence: a session opened under it meets no rule and cannot tell
    that from a repository with none. Two consequences ride along because
    both bite later and neither announces itself — the sweep still holds the
    repository to every rule, and the committed tree has just been rewritten.
    """
    from lup.harness.codescan.common import RuleSelection
    from lup.devtools.harness.launch import announce_relaxed_rules
    from lup.harness.models import HookSet, Plugin

    plugin = Plugin(
        id="plugin.lup",
        name="lup",
        description="a plugin",
        version="0.0.0",
        marketplace="lup",
        skills=[],
        agents=[],
        hooks=HookSet(
            id="hooks.lup",
            policy_ids=["edit"],
            rules=RuleSelection(retired=["dict-get", "own-model-dispatch"]),
        ),
    )

    announce_relaxed_rules(False, plugin)
    assert capsys.readouterr().out == ""

    announce_relaxed_rules(True, plugin)
    said = capsys.readouterr().out
    assert "retired for this session: 2 rules" in said
    assert "dev check --antipatterns` still holds this repository" in said
    assert "before committing" in said
    assert "dev seams --retire-all" in said


def test_every_rule_retired_names_them_rather_than_standing_for_them() -> None:
    """The selection is subtractive, so "all of them" is spelled as all of them.

    A rule the library adds later is then one this selection has visibly not
    answered for, rather than one a flag silently swallowed.
    """
    from lup.harness.codescan.registry import all_rules, every_rule_retired

    retired = every_rule_retired()

    assert len(retired.retired) == len(all_rules())
    assert retired.retired
    assert not any(retired.keeps(rule.id) for rule in all_rules())
