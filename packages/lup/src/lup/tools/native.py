"""Explicit authority for a session's built-in tools, independent of app tools."""

from collections.abc import Iterator, Sequence
from enum import StrEnum


class NativeToolGroup(StrEnum):
    """Composable facilities; an adapter refuses any it cannot enforce exactly."""

    READ = "read"
    WEB = "web"
    WRITE = "write"
    SHELL = "shell"
    ALL = "all"


type NativeTools = Sequence[NativeToolGroup | str] | None


def native_grants(grants: NativeTools) -> tuple[NativeToolGroup | str, ...]:
    """Validate exact grants before an adapter expands its own tool spellings.

    None and an empty declaration both grant nothing. Permission patterns are
    not tool identities and would widen a grant if treated as identities.
    """
    if isinstance(grants, str):
        raise ValueError(
            "native_tools takes a sequence of exact names or NativeToolGroup values"
        )

    def validated() -> Iterator[NativeToolGroup | str]:
        for grant in grants or ():
            if not isinstance(grant, str) or not grant or not grant.isidentifier():
                raise ValueError(
                    f"native_tools requires an exact tool name, got {grant!r}"
                )
            yield NativeToolGroup(grant) if grant in NativeToolGroup else grant

    return tuple(dict.fromkeys(validated()))
