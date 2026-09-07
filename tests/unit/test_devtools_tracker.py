# lup: ignore[tuple-shape]
# The surface assertions compare a command's options as the fixed shape they are.
"""What `dev tracker` may do, held to exactly what it was granted.

This command runs inside `uv run lup-devtools`, which the permission policy
allows outright — so nothing downstream of it can put a question in front of
anybody. Its surface is therefore the whole of the boundary: three compensable
verbs, one listing, and no way to spell anything else through it.

A test over the wired CLI rather than over the functions beneath it, because
the hole this guards against is a later option, a passthrough, or a fourth
verb — none of which any unit test of the routing would notice.
"""

import pytest
import typer
from typer.testing import CliRunner

import lup.devtools.dev.issues as issues_mod
from lup_template.devtools.main import app

PLAIN_CONSOLE = {"FORCE_COLOR": None, "NO_COLOR": "1", "TERM": "dumb"}
runner = CliRunner(env=PLAIN_CONSOLE)

GRANTED = {"comment", "close", "reopen", "list"}
"""Every verb this command may grow without somebody deciding to widen it.

`comment`, `close` and `reopen` are the compensable band: each is restored by
a normal follow-up, which is what puts them in reach of a call nobody is
asked about. `list` reads a declaration already on disk. A verb that is not
one of these belongs to `gh`, where the policy asks.
"""


def tracker_app() -> typer.Typer:
    """The wired `dev tracker` group, found the way a caller reaches it."""
    dev = next(
        group.typer_instance
        for group in app.registered_groups
        if group.name == "dev" and group.typer_instance is not None
    )
    return next(
        group.typer_instance
        for group in dev.registered_groups
        if group.name == "tracker" and group.typer_instance is not None
    )


def test_the_surface_is_exactly_what_was_granted() -> None:
    """A fourth verb fails here rather than quietly widening an allowed lane.

    Measured as a set rather than a subset on purpose: `assert "api" not in`
    guards the hole somebody already thought of, and this guards the one they
    have not.
    """
    served = {
        command.name
        for command in tracker_app().registered_commands
        if command.name is not None
    }

    assert served == GRANTED
    # And no nested group, which is how a surface grows a second time.
    assert tracker_app().registered_groups == []


@pytest.mark.parametrize("verb", sorted(GRANTED - {"list"}))
def test_no_verb_takes_anything_but_its_own_words(verb: str) -> None:
    """No passthrough, no `--json`, no raw arguments reaching gh.

    Each verb takes an issue number and the two things that decide where it
    lands and what it says. An option outside that set is a way to spell
    something the three verbs do not name, which is the shape a hole takes
    when nobody adds a verb.
    """
    allowed = {"--body", "--comment", "--repo", "--help"}
    text = runner.invoke(app, ["dev", "tracker", verb, "--help"]).output
    offered = {word.strip(",") for word in text.split() if word.startswith("--")}

    assert offered <= allowed, offered
    for forbidden in ("--json", "--jq", "--field", "--raw-field", "--method"):
        assert forbidden not in text


def test_a_repository_nobody_declared_is_refused_with_the_way_to_reach_it() -> None:
    """The refusal is a redirection, so the command it names has to work.

    A denial whose escape hatch has gone stale is worse than one with none:
    it sends somebody to an invocation that no longer does what it says. The
    printed route is built from the same words the operation would have run,
    and this pins that it reaches the caller intact.
    """
    result = runner.invoke(
        app,
        ["dev", "tracker", "comment", "12", "--body", "look", "--repo", "other/repo"],
    )

    assert result.exit_code == 1
    assert "gh issue comment 12 --body look --repo other/repo" in result.output
    # What it says about itself: not ours, and not declared.
    assert "other/repo is neither" in result.output


def test_the_route_a_refusal_prints_is_the_one_the_command_would_have_run() -> None:
    """Spelled once and read twice, so the two cannot drift apart.

    The alternative — a refusal that rebuilds the invocation beside the one
    performed — goes stale the first time either moves, and nothing fails
    when it does.
    """
    performed = issues_mod.issue_arguments("close", 9, "no longer reproduces")
    routes = issues_mod.TrackerRoutes(own="acme/widget")

    with pytest.raises(RuntimeError) as refused:
        routes.chosen(performed, named="other/repo")

    assert "gh issue close 9 --comment 'no longer reproduces' --repo other/repo" in (
        str(refused.value)
    )


def test_this_project_declares_the_tracker_its_adopters_inherit() -> None:
    """The scaffold ships lup's tracker, and that is the point of shipping it.

    A project built on lup meets most of its friction in lup's machinery —
    the resolver, the permission policy, the sandbox — none of which is
    editable from the consuming tree. An adopter inheriting this declaration
    can report where the fix would be made; one that outgrows it replaces the
    entry, which the customization marker beside it says.
    """
    listed = runner.invoke(app, ["dev", "tracker", "list"]).output

    assert "joy-void-joy/lup" in listed
    assert "components: lup" in listed
