"""The host service's control requests and replies, typed.

One request per connection, its JSON read to the end, and one JSON reply. A request
is a model told apart by its `kind`, which names the handler that answers it
(`host/service.py`); a reply is told apart by its own. The kinds here are the
service's own: a launch's registration, its end, and stopping the service. A
module declares its own kinds beside the handler it registers for them.
"""

from pathlib import Path, PurePath
from typing import Annotated, Literal

from pydantic import AfterValidator

from lup.types import Model
from lup_dev.errors import LupDevError


class HostError(LupDevError):
    """The host service refused a request, or couldn't be reached."""


def segment(launch: str) -> str:
    """Return a launch's id if it can name a directory: one path segment, not `..`.

    >>> segment("a1b2")
    'a1b2'
    """
    if not launch or launch == ".." or PurePath(launch).name != launch:
        message = f"a launch's id names its directory, so it's one path segment, not {launch!r}"
        raise ValueError(message)
    return launch


type LaunchId = Annotated[str, AfterValidator(segment)]
"""A launch's id: unique among the launches the service serves, it names their directory."""


class Request(Model):
    """A control request: its `kind` names it, and the handler that answers it."""

    kind: str

    @classmethod
    def named(cls) -> str:
        """Return the kind this model's requests carry, its `kind` field's default.

        A model built without validation holds its defaults, so a request's kind is
        read from its model rather than spelled again where it's routed.
        """
        return cls.model_construct().kind


class Register(Request):
    """Serve a launch: its socket directory, the hook socket inside, its record."""

    kind: Literal["register"] = "register"
    launch: LaunchId
    runtime: str
    """The runtime the launch runs, by its name: whose adapter answers its hooks."""
    worktree: Path
    """The worktree the launch started in."""


class Unregister(Request):
    """End a launch: its sockets closed, its directory and record removed."""

    kind: Literal["unregister"] = "unregister"
    launch: LaunchId


class Stop(Request):
    """Stop the service; the launches it serves stay recorded, for the next to serve."""

    kind: Literal["stop"] = "stop"


class Reply(Model):
    """The service's answer to one request, told apart by its `kind`."""

    kind: str


class Registered(Reply):
    """The launch is served: its socket directory, which its room mounts."""

    kind: Literal["registered"] = "registered"
    directory: Path


class Done(Reply):
    """The request is carried out, with nothing more to say."""

    kind: Literal["done"] = "done"


class Refused(Reply):
    """The request wasn't carried out, and why."""

    kind: Literal["refused"] = "refused"
    error: str
