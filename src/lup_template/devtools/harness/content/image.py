"""The container this repository's agent sessions run in.

Mechanism from the library, composition here, exactly as `requirements.py`
splits them: `lup.harness.image` says what an image declaration *is*, and what
is this project's is which defaults it takes and which it overrules.

It overrules one, and the one it overrules is the network. The library defaults
to a filtered proxy because an adopter's first session should not reach
whatever is on their network before anybody has decided it may. This repository
has decided. That filter admits every public destination already, so it never
stood between a session and the internet; what it stood between was a session
and this machine's own loopback, and the price was that HTTP was the only
transport crossing it -- which is what rewrites every ssh remote, and what
leaves a sign-in redirecting to a port no browser on this machine can reach.
Sharing the namespace hands both back and gives up the denial of the LAN, which
is a trade about who runs this repository and on what, so it is made here
rather than in a library with no way to know either.
"""

from lup.harness.egress import SessionEgress
from lup.harness.image import Image


def agent_image() -> Image:
    """This repository's image: the library's offer, on this machine's network.

    A function rather than the model itself, so a project that later needs to
    resolve something against its own checkout has somewhere to do it without
    changing what the catalog calls.

    Notably *not* a place to enumerate the worktrees under `tree/`. That was
    tried: `trusted_projects` filled with thirty-one directory names, several
    of which were not checkouts, and the resulting image carried one host's
    filesystem layout and rebuilt a layer whenever a worktree came or went.
    Trust belongs to the checkout a container is started against, which the
    entrypoint knows and a build cannot.
    """
    return Image(egress=SessionEgress(mode="host"))
