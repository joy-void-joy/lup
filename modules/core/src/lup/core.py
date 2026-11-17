"""`Core`: the module every project holds, which packages what every project has, and lists its submodules' promises."""

from lup.declaration.module import Module
from lup.declaration.profiles import DEFAULT, DirectoryName, Profile, Profiles
from lup.declaration.promises import DeclarationPromises, ProfilesPromises
from lup.doors.parts import Parts
from lup.doors.promises import DoorsPromises, PartsPromises
from lup.programs.promises import ProgramsPromises
from lup.running.promises import RunningPromises
from lup.shell.kinds import SHELL_FOLDS, SHELL_TONES, Folds, Tones
from lup.shell.promises import ShellPromises
from lup.testing.promises import TestingPromises


class Core(Module):
    """What every project has: loading the declaration, the doors its modules are reached through, checking their promises, running programs, and the shell's kinds; the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails. What it serves is its submodules' promises; what
    it declares, the shell's tones and fold kinds, which every module's views may
    name, and which a layer changes as any field.
    """

    name = "core"
    parts: Parts = Parts.of(
        DeclarationPromises,
        ProfilesPromises,
        DoorsPromises,
        PartsPromises,
        RunningPromises,
        TestingPromises,
        ShellPromises,
        ProgramsPromises,
    )
    tones: Tones = Tones.of(*SHELL_TONES)
    """The shell's tones: plain, muted, strong, and the operator's own words."""
    folds: Folds = Folds.of(*SHELL_FOLDS)
    """The shell's fold kinds: a party's section, a file, a body, a run of
    unchanged lines."""
    # lup: defer(issue=5, why="a session's start reads the profile it runs on and its account (`lup.declaration.profiles.chosen`), which lup's sessions bring")
    profiles: Profiles = Profiles.of(Profile(name=DEFAULT))
    """The profiles the repository's sessions may run on: lup's `default`, and
    those its layers add (`lup.declaration.profiles`)."""
    profile: DirectoryName = DEFAULT
    """The profile the repository's sessions run on, by its name, where a session
    is started naming none."""
