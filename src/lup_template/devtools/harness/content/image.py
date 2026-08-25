"""The container this repository's agent sessions run in.

Mechanism from the library, composition here, exactly as `requirements.py`
splits them: `lup.harness.image` says what an image declaration *is*, and what
is this project's is which defaults it takes and which it overrules.

It overrules none of them, and that is the finding rather than an omission. A
template whose every field had to be answered before anything worked would be
a template that decided nothing; the library's defaults are what this
repository actually wants, down to the base image, which was chosen so that
every package in this toolchain arrives signed.
"""

from lup.harness.image import Image


def agent_image() -> Image:
    """This repository's image, which is the library's offer taken whole.

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
    return Image()
