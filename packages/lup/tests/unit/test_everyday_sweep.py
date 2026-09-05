"""The one measurement of the vocabulary that reads a tightening.

Everything else about the shell table is measured in the direction a rule
*loosening* shows up in: the recorded asks list commands a question was raised
about, and the rule census lists what each row earns. Neither notices a
de-escalation that stopped firing, so a change putting a question in front of
`git status` passes both and reaches somebody's session instead.

What is pinned here is the sweep's own behaviour rather than the corpus. The
corpus is checked against the live table by `dev check`, where it belongs; a
test asserting the same thing would be the same measurement paid for twice,
and would fail in the same commit for the same reason.
"""

from lup.devtools.hooks.classify import stopped_everyday
from lup.harness.models import HookSet
from lup.policy.everyday import SESSION_SHAPES, CommandFamily, everyday_commands

UNCLASSIFIED = HookSet(
    id="test",
    policy_ids=["shell"],
    everyday_commands=[
        CommandFamily(
            what="asking git what happened", commands=["git status", "git diff"]
        ),
        CommandFamily(
            what="something nobody classified", commands=["definitely-not-a-tool"]
        ),
    ],
)
"""A corpus holding one command no table answers for, and two it allows."""

REFUSED = HookSet(
    id="test",
    policy_ids=["shell"],
    everyday_commands=[
        CommandFamily(
            what="a spelling no posture allows", commands=["python -c 'print(1)'"]
        )
    ],
)
"""A corpus holding one command refused for its shape rather than for its risk.

An unclassified command will not serve here. Inside a containment boundary it
is allowed — every effect it can have is confined there — which is the right
answer and a useless probe for asking whether all four postures were swept.
"""


def test_a_stopped_command_is_reported_under_the_family_that_claimed_it() -> None:
    """The family is the claim, so a finding that dropped it says nothing.

    A reader shown `git diff --stat` alone has to reconstruct why it mattered
    before they can weigh whether the rule that stopped it was right to. Shown
    it under "asking git what happened", they are told what broke.
    """
    stopped = stopped_everyday(UNCLASSIFIED, shapes=SESSION_SHAPES[:1])

    assert [item.command for item in stopped] == ["definitely-not-a-tool"]
    assert stopped[0].what == "something nobody classified"
    assert stopped[0].effect != "allow"
    assert stopped[0].reason


def test_the_corpus_is_swept_in_every_posture_a_session_runs_in() -> None:
    """A verdict is reached for somebody, so the claim has to say for whom.

    One posture was swept — interactive, uncontained, with a person there to
    answer — and the others reach different rows: a worker session has nobody
    to ask, so a rule that starts asking stops it rather than interrupting
    it. A tightening visible only there was invisible to every reading.
    """
    stopped = stopped_everyday(REFUSED)

    assert [item.shape for item in stopped] == [shape.what for shape in SESSION_SHAPES]


def test_declaring_no_corpus_asserts_nothing() -> None:
    """An empty declaration is silence, never a passing measurement.

    The library offers the families; a project that declared none has simply
    not made this claim, and the sweep has to read that as nothing to check
    rather than as everything checked.
    """
    assert stopped_everyday(HookSet(id="test", policy_ids=["shell"])) == []


def test_every_offered_family_carries_commands() -> None:
    """A family with nothing in it is a claim that reads as made and is not.

    The failure this guards is the quiet one: a project overriding a family
    with an empty sequence keeps its name in the report and its count in the
    total, and the sweep goes on passing over commands nobody swept.
    """
    for family in everyday_commands():
        assert family.commands, family.what
