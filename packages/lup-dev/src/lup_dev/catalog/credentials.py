"""What lup's default lets the host do with the operator's credentials, and the refs no push updates.

`Core`'s `credentials` reads these (`lup_dev.declaration.kinds`, `Credentials`;
`docs/host-tools.md`, *What the declaration allows*). Its actions are every one
lup carries out but those withheld here, each with its reason, as
`lup_dev.catalog.rules` leaves rules out: so an action a later release adds is
allowed unless it's withheld here too, and a project allows one back with
`Actions().add(…)`.
"""

from lup.types import Model


class Withheld(Model):
    """An action lup's default doesn't allow, and why."""

    action: str
    """The action's name, as `Actions` names it."""
    why: str
    """Why the host doesn't do it unasked in every project, for each to allow."""


class CredentialDefaults(Model):
    """What the host does with the operator's credentials unless the project says otherwise: `Core`'s credentials."""

    withheld: list[Withheld] = [
        Withheld(
            action="force-push",
            why=(
                "a push that isn't a fast-forward rewrites the forge's history, "
                "which others may have built on, and loses the commits only the "
                "forge held"
            ),
        ),
        Withheld(
            action="delete-ref",
            why="deleting a branch or tag on the forge loses the commits only it held",
        ),
    ]
    """The actions lup's default leaves out, each with its reason."""
    protected: list[str] = ["refs/heads/main", "refs/tags/*"]
    """Refs no push updates, as patterns over full ref names.

    - `refs/heads/main`: what reaches `main` is the operator's to merge
      (`DESIGN.md`, *Policy*: "no push to `main`"; `AGENTS.md`: "Never merge
      into `main` or push to it yourself");
    - `refs/tags/*`: a tag marks a release, which is the operator's too.
    """
    gated: list[str] = ["refs/heads/dev"]
    """Refs a push from a room updates only once the gate passed on the commit it
    would put there, as patterns over full ref names: lup's integration branch,
    `dev`, so it never takes a commit the gate fails on. A project whose
    integration branch is another names that one. The gate runs in the room,
    before the host is asked: it steers, and guards nothing
    (`docs/host-tools.md`, *git through a remote helper*)."""
