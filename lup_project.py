"""The repository as the second lup reads it: what its rooms need beyond the second lup's defaults.

The second lup judges this repository's sessions and builds their rooms until
the third lup runs its own (#13), and it reads this file as its declaration, in
its own grammar. The third lup's declaration is `lup_declaration.py`, which
takes this file's name at the switch.
"""

# lup: defer(issue=13, why="the second lup's declaration, in its grammar, until the third lup runs this repository's sessions and its own declaration takes this name")
from lup_dev import Module, Modules, Package, Packages, Project


class ShellRoom(Module):
    """What building the dashboard's page needs in a room: its package manager, and a browser to look at it with.

    - pnpm installs the page's packages from its lockfile, held to the package
      age its settings keep.
    - Chromium, driven headless, shows an agent the page they build; a virtual
      display and `xdotool` give a windowed Chromium real key events, which
      headless Chromium never sees.
    """

    name = "shell-room"
    packages: Packages = Packages.of(
        Package(
            name="pnpm", why="installs the dashboard page's packages from its lockfile"
        ),
        Package(name="chromium", why="shows an agent the dashboard's page they build"),
        Package(
            name="xorg-server-xvfb",
            why="`Xvfb`, a virtual display for a windowed Chromium to take key events",
        ),
        Package(
            name="xdotool",
            why="types into the virtual display as a keyboard does",
        ),
    )


project = Project(modules=Modules.default().add(ShellRoom()))
