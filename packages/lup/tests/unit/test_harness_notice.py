"""What a launch line looks like, and what decides it.

A session's opening is a block of thirty lines in one weight, and the sentence
that decides whether the session can work sits somewhere inside it. These hold
the two properties that make the block readable: urgency travels with the
sentence rather than being chosen at the print, and the colour is the
terminal's alone -- a redirected launch records the same words with nothing in
them.
"""

from lup.harness.notice import Ink, Notice, Palette
from lup.harness.requirements import LostCapability, RefusedLaunch, Requirement, Run


def probe(refuses: bool) -> Requirement:
    """A requirement whose absence either stops a launch or merely costs it."""
    return Requirement(
        capability="probe",
        purpose="something worth having",
        exercise=Run(command=["definitely-not-a-program-on-this-host"]),
        absence=(
            RefusedLaunch(because="nothing works without it")
            if refuses
            else LostCapability(capability="one convenience")
        ),
    )


def test_a_refusal_and_a_cost_do_not_read_alike() -> None:
    """They were the same sentence on screen, which is the whole complaint.

    A capability whose absence stops the launch and one whose absence costs a
    convenience are different news, and a reader skimming an opening block has
    only the weight of the line to tell them apart.
    """
    stopping = probe(refuses=True).check({}).notices()[0]
    costing = probe(refuses=False).check({}).notices()[0]

    assert stopping.urgency == "refusal"
    assert costing.urgency == "warning"


def test_a_working_requirement_is_the_thing_the_others_stand_out_from() -> None:
    """Colouring only the alarms leaves them nothing to be an exception to."""
    working = Requirement(
        capability="probe",
        purpose="something worth having",
        exercise=Run(command=["echo", "ok"]),
        absence=LostCapability(capability="one convenience"),
    )

    assert working.check({}).notices()[0].urgency == "ready"


def test_a_cause_stays_subordinate_to_the_verdict_it_explains() -> None:
    """Read at full weight, a three-line finding becomes three findings."""
    notices = probe(refuses=True).check({}).notices()

    assert notices[0].indent == 0
    assert all(item.indent == 1 for item in notices[1:])


def test_the_reason_a_thing_was_needed_is_never_itself_alarming() -> None:
    """It is context for the line above, and competes with it when painted."""
    assert probe(refuses=True).check({}).notices()[-1].urgency == "detail"


def test_an_ink_says_only_what_it_asks_for() -> None:
    """`False` is the turn-it-off instruction, not the absence of one.

    Passing it emitted two redundant resets on every plain line, which
    renders identically and doubles the noise in anything that reads the
    escapes back.
    """
    painted = Ink(colour="green").paint("working")

    assert painted.count("\x1b[") == 2
    assert "\x1b[32m" in painted


def test_the_warning_colour_is_one_no_ansi_name_offers() -> None:
    """Orange is the shade a warning wants, and it is a 256-colour index."""
    assert "\x1b[38;5;208m" in Palette().warning.paint("no token")


def test_a_palette_is_a_default_rather_than_a_fixture() -> None:
    """Someone else's terminal is not this code's to decide."""
    theirs = Palette(warning=Ink(colour="yellow"))

    assert "\x1b[33m" in Notice(text="careful", urgency="warning").painted(theirs)


def test_indentation_survives_a_terminal_that_takes_no_colour() -> None:
    """The shape of the block is structure, not styling."""
    assert Notice(text="cause", indent=2).painted().endswith("cause\x1b[0m")
    assert Notice(text="cause", indent=2).painted().startswith("        ")
