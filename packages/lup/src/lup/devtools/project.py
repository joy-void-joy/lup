"""What an application tells the shared development tooling about itself.

The commands under :mod:`lup.devtools` are workflow rather than domain: they
scan, check, and generate against whichever repository they are pointed at.
A few facts about that repository are not theirs to infer — the import root
the application publishes, which initialization renames, and the roots whose
contents answer to some purpose other than production. Reaching back for
those by name is what kept these commands in an application package; taking
them as a declaration is what lets any adopter supply its own.
"""

from pathlib import Path

from pydantic import BaseModel

from lup.codescan.boundaries import ApplicationRoots
from lup.codescan.common import AntiPattern, RuleSelection
from lup.devtools.subapps import SubAppSelection
from lup.harness.models import ContentSelection
from lup.policy.kernel.rows import PathRoleRow


class DevProject(BaseModel, frozen=True):
    """The repository facts shared development tooling cannot work out alone."""

    package: str
    """The import root this application publishes.

    Only the application knows it: initialization renames the package, so a
    value written down in the library would go on naming one that is gone
    and silently resolve nothing.
    """

    path_roles: list[PathRoleRow] = []
    """Roots whose contents are judged by a purpose other than production.

    A test root is judged by whether it exercises production rather than by
    production's own conventions, so a scan that read them all the same way
    would report a fixture as a defect.
    """

    rules: RuleSelection = RuleSelection()
    """Which of the library's scan rules this repository holds itself to.

    Carried here so the sweep reads the selection the edit hook was compiled
    with: an application declares it once on its ``HookSet`` and hands it
    over, the way it already hands over its path roles.
    """

    anti_patterns: list[AntiPattern] = []
    """Code shapes only this repository refuses, beside the library's own.

    Carried here for the reason the selection is: the sweep and the edit hook
    have to read one table. A rule declared on the ``HookSet`` and not handed
    over would be enforced on every edit and invisible to ``dev check``, which
    is the disagreement the selection already exists to prevent.
    """

    subapps: SubAppSelection = SubAppSelection()
    """Which of the library's sub-apps this repository's CLI serves."""

    content: ContentSelection = ContentSelection()
    """Which of the library's skills and agents this repository's plugin ships.

    Carried beside the other two because every one of them is the same kind of
    fact — something this repository declined that the library still ships —
    and the gate reports them together. A retirement nobody can see becomes
    permanent by default: the roster it was taken from goes on growing, and
    the project that opted out once never meets the decision again."""

    roots: ApplicationRoots = ApplicationRoots()
    """Where this application is allowed to name a concrete implementation.

    The seam guard reads it to tell a composition root — which may say
    ``ClaudeSpellings`` because choosing is its whole job — from a module
    that reached past the abstraction it was handed.
    """

    catalog: Path | None = None
    """Where this repository writes down what it settled about itself.

    Named rather than derived, because the layout is the application's and a
    library guessing at one would report the wrong file as unanswered.
    Declaring none is a real answer — a project curating its declarations by
    hand needs no surface over them — and the seam command says so rather
    than reading somewhere it was never pointed.
    """
