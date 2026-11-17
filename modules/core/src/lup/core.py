"""`Core`: the module every project holds, which packages what every project has, and lists its submodules' promises."""

from lup.declaration.module import Module
from lup.declaration.profiles import DEFAULT, DirectoryName, Profile, Profiles
from lup.declaration.promises import DeclarationPromises, ProfilesPromises
from lup.doors.promises import DoorsPromises
from lup.doors.serving import Serving
from lup.testing.promises import TestingPromises


class Core(Module):
    """What every project has: loading the declaration, the doors its modules are reached through, and checking their promises; the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails. What it serves is its submodules' promises.
    """

    name = "core"
    serving: Serving = Serving.of(
        DeclarationPromises, ProfilesPromises, DoorsPromises, TestingPromises
    )
    # lup: defer(issue=5, why="a session's start reads the profile it runs on and its account (`lup.declaration.profiles.chosen`), which lup's sessions bring")
    profiles: Profiles = Profiles.of(Profile(name=DEFAULT))
    """The profiles the repository's sessions may run on: lup's `default`, and
    those its layers add (`lup.declaration.profiles`)."""
    profile: DirectoryName = DEFAULT
    """The profile the repository's sessions run on, by its name, where a session
    is started naming none."""
