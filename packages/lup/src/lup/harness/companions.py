"""Processes a launch runs on the host beside a checkout's sessions, while any lasts.

Some work wants something running outside the session while it goes on: a
preview server showing what the session is making, a watcher rebuilding it.
Started by hand, it is one more thing an operator forgets to start, or to
stop, and a second copy fighting the first for a port. Declared, the launch
starts it after the launch is cleared to open — past the trust review, so it
is the approved declaration that names it — says where it is in the banner,
and stops it, and whatever it started, when the last session using it ends.

One per checkout, shared by that checkout's sessions: a second session in the
same checkout reuses what the first started rather than fighting it for a
port, and a session in another checkout gets companions of its own, serving
its own files on ports of its own. ``ports`` names the ports a companion
wants; each checkout is given the preferred one where it is free and the next
free one otherwise, kept for that checkout from then on, and ``{ports.<name>}``
in the command and the url is the port that checkout was given.

A companion runs on the host, as the operator, with the host's network. That
is the point of it and the reason it is declared where a review reads it: it
is outside every boundary the session has. A contained session reaches it
only as any host service, by a declared name — one that follows the
companion's port (:attr:`lup.harness.services.HostService.companion_port`).

That is also what makes a companion the one place a secret the session must
never hold can be used: a listener calling a paid API, say. It names the keys
it needs in ``secrets``, and the launch hands it exactly those from the
operator's host store (:mod:`lup.devtools.envfiles`) -- no other companion
receives them, and the session's own environment has them taken out.
"""

# lup: ignore[import-re] — the port placeholder is a grammar this module
# defines, and nothing else parses it
import re
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator
from pydantic import model_validator

from lup.types import EnvName

type PortName = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
]
"""What a companion calls one of its ports, and a placeholder spells it with."""

type PortNumber = Annotated[int, Field(ge=1, le=65535)]
"""One TCP port."""

type CompanionPorts = dict[PortName, PortNumber]
"""A companion's ports, by the names its command and url spell them with."""

# lup: ignore[dict-str-payload] — keyed by `<companion>.<port>`, the reference
# a host service follows a companion's port by: an open set a project declares
type PortsGiven = dict[str, int]
"""The ports one checkout's companions were given, each by ``<companion>.<port>``."""

# lup: ignore[re-call] — the placeholder's own grammar, which nothing else parses
PORT_PLACEHOLDER = re.compile(r"\{ports\.(?P<name>[^{}]*)\}")
"""``{ports.<name>}``, and anything spelled like one, so a misspelling is caught."""


class HostCompanion(BaseModel, frozen=True):
    """One process on the host beside a checkout's sessions, stopped after the last."""

    name: str = Field(
        pattern=r"^[a-z][a-z0-9_-]*$",
        max_length=64,
        description="What the companion is called, in the banner and its log's name",
    )
    command: list[str] = Field(
        min_length=1,
        description=(
            "The program and its arguments, run without a shell; "
            "`{ports.<name>}` is the port this checkout was given"
        ),
    )
    directory: PurePosixPath = Field(
        default=PurePosixPath("."),
        description="Where it runs, relative to the checkout",
    )
    url: str = Field(
        default="",
        description=(
            "Where the operator reaches it, said in the banner; empty says none. "
            "`{ports.<name>}` is the port this checkout was given"
        ),
    )
    ports: CompanionPorts = Field(
        default={},
        description=(
            "The ports it listens on, by name, each the one preferred. A "
            "checkout is given the preferred port where it is free and the "
            "next free one otherwise, and keeps it. The companion is alive "
            "while its process is and every one of them answers"
        ),
    )
    open: bool = Field(
        default=False,
        description=(
            "Whether the session that starts it opens its url in the "
            "operator's browser; a session reusing it does not"
        ),
    )
    because: str = Field(
        default="",
        description=(
            "What it is for. A companion runs outside every boundary the "
            "session has, and the reason is what lets the next reader decide "
            "whether it still has to"
        ),
    )
    secrets: list[EnvName] = Field(
        default=[],
        description=(
            "Env keys this companion is handed from the operator's host store, "
            "and it alone. Read from the store and nowhere else, so a key the "
            "launch's own environment exports does not reach it"
        ),
    )

    @field_validator("directory")
    @classmethod
    def inside_the_checkout(cls, value: PurePosixPath) -> PurePosixPath:
        """Refuse a directory reaching outside the checkout it is declared in."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError(
                f"companion directory {value.as_posix()!r} must be inside the "
                "checkout, relative to its root"
            )
        return value

    @model_validator(mode="after")
    def placeholders_name_its_ports(self) -> "HostCompanion":
        """Refuse a placeholder naming no declared port, and an open with no url."""
        unknown = sorted(
            {
                found["name"]
                for text in [*self.command, self.url]
                for found in PORT_PLACEHOLDER.finditer(text)
                if found["name"] not in self.ports
            }
        )
        if unknown:
            raise ValueError(
                f"companion {self.name!r} says "
                f"{', '.join(f'{{ports.{name}}}' for name in unknown)} but declares "
                f"ports: {', '.join(sorted(self.ports)) or 'none'}"
            )
        if self.open and not self.url:
            raise ValueError(
                f"companion {self.name!r} is declared to open, but has no url to open"
            )
        return self

    def references(self, ports: CompanionPorts) -> PortsGiven:
        """These ports under the ``<companion>.<port>`` a host service follows one by."""
        return {f"{self.name}.{name}": port for name, port in ports.items()}

    def at(self, ports: CompanionPorts) -> "HostCompanion":
        """This companion with every placeholder filled by the ports a checkout was given."""

        def filled(text: str) -> str:
            """One argument or url with its placeholders spelled as ports."""
            return PORT_PLACEHOLDER.sub(lambda found: str(ports[found["name"]]), text)

        return self.model_copy(
            update={
                "command": [filled(word) for word in self.command],
                "url": filled(self.url),
            }
        )
