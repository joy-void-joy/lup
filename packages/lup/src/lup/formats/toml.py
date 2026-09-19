"""The nodes a generated TOML document is declared as.

The third container, and the one that looks safest: TOML quotes a basic
string much as JSON does, which is why `json.dumps` stood in for its quoting
for as long as it did. The two agree until they do not — a literal TOML
reader is entitled to its own escapes, a multi-line value wants its own
delimiter, and the day a value carries something the two spell differently is
the day a generated agent file stops parsing with nothing in the generator
having changed.

So this says what :mod:`lup.formats.yaml` says, through the library that
already ships here: a node holds the value it stands for, :mod:`tomlkit`
writes it, and :meth:`TomlDocument.text` is parsed back and held against what
the nodes declare before the file exists.
"""

from abc import ABC, abstractmethod
from typing import Annotated, Literal

import tomlkit
from pydantic import BaseModel, Discriminator, model_validator

type TomlValue = str | int | float | bool
"""What TOML writes as one value. A key with nothing under it is omitted
rather than written null, TOML having no such value to write."""

type TomlData = dict[str, TomlValue]
"""A flat table, which is every generated TOML document this repository has."""


class TomlNode(BaseModel, ABC, frozen=True):
    """One value of a generated TOML document, as the writer receives it."""

    @abstractmethod
    def plain(self) -> TomlValue:
        """The value this node stands for, as a parser would hand it back."""


class TomlScalar(TomlNode, frozen=True):
    """One value, spelled the way the writer spells it."""

    type: Literal["scalar"] = "scalar"
    value: TomlValue

    def plain(self) -> TomlValue:
        return self.value


type TomlAny = Annotated[TomlScalar, Discriminator("type")]
"""Any node a generated TOML document holds."""


class TomlEntry(BaseModel, frozen=True):
    """One key of the document, with the comment a reader needs above it."""

    key: str
    value: TomlAny
    comment: str = ""


class TomlDocument(BaseModel, frozen=True):
    """A whole TOML file as the values it carries, written and then read back."""

    entries: list[TomlEntry]

    @model_validator(mode="after")
    def keys_are_distinct(self) -> "TomlDocument":
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(dict.fromkeys(keys)):
            raise ValueError(f"document declares one key twice: {keys}")
        return self

    @model_validator(mode="after")
    def renders_what_it_holds(self) -> "TomlDocument":
        parsed = tomlkit.parse(self.text())
        if parsed != self.plain():
            raise ValueError(
                "toml document does not parse back to what it declares: "
                f"{parsed!r} from {self.plain()!r}"
            )
        return self

    def plain(self) -> TomlData:
        """The data this document stands for, as a parser would hand it back."""
        return {entry.key: entry.value.plain() for entry in self.entries}

    def text(self) -> str:
        """This document as TOML, newline-terminated."""
        written = tomlkit.document()
        for entry in self.entries:
            if entry.comment:
                written.add(tomlkit.comment(entry.comment))
            written.add(entry.key, entry.value.plain())
        return tomlkit.dumps(written)
