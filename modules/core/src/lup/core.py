"""`Core`: the module every project holds, which packages what every project has, and lists its submodules' promises."""

from pathlib import Path

from lup.command_line.promises import CommandLinePromises
from lup.declaration.module import Module
from lup.declaration.profiles import DEFAULT, DirectoryName, Profile, Profiles
from lup.declaration.promises import DeclarationPromises, ProfilesPromises
from lup.doors.parts import Parts
from lup.doors.promises import DoorsPromises, PartsPromises
from lup.inbox.part import Inboxes, Speaking
from lup.inbox.promises import InboxPromises
from lup.inbox.records import EDGES, NODES
from lup.programs.promises import ProgramsPromises
from lup.running.plan import CORE
from lup.running.promises import RunningPromises
from lup.runtimes.promises import RecordsPromises
from lup.setup.part import Setup
from lup.setup.promises import SetupPromises
from lup.shell.blocks import Viewing
from lup.shell.kinds import SHELL_FOLDS, SHELL_TONES, FoldKind, Folds, Tones
from lup.shell.pages import Dashboarding, Pages
from lup.shell.promises import PagesPromises, ShellPromises
from lup.store.promises import StorePromises
from lup.store.records import Recorded
from lup.testing.promises import TestingPromises
from lup.told.promises import GuidancePromises


class Core(Module):
    """What every project has: loading the declaration and its layers, the doors its modules are reached through, checking their promises, running programs, the shell's kinds, the inbox, rendering guidance, the command line, setting a repository up for lup, and the profiles its sessions run on; the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails. What it serves is its submodules' parts and
    promises, the inbox's among them; what it declares, the shell's tones and
    fold kinds, which every module's views may name, and which a layer changes
    as any field, and the kinds of record the inbox keeps in the store.
    """

    name = CORE
    parts: Parts = Parts.of(
        DeclarationPromises,
        ProfilesPromises,
        DoorsPromises,
        PartsPromises,
        RunningPromises,
        RecordsPromises,
        TestingPromises,
        ShellPromises,
        Pages,
        PagesPromises,
        StorePromises,
        Inboxes,
        Speaking,
        InboxPromises,
        ProgramsPromises,
        GuidancePromises,
        CommandLinePromises,
        Setup,
        SetupPromises,
    )
    tones: Tones = Tones.of(*SHELL_TONES)
    """The shell's tones: plain, muted, strong, and the operator's own words."""
    folds: Folds = Folds.of(
        *SHELL_FOLDS,
        FoldKind(
            name="concern",
            letter="c",
            called="concern",
            level=1,
            colour="cyan",
            outlined=True,
        ),
    )
    """The shell's fold kinds: a party's section, a file, a body, a run of
    unchanged lines; and the inbox's, a concern."""
    dashboard: Dashboarding = Dashboarding()
    """Whether the machine serves the dashboard, and on which port; read from
    the home repository's declaration with the machine's layer over it."""
    kinds: Recorded = Recorded.of(*NODES, *EDGES)
    """The kinds of record the core's submodules keep in the store: the inbox's."""
    document: Viewing | None = None
    """The view the dashboard's document is, its root: a view listing the
    parties, each a fold of the `party` kind whose content reads what's shown of
    it, of the module named; none where the home repository's declaration names
    none, and the machine's dashboard shows the inbox's parties of the home
    repository (`lup.environment.shell.hosted`)."""
    # lup: defer(issue=5, why="a session's start reads the profile it runs on and its account (`lup.declaration.profiles.chosen`), which lup's sessions bring")
    profiles: Profiles = Profiles.of(Profile(name=DEFAULT))
    """The profiles the repository's sessions may run on: lup's `default`, and
    those its layers add (`lup.declaration.profiles`)."""
    profile: DirectoryName = DEFAULT
    """The profile the repository's sessions run on, by its name, where a session
    is started naming none."""
    home: Path | None = None
    """The home repository, a worktree of it, whose approved commit's machine
    parts run on this machine: lup's own checkout, for whoever works on lup.
    Set in the machine's layer; none to run the installed `lup`'s own parts,
    as whoever only builds with lup does."""
