"""`Remote`: a room's `git push` and `git fetch`, carried out with the operator's credentials, within what the project's declaration allows, among lup's default modules."""

from fnmatch import fnmatchcase
from typing import ClassVar, Literal, get_args

from lup.declaration.grammar import Named
from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.remote.promises import RemotePromises
from lup.remote.remotes import Remotes

type Action = Literal["fetch", "push", "force-push", "delete-landed", "delete-any"]
"""What a room may ask of a remote with the operator's credentials:
- `fetch`: list a remote's refs and fetch its objects;
- `push`: update a ref by a fast-forward;
- `force-push`: update one otherwise, rewriting what the remote holds;
- `delete-landed`: delete a branch whose commits are all in the integration
  branch on the remote already, so nothing goes with it;
- `delete-any`: delete any ref, whatever it holds."""


class Actions(Named[str]):
    """What a room may ask of a remote with the operator's credentials, by name: `Remote(actions=Actions().add("force-push"))`."""


class Refs(Named[str]):
    """Refs no room's push updates, as patterns over their full names, as `fnmatch` reads them, `*` spanning `/`: `refs/tags/*`."""


class Remote(Module):
    """A room's `git push` and `git fetch`, carried out with the operator's credentials, within what the declaration allows.

    Each project's is one part, in a container of its own, holding the
    project's git directory and the operator's SSH agent alone (`Remotes`). A
    room's git reaches it through `git-remote-lup`, which the room's git
    configuration sends each of the repository's remotes through.
    """

    name = "remote"
    known: ClassVar[list[str]] = list(get_args(Action.__value__))
    """Every action lup carries out with the operator's credentials, which
    `Actions.all()` starts from."""
    actions: Actions = (
        Actions.all()
        .drop(
            "force-push",
            why=(
                "a push that isn't a fast-forward rewrites what the remote holds, "
                "which others may have built on, losing the commits only it held"
            ),
        )
        .drop(
            "delete-any",
            why="deleting a ref the integration branch doesn't hold loses the commits only the remote held",
        )
    )
    """What a room may ask of a remote: every action lup carries out, but
    those dropped, each with why, so an action a later release adds is
    allowed unless a project drops it too."""
    protected: Refs = Refs.of("refs/tags/*")
    """Refs no room's push updates: a tag marks a release, which is the
    operator's. The integration branch and the release branch a project lands
    on (`Landing`) are held too, the first moving only by the operator's
    accept, the second only by their merge."""
    parts: Parts = Parts.of(Remotes, RemotePromises)

    def allowed(self) -> list[str]:
        """Return the actions a room may ask of a remote, as the declaration resolves them."""
        return [each.entry for each in self.actions.resolve(self.known, self.known)]

    def holding(self, ref: str) -> str | None:
        """Return the pattern among `protected` that `ref`, by its full name, matches, or none.

        >>> Remote().holding("refs/tags/v1"), Remote().holding("refs/heads/feat")
        ('refs/tags/*', None)
        """
        return next(
            (pattern for pattern in self.held(Refs) if fnmatchcase(ref, pattern)),
            None,
        )
