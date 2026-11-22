"""`GitHub`: the tools sessions act on GitHub through, with the operator's own login, within what the project's declaration allows, among lup's default modules."""

from typing import ClassVar, Literal, get_args

from lup.declaration.grammar import Named
from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.github.forge import Forge
from lup.github.promises import GitHubPromises

type Action = Literal[
    "read",
    "file-issue",
    "edit",
    "close-issue",
    "comment",
    "edit-comment",
    "pull-request",
]
"""What an agent may do on GitHub under the operator's name:
- `read`: read and search issues and pull requests, of any repository their
  login can read, and say whether an issue is open;
- `file-issue`: file an issue;
- `edit`: edit an issue's or a pull request's title, body or labels;
- `close-issue`: close an issue, saying why, or reopen one;
- `comment`: comment on an issue or a pull request;
- `edit-comment`: edit a comment;
- `pull-request`: open a pull request, as a draft or ready, and mark a draft
  ready.

Merging and approving aren't among them: either would show the operator's
name on a decision they didn't make."""


class Actions(Named[str]):
    """What an agent may do on GitHub under the operator's name, by name: `GitHub(actions=Actions().drop("file-issue", why="…"))`."""


class GitHub(Module):
    """The tools sessions act on GitHub through, with the operator's own login, within what the declaration allows.

    Each project's is one part, in a container of its own, holding the
    operator's GitHub login alone (`Forge`). It writes to the project's own
    repository on GitHub alone, named by its remote, and reads any the
    operator's login can.
    """

    name = "github"
    known: ClassVar[list[str]] = list(get_args(Action.__value__))
    """Every action lup carries out on GitHub, which `Actions.all()` starts
    from."""
    actions: Actions = Actions.all()
    """What an agent may do on GitHub: every action lup carries out, so an
    action a later release adds is allowed unless a project drops it."""
    parts: Parts = Parts.of(Forge, GitHubPromises)

    def allowed(self) -> list[str]:
        """Return the actions an agent may take on GitHub, as the declaration resolves them."""
        return [each.entry for each in self.actions.resolve(self.known, self.known)]
