"""Processes a launch runs on the host beside a session, for as long as it lasts.

Some work wants something running outside the session while it goes on: a
preview server showing what the session is making, a watcher rebuilding it.
Started by hand, it is one more thing an operator forgets to start, or to
stop, and a second copy fighting the first for a port. Declared, the launch
starts it after the launch is cleared to open — past the trust review, so it
is the approved declaration that names it — says where it is in the banner,
and stops it, and whatever it started, when the session ends.

A companion runs on the host, as the operator, with the host's network. That
is the point of it and the reason it is declared where a review reads it: it
is outside every boundary the session has. A contained session reaches it
only as any host service, by a declared name.

That is also what makes a companion the one place a secret the session must
never hold can be used: a listener calling a paid API, say. It names the keys
it needs in ``secrets``, and the launch hands it exactly those from the
operator's host store (:mod:`lup.devtools.envfiles`) -- no other companion
receives them, and the session's own environment has them taken out.
"""

from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

from lup.types import EnvName


class HostCompanion(BaseModel, frozen=True):
    """One process started on the host beside each session, and stopped with it."""

    name: str = Field(
        pattern=r"^[a-z][a-z0-9_-]*$",
        max_length=64,
        description="What the companion is called, in the banner and its log's name",
    )
    command: list[str] = Field(
        min_length=1,
        description="The program and its arguments, run without a shell",
    )
    directory: PurePosixPath = Field(
        default=PurePosixPath("."),
        description="Where it runs, relative to the checkout",
    )
    url: str = Field(
        default="",
        description="Where the operator reaches it, said in the banner; empty says none",
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
