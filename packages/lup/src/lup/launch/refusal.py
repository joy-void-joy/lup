"""A launch that cannot open, in words the operator acts on.

The library composes a session and refuses one it cannot open safely; what a
refusal looks like to a person is the entry point's to decide. A command-line
launcher turns it into its own usage error, a program opening sessions in
process lets it propagate, and neither has to know the other exists.
"""


class LaunchRefused(ValueError):
    """A launch that cannot open, in words the operator acts on.

    The message is the whole finding: what was missing or wrong, and what to
    run or change before trying again. A ``ValueError`` because what refused
    is always something the launch was given -- a declaration, a mount, a
    login, a checkout -- rather than something the library got wrong.
    """
