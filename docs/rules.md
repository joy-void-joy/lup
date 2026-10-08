<!-- Generated from `packages/lup-dev/src/lup_dev/catalog/rules.ts` by `lup-dev rules docs`. Edit the table, not this file. -->

# lup's rules

Each rule names the mistake it prevents and where it steers instead, and shows code it flags, the same code done the steer's way, and near misses it leaves alone. The examples are the rules' specification: the engine's tests run every one. How a rule is declared, and why, is in `docs/judging-writes.md`; the conventions the rules enforce are in `docs/conventions.md`.

To keep one finding, write `# lup: ignore("<rule>", why="<reason>")` on its line or alone on the line above; adding one asks the operator.

## `regex`

A regular expression matches the cases it was tried on and fails quietly on the rest, and the bugs it leaves are hard to find.

**Steer:** Read the text with its format's parser (`json`, `tomllib`, `csv`, `urllib.parse`, `shlex`, `ast`, `packaging.version`), and give a grammar of our own a parser library.

**Flags:**

```python
import re


def major(version: str) -> int:
    """Return the major part of a version number."""
    found = re.match("[0-9]+", version)
    return int(found.group()) if found else 0
```

Done the steer's way:

```python
from packaging.version import Version


def major(version: str) -> int:
    """Return the major part of a version number."""
    return Version(version).major
```

**Leaves alone:**

```python
import reprlib


def shown(value: str) -> str:
    """Show a value, shortened for a log line."""
    return reprlib.repr(value)
```


## `tuple-shape`

A tuple's positions hide what each value means, and a second spelling of a sequence beside `list[X]` is one more choice for each session to make.

**Steer:** Name each field with a model, or write a sequence as `list[X]`; where a library takes a tuple, keep it with an `ignore` that says so.

**Flags:**

```python
def location(name: str) -> tuple[str, int]:
    """Return the file and line that define `name`."""
    return name, 1
```

Done the steer's way:

```python
from lup.types import Model


class Location(Model):
    """A file, and a line in it."""

    path: str
    line: int


def location(name: str) -> Location:
    """Return the file and line that define `name`."""
    return Location(path=name, line=1)
```

```python
def total(sizes: tuple[int, ...]) -> int:
    """Add up the sizes."""
    return sum(sizes)
```

Done the steer's way:

```python
def total(sizes: list[int]) -> int:
    """Add up the sizes."""
    return sum(sizes)
```

**Leaves alone:**

```python
def is_tuple(value: object) -> bool:
    """Say whether `value` is a tuple."""
    return isinstance(value, tuple)
```

```python
def frozen(sizes: list[int]) -> object:
    """Return the sizes as a tuple, for hashing."""
    return tuple(sizes)
```


## `set-shape`

A set keeps only membership, throwing away what a dict keyed by its members would record.

**Steer:** Use a dict keyed by the members, or a list of models; a set that truly records nothing, such as things already seen, takes an `ignore` that says so.

**Flags:**

```python
def tools(calls: list[str]) -> set[str]:
    """Return the tools named in `calls`."""
    return set(calls)
```

Done the steer's way:

```python
from collections import Counter


def tools(calls: list[str]) -> Counter[str]:
    """Count the calls to each tool named in `calls`."""
    return Counter(calls)
```

```python
def allowed(tool: str) -> bool:
    """Say whether `tool` may run."""
    return tool in {"Read", "Grep"}
```

Done the steer's way:

```python
def allowed(tool: str) -> bool:
    """Say whether `tool` may run."""
    return tool in ["Read", "Grep"]
```

**Leaves alone:**

```python
def sizes(names: list[str]) -> dict[str, int]:
    """Map each name to its length."""
    return {name: len(name) for name in names}
```


## `string-split`

Splitting structured text by hand matches the inputs it was tried on, and fails quietly on the rest.

**Steer:** Read the text with its format's parser: `shlex.split` for a command line, `urllib.parse` for a URL, `email` for headers, `csv` for rows.

**Flags:**

```python
def host(url: str) -> str:
    """Return the host `url` names."""
    return url.split("/")[2]
```

Done the steer's way:

```python
from urllib.parse import urlsplit


def host(url: str) -> str:
    """Return the host `url` names, or nothing when it names none."""
    return urlsplit(url).hostname or ""
```

**Leaves alone:**

```python
import shlex


def words(line: str) -> list[str]:
    """Split a command line as a shell would, and a sentence on its spaces."""
    return [*shlex.split(line), *line.split(), *line.split(None, 1)]
```


## `string-slice`

Taking text apart by position breaks quietly as soon as its layout shifts.

**Steer:** Read the text with its format's parser, which says what each part is.

**Flags:**

```python
def branch(ref: str) -> str:
    """Return the branch a git ref names."""
    return ref[len("refs/heads/") :]
```

Done the steer's way:

```python
from pathlib import PurePosixPath


def branch(ref: str) -> str:
    """Return the branch a git ref names."""
    return PurePosixPath(ref).relative_to("refs/heads").as_posix()
```

**Leaves alone:**

```python
def rest(items: list[int], name: str) -> list[int]:
    """Return all but the first item, and the length of `name`'s first letter."""
    return [*items[1:], len(name[0])]
```


## `dict-literal-key`

Reading a dict by literal keys treats it as a record whose schema hides in the places that read it.

**Steer:** Validate the data once into a model, and read its fields.

**Flags:**

```python
import json


def tool(payload: str) -> str:
    """Return the tool a hook's payload names."""
    data: dict[str, str] = json.loads(payload)
    return data["tool_name"]
```

Done the steer's way:

```python
from lup.types import Model


class Payload(Model):
    """The part of a hook's payload read here."""

    tool_name: str


def tool(payload: str) -> str:
    """Return the tool a hook's payload names."""
    return Payload.model_validate_json(payload).tool_name
```

```python
def model(settings: dict[str, str]) -> str:
    """Return the model the settings name."""
    return settings.get("model", "default")
```

Done the steer's way:

```python
from lup.types import Model


class Chosen(Model):
    """The settings read here."""

    model: str = "default"


def model(settings: dict[str, str]) -> str:
    """Return the model the settings name."""
    return Chosen.model_validate(settings).model
```

**Leaves alone:**

```python
def price(prices: dict[str, int], item: str, first: list[int]) -> int:
    """Look an item's price up in the table, and add the first extra."""
    return prices[item] + first[0]
```


## `subprocess`

A second library for running programs, beside the one the rest of the code uses, splits how commands are run, checked and reported.

**Steer:** Run programs with `sh`: `sh.git("status")`, or `sh.Command(path)(…)` for one found by path.

**Flags:**

```python
import subprocess


def status() -> str:
    """Return the working tree's status."""
    return subprocess.run(["git", "status"], capture_output=True, text=True).stdout
```

Done the steer's way:

```python
import sh


def status() -> str:
    """Return the working tree's status."""
    return str(sh.git("status"))
```

**Leaves alone:**

```python
import asyncio


async def pause() -> None:
    """Give other tasks a turn."""
    await asyncio.sleep(0)
```


## `os-shell`

Running a program through the shell, or in place of this process, hides its arguments from the reader and its failure from the caller.

**Steer:** Run programs with `sh`, which takes the arguments as a list and raises when the program fails.

**Flags:**

```python
import os


def fetch() -> int:
    """Fetch the remote's commits."""
    return os.system("git fetch")
```

Done the steer's way:

```python
import sh


def fetch() -> None:
    """Fetch the remote's commits."""
    sh.git("fetch")
```

**Leaves alone:**

```python
import os


def process() -> int:
    """Return this process's id."""
    return os.getpid()
```


## `argparse`

A second library for command lines, beside the one lup commands use, splits how options are declared, checked and documented.

**Steer:** Declare the command line with `typer`.

**Flags:**

```python
import argparse


def main() -> None:
    """Greet the name given."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    print(f"hello {parser.parse_args().name}")
```

Done the steer's way:

```python
import typer

app = typer.Typer()


@app.command()
def main(name: str) -> None:
    """Greet `name`."""
    typer.echo(f"hello {name}")
```

**Leaves alone:**

```python
import typer


def ask() -> bool:
    """Ask whether to go on."""
    return typer.confirm("Go on?")
```


## `os-path`

Paths handled as strings lose what a path knows, and each place joins and splits them its own way.

**Steer:** Handle paths with `pathlib`: `Path(root) / "docs"`, `path.suffix`, `path.parent`.

**Flags:**

```python
import os


def docs(root: str) -> str:
    """Return where the docs are."""
    return os.path.join(root, "docs")
```

Done the steer's way:

```python
from pathlib import Path


def docs(root: str) -> Path:
    """Return where the docs are."""
    return Path(root) / "docs"
```

```python
from os.path import splitext


def stem(name: str) -> str:
    """Return a file name without its extension."""
    return splitext(name)[0]
```

Done the steer's way:

```python
from pathlib import PurePath


def stem(name: str) -> str:
    """Return a file name without its extension."""
    return PurePath(name).stem
```

**Leaves alone:**

```python
import os


def processors() -> int:
    """Return how many processors there are."""
    return os.cpu_count() or 1
```


## `os-file-ops`

Files handled through string paths, beside `pathlib`, split how files are found, written and removed.

**Steer:** Handle files with `pathlib`: `path.unlink()`, `path.mkdir(parents=True)`, `path.iterdir()`.

**Flags:**

```python
import os


def names(directory: str) -> list[str]:
    """List the names in a directory."""
    return os.listdir(directory)
```

Done the steer's way:

```python
from pathlib import Path


def names(directory: str) -> list[str]:
    """List the names in a directory."""
    return [entry.name for entry in Path(directory).iterdir()]
```

**Leaves alone:**

```python
import os


def process() -> int:
    """Return this process's id."""
    return os.getpid()
```


## `os-environ`

An environment variable read where it's used can't be found or listed, and a missing one fails deep inside the code.

**Steer:** Read environment variables as fields of the package's settings model (`settings.py`, pydantic-settings), validated once.

**Flags:**

```python
import os


def editor() -> str:
    """Return the editor the user chose."""
    return os.getenv("EDITOR", "vi")
```

Done the steer's way:

```python
from lup.types import Settings


class Environment(Settings):
    """The environment variables read here, one field each."""

    editor: str = "vi"


def editor() -> str:
    """Return the editor the user chose."""
    return Environment().editor
```

**Leaves alone:**

```python
import os


def process() -> int:
    """Return this process's id."""
    return os.getpid()
```


## `rich-progress`

A second library for progress bars splits how long work shows its progress.

**Steer:** Show progress with `tqdm`.

**Flags:**

```python
from rich.progress import track


def total(sizes: list[int]) -> int:
    """Add up the sizes, showing progress."""
    return sum(track(sizes))
```

Done the steer's way:

```python
from tqdm import tqdm


def total(sizes: list[int]) -> int:
    """Add up the sizes, showing progress."""
    return sum(tqdm(sizes))
```

**Leaves alone:**

```python
from rich.console import Console


def show(text: str) -> None:
    """Print text with its markup."""
    Console().print(text)
```


## `pdf-extraction`

A text extractor's empty result reads as an empty document, so a scanned PDF passes as blank.

**Steer:** Read the document whole, as a document a model reads, rather than the text a library extracts.

**Flags:**

```python
from pypdf import PdfReader


def text(path: str) -> str:
    """Return a PDF's text."""
    return "".join(page.extract_text() for page in PdfReader(path).pages)
```

Done the steer's way:

```python
from pathlib import Path


def document(path: str) -> bytes:
    """Return a PDF whole, for a model that reads documents."""
    return Path(path).read_bytes()
```

**Leaves alone:**

```python
from pathlib import Path


def size(path: str) -> int:
    """Return a PDF's size in bytes."""
    return Path(path).stat().st_size
```


## `suppress`

An error swallowed by `suppress` leaves no trace of what failed, or why.

**Steer:** Handle the error, log it, or let it rise; where a library can skip the case itself, let it.

**Flags:**

```python
from contextlib import suppress
from pathlib import Path


def remove(path: str) -> None:
    """Remove a file, if it's there."""
    with suppress(FileNotFoundError):
        Path(path).unlink()
```

Done the steer's way:

```python
from pathlib import Path


def remove(path: str) -> None:
    """Remove a file, if it's there."""
    Path(path).unlink(missing_ok=True)
```

**Leaves alone:**

```python
from contextlib import ExitStack


def stack() -> ExitStack:
    """Return an empty stack of exits."""
    return ExitStack()
```


## `bare-except`

A bare `except:` catches everything, `KeyboardInterrupt` and `SystemExit` included, and hides why.

**Steer:** Catch `Exception` or something narrower, and handle, log or re-raise it.

**Flags:**

```python
def number(text: str) -> int:
    """Read a number, or zero."""
    try:
        return int(text)
    except:
        return 0
```

Done the steer's way:

```python
def number(text: str) -> int:
    """Read a number, or zero."""
    try:
        return int(text)
    except ValueError:
        return 0
```

**Leaves alone:**

```python
def number(text: str) -> int:
    """Read a number, or zero."""
    try:
        return int(text)
    except (ValueError, OverflowError):
        return 0
```


## `except-baseexception`

Catching `BaseException` catches `KeyboardInterrupt` and `SystemExit` too, so nothing can stop the code.

**Steer:** Catch `Exception` or something narrower, and handle, log or re-raise it.

**Flags:**

```python
def number(text: str) -> int:
    """Read a number, or zero."""
    try:
        return int(text)
    except BaseException:
        return 0
```

Done the steer's way:

```python
def number(text: str) -> int:
    """Read a number, or zero."""
    try:
        return int(text)
    except ValueError:
        return 0
```

**Leaves alone:**

```python
def wait() -> None:
    """Wait until interrupted."""
    try:
        input()
    except KeyboardInterrupt:
        return
```


## `suppression-comment`

A second suppression syntax hides a finding without the operator ever being asked.

**Steer:** Keep one finding with `# lup: ignore("<rule>", why="<reason>")`, which asks the operator.

**Flags:**

```python
def width() -> int:
    """Return the width."""
    return 1  # noqa: PLR2004
```

Done the steer's way:

```python
def width() -> int:
    """Return the width."""
    return 1
```

```python
def width() -> int:
    """Return the width."""
    return "1"  # type: ignore[return-value]
```

Done the steer's way:

```python
def width() -> int:
    """Return the width."""
    return 1
```

**Leaves alone:**

```python
def width() -> int:
    """Return the width."""
    # the type checker reads this
    return 1
```


## `any-type`

`Any` turns type checking off for everything it touches.

**Steer:** Give the real type, a type parameter, or `JsonValue` or `JsonObject` for JSON whose schema lives elsewhere.

**Flags:**

```python
from typing import Any


def size(value: Any) -> int:
    """Return the size of `value`."""
    return len(value)
```

Done the steer's way:

```python
def size(value: str | list[str]) -> int:
    """Return the size of `value`."""
    return len(value)
```

**Leaves alone:**

```python
def anything(values: list[bool]) -> bool:
    """Say whether any value holds."""
    return any(values)
```


## `cast`

`cast` asserts a type without checking it, so a wrong one passes silently.

**Steer:** Narrow with `isinstance` or `match`, or validate with a model, so the type is checked.

**Flags:**

```python
from typing import cast


def text(value: str | int) -> str:
    """Return `value`, which callers pass as text."""
    return cast("str", value)
```

Done the steer's way:

```python
def text(value: str | int) -> str:
    """Return `value` as text."""
    return value if isinstance(value, str) else str(value)
```

**Leaves alone:**

```python
def unsigned(data: bytes) -> list[int]:
    """Read bytes as unsigned numbers."""
    return memoryview(data).cast("B").tolist()
```


## `bare-object`

`object` as a type says nothing about the value, so every use needs a check the type could have done.

**Steer:** Give the real type, a type parameter, or `JsonValue` or `JsonObject` for JSON whose schema lives elsewhere.

**Flags:**

```python
def first(values: list[object]) -> object:
    """Return the first of `values`."""
    return values[0]
```

Done the steer's way:

```python
def first[T](values: list[T]) -> T:
    """Return the first of `values`."""
    return values[0]
```

**Leaves alone:**

```python
class Point:
    """A point, equal to another at the same place."""

    def __init__(self, x: int) -> None:
        """Place the point."""
        self.x = x

    def __eq__(self, other: object) -> bool:
        """Say whether `other` is a point at the same place."""
        return isinstance(other, Point) and other.x == self.x

    def __hash__(self) -> int:
        """Hash the point by its place."""
        return hash(self.x)
```


## `dataclass`

A dataclass is a second way to declare a shape, beside pydantic models, and validates nothing.

**Steer:** Declare the shape as a model deriving from `lup.types.Model`.

**Flags:**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    """A point on the plane."""

    x: int
    y: int
```

Done the steer's way:

```python
from lup.types import Model


class Point(Model):
    """A point on the plane."""

    x: int
    y: int
```

**Leaves alone:**

```python
from dataclasses import is_dataclass


def described(value: type) -> bool:
    """Say whether a class from elsewhere is a dataclass."""
    return is_dataclass(value)
```


## `namedtuple`

A named tuple is a second way to declare a shape, beside pydantic models, and still reads by position.

**Steer:** Declare the shape as a model deriving from `lup.types.Model`.

**Flags:**

```python
from typing import NamedTuple


class Point(NamedTuple):
    """A point on the plane."""

    x: int
    y: int
```

Done the steer's way:

```python
from lup.types import Model


class Point(Model):
    """A point on the plane."""

    x: int
    y: int
```

**Leaves alone:**

```python
from typing import NewType

UserId = NewType("UserId", int)
```


## `model-config`

A `model_config` assignment reads like a field, though it configures the class.

**Steer:** Configure the model with class keywords: `class Turn(Model, extra="forbid")`.

**Flags:**

```python
from pydantic import ConfigDict

from lup.types import Model


class Turn(Model):
    """One turn of a conversation."""

    model_config = ConfigDict(extra="forbid")

    text: str
```

Done the steer's way:

```python
from lup.types import Model


class Turn(Model, extra="forbid"):
    """One turn of a conversation."""

    text: str
```

**Leaves alone:**

```python
from lup.types import Model


class Turn(Model, extra="forbid"):
    """One turn of a conversation, and the model that took it."""

    text: str
    model: str = "small"
```


## `default-factory`

A factory for an empty collection says in a call what a literal default says plainly.

**Steer:** Default to the literal, `steps: list[Step] = []`, which pydantic copies for each instance.

**Flags:**

```python
from pydantic import Field

from lup.types import Model


class Plan(Model):
    """The steps a run takes."""

    steps: list[str] = Field(default_factory=list)
```

Done the steer's way:

```python
from lup.types import Model


class Plan(Model):
    """The steps a run takes."""

    steps: list[str] = []
```

**Leaves alone:**

```python
from datetime import UTC, datetime

from pydantic import Field

from lup.types import Model


class Stamp(Model):
    """When something happened."""

    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```


## `model-mutability`

A model deriving straight from pydantic's base, or writing `frozen` itself, leaves whether it can change to each model.

**Steer:** Derive from `lup.types.Model`, which is frozen, or from `lup.types.MutableModel` where values must change, or `lup.types.Settings`; never write `frozen`.

**Flags:**

```python
from pydantic import BaseModel


class Point(BaseModel, frozen=True):
    """A point on the plane."""

    x: int
```

Done the steer's way:

```python
from lup.types import Model


class Point(Model):
    """A point on the plane."""

    x: int
```

**Leaves alone:**

```python
from lup.types import MutableModel


class Tally(MutableModel):
    """A count that goes up as things happen."""

    seen: int = 0
```


## `typed-dict`

A `TypedDict` of our own is a second way to declare a shape, beside pydantic models, and validates nothing.

**Steer:** Declare the shape as a model deriving from `lup.types.Model`; a `TypedDict` appears only where a library's API is typed with one, and then it's the library's.

**Flags:**

```python
from typing import TypedDict


class Turn(TypedDict):
    """One turn of a conversation."""

    text: str
```

Done the steer's way:

```python
from lup.types import Model


class Turn(Model):
    """One turn of a conversation."""

    text: str
```

**Leaves alone:**

```python
from collections.abc import Mapping


def total(counts: Mapping[str, int]) -> int:
    """Add up the counts in a mapping, whatever its keys."""
    return sum(counts.values())
```


## `all-export`

`__all__` outside a package's root makes a second public list, beside the one the package's root declares.

**Steer:** Leave `__all__` to the package's root; elsewhere, import each name from the module that defines it.

**Flags:**

```python
__all__ = ["greet"]


def greet() -> str:
    """Return a greeting."""
    return "hello"
```

Done the steer's way:

```python
def greet() -> str:
    """Return a greeting."""
    return "hello"
```

**Leaves alone:**

```python
import json


def exported() -> list[str]:
    """List what `json` exports."""
    return list(json.__all__)
```


## `protocol`

A `Protocol` is a second way to declare an interface, beside an ABC, matched by shape and checked only by pyright.

**Steer:** Declare the interface as an ABC its implementations inherit; for a shape we don't own, keep the `Protocol` with an `ignore` saying so.

**Flags:**

```python
from typing import Protocol


class Greeter(Protocol):
    """Something that greets."""

    def greet(self) -> str:
        """Return a greeting."""
        ...
```

Done the steer's way:

```python
from abc import ABC, abstractmethod


class Greeter(ABC):
    """Something that greets."""

    @abstractmethod
    def greet(self) -> str:
        """Return a greeting."""
```

**Leaves alone:**

```python
from collections.abc import Iterable


def total(values: Iterable[int]) -> int:
    """Add up `values`."""
    return sum(values)
```


## `elif`

An `elif` chain hides which value decides, arm after arm.

**Steer:** Decide on a value's structure with `match`; compare with guard clauses that return, one `if` after another.

**Flags:**

```python
def unit(seconds: int) -> str:
    """Return the unit a duration shows in."""
    if seconds < 60:
        return "s"
    elif seconds < 3600:
        return "m"
    return "h"
```

Done the steer's way:

```python
def unit(seconds: int) -> str:
    """Return the unit a duration shows in."""
    if seconds < 60:
        return "s"
    if seconds < 3600:
        return "m"
    return "h"
```

```python
def unit(seconds: int) -> str:
    """Return the unit a duration shows in."""
    if seconds < 60:
        unit = "s"
    else:
        if seconds < 3600:
            unit = "m"
        else:
            unit = "h"
    return unit
```

Done the steer's way:

```python
def unit(seconds: int) -> str:
    """Return the unit a duration shows in."""
    if seconds < 60:
        return "s"
    if seconds < 3600:
        return "m"
    return "h"
```

**Leaves alone:**

```python
def sign(number: int) -> int:
    """Return the sign of a number."""
    if number < 0:
        return -1
    return 1 if number > 0 else 0
```


## `wildcard-guard`

A guard on a pattern that matches anything is an `if` chain dressed as a `match`.

**Steer:** Write a pattern that binds what the guard reads (`case Lease(reason=str() as reason) if reason:`), or compare with guard clauses.

**Flags:**

```python
def unit(seconds: int) -> str:
    """Return the unit a duration shows in."""
    match seconds:
        case _ if seconds < 60:
            return "s"
        case _:
            return "m"
```

Done the steer's way:

```python
def unit(seconds: int) -> str:
    """Return the unit a duration shows in."""
    if seconds < 60:
        return "s"
    return "m"
```

**Leaves alone:**

```python
from lup.types import Model


class Lease(Model):
    """A hold on a resource, and why it's held."""

    reason: str


def why(lease: Lease | None) -> str:
    """Say why a lease is held, if it is."""
    match lease:
        case Lease(reason=str() as reason) if reason:
            return reason
        case _:
            return "unheld"
```


## `isinstance-chain`

A chain of `isinstance` tests on one value hides that it decides on its class, arm after arm.

**Steer:** Decide with a `match` on the value, a class pattern each arm: `case int():`.

**Flags:**

```python
def size(value: int | str | list[int]) -> int:
    """Return how big a value is."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return len(value)
    return len(value)
```

Done the steer's way:

```python
def size(value: int | str | list[int]) -> int:
    """Return how big a value is."""
    match value:
        case int():
            return value
        case _:
            return len(value)
```

**Leaves alone:**

```python
def size(value: int | str) -> int:
    """Return how big a value is."""
    if isinstance(value, int):
        return value
    return len(value)
```


## `string-strip`

Stripping given characters off text takes it apart by hand, and fails quietly on the input it wasn't tried on.

**Steer:** Read the text with its format's parser; `.strip()` with no argument, which trims whitespace, is fine.

**Flags:**

```python
def release(tag: str) -> str:
    """Return the release a tag names: `1.2` for `v1.2`."""
    return tag.lstrip("v")
```

Done the steer's way:

```python
from packaging.version import Version


def release(tag: str) -> str:
    """Return the release a tag names: `1.2` for `v1.2`."""
    return str(Version(tag))
```

**Leaves alone:**

```python
def tidy(line: str) -> str:
    """Trim the whitespace around a line."""
    return line.strip()
```


## `string-replace`

Rewriting text by replacing pieces of it edits a format by hand, and fails quietly on the input it wasn't tried on.

**Steer:** Build or rewrite the text with its format's own tools: `urllib.parse.quote`, `shlex.join`, `json.dumps`.

**Flags:**

```python
def escaped(url: str) -> str:
    """Return a URL with its spaces escaped."""
    return url.replace(" ", "%20")
```

Done the steer's way:

```python
from urllib.parse import quote


def escaped(url: str) -> str:
    """Return a URL with its spaces escaped."""
    return quote(url, safe=":/?=&")
```

**Leaves alone:**

```python
from datetime import datetime


def midnight(moment: datetime) -> datetime:
    """Return the start of a moment's day."""
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)
```


## `silent-truncation`

A sequence cut at a fixed bound to make it fit drops what lies past it, and nothing says so.

**Steer:** Keep the whole value; where a format forces a limit, save the full copy, point at it, and say so in an `ignore`.

**Flags:**

```python
def shown(rows: list[str]) -> list[str]:
    """Return the rows a report shows."""
    return rows[:200]
```

Done the steer's way:

```python
from pathlib import Path


def shown(rows: list[str], saved: str) -> str:
    """Return the report: every row, saved whole where the report points."""
    Path(saved).write_text("\n".join(rows))
    return f"{len(rows)} rows, in {saved}"
```

**Leaves alone:**

```python
def body(rows: list[str]) -> list[str]:
    """Return the rows after the header."""
    return rows[1:]
```


## `historical-voice`

A comment or docstring telling how the code came to be means something only against a version the reader never sees.

**Steer:** Say what is: "the call waits", not "the call now waits"; "a file being created", not "a new file". History belongs in the commit message.

**Flags:**

```python
import time


def pause(seconds: float) -> None:
    """Pause before the next try, which now waits a second at least."""
    time.sleep(max(seconds, 1))
```

Done the steer's way:

```python
import time


def pause(seconds: float) -> None:
    """Pause before the next try, for a second at least."""
    time.sleep(max(seconds, 1))
```

**Leaves alone:**

```python
def described(old: str, replacement: str) -> str:
    """Describe an edit: its `old_string` and `new_string`, which "the new text" names."""
    return f"{old} -> {replacement}"
```


## `docstring-code`

reStructuredText's double backticks and Sphinx roles are a second way to mark code, beside Markdown's.

**Steer:** Mark inline code with single backticks: `name`, `print`.

**Flags:**

```python
def greet(name: str) -> str:
    """Return a greeting for ``name``; see :func:`print`."""
    return f"hello {name}"
```

Done the steer's way:

```python
def greet(name: str) -> str:
    """Return a greeting for `name`; see `print`."""
    return f"hello {name}"
```

**Leaves alone:**

```python
def greet(name: str) -> str:
    """Return a greeting. Usage: `greet("Ada")`."""
    return f"hello {name}"
```


## `runtime-mention`

A runtime named outside its adapter builds a feature for one runtime above the seam, where the others quietly lack it.

**Steer:** Speak in lup's own words and capabilities (`runtime.asks_before()`); the runtime's spelling, and the evidence behind a capability, belong in its adapter.

**Flags:**

```python
def asks_first(runtime: str) -> bool:
    """Say whether a runtime asks before a call runs."""
    return runtime == "claude"
```

Done the steer's way:

```python
from abc import ABC, abstractmethod


class Runtime(ABC):
    """One agent runtime, as lup sees it."""

    @abstractmethod
    def asks_before(self) -> bool:
        """Say whether the runtime can ask the operator before a call runs."""


def asks_first(runtime: Runtime) -> bool:
    """Say whether a runtime asks before a call runs."""
    return runtime.asks_before()
```

**Leaves alone:**

```python
def settings_home(name: str) -> str:
    """Return where a runtime keeps its settings, by the name its adapter gives."""
    return f".{name}"
```


## `collection-loop`

A collection created empty and filled in a loop spreads one value over several statements.

**Steer:** Build it with a comprehension, or, where the loop has control flow a comprehension can't hold, a nested function that `yield`s.

**Flags:**

```python
def squares(numbers: list[int]) -> list[int]:
    """Return the square of each number."""
    squared: list[int] = []
    for number in numbers:
        squared.append(number * number)
    return squared
```

Done the steer's way:

```python
def squares(numbers: list[int]) -> list[int]:
    """Return the square of each number."""
    return [number * number for number in numbers]
```

**Leaves alone:**

```python
def merged(counts: dict[str, int], extra: dict[str, int]) -> dict[str, int]:
    """Add the extra counts to a copy of the counts."""
    total = dict(counts)
    for key, value in extra.items():
        total[key] = total.get(key, 0) + value
    return total
```


## `constant-home`

A constant outside its home is frozen where a caller can't change it, or spread where nobody can find it.

**Steer:** A number or duration becomes an overridable default (a parameter default or a model field default); a path goes in the package's `layout.py`, an environment variable's name in its `settings.py`, a runtime's wire spelling in its adapter's `Spellings`.

**Flags:**

```python
import time

RETRIES = 3


def fetch() -> None:
    """Try a few times."""
    for _ in range(RETRIES):
        time.sleep(0)
```

Done the steer's way:

```python
import time


def fetch(retries: int = 3) -> None:
    """Try a few times."""
    for _ in range(retries):
        time.sleep(0)
```

**Leaves alone:**

```python
GREETING = "hello"


def greet() -> str:
    """Return the greeting."""
    return GREETING
```


## `interface-shape`

An interface whose shape drifts, abstract without saying so, large, carrying behaviour or implemented twice in one class, stops being one seam an implementation fills.

**Steer:** Name `ABC` in the bases of a class with abstract methods; keep an ABC to one to three abstract methods and no concrete behaviour, which lives in a plain class or function composed over it; implement one of our ABCs per class.

**Flags:**

```python
from abc import abstractmethod

from lup.types import Model


class Shape(Model):
    """A shape that knows its area."""

    @abstractmethod
    def area(self) -> float:
        """Return the shape's area."""
```

Done the steer's way:

```python
from abc import ABC, abstractmethod

from lup.types import Model


class Shape(Model, ABC):
    """A shape that knows its area."""

    @abstractmethod
    def area(self) -> float:
        """Return the shape's area."""
```

```python
from abc import ABC, abstractmethod


class Shape(ABC):
    """A shape that knows its area."""

    @abstractmethod
    def area(self) -> float:
        """Return the shape's area."""

    def described(self) -> str:
        """Describe the shape by its area."""
        return f"area {self.area()}"
```

Done the steer's way:

```python
from abc import ABC, abstractmethod


class Shape(ABC):
    """A shape that knows its area."""

    @abstractmethod
    def area(self) -> float:
        """Return the shape's area."""


def described(shape: Shape) -> str:
    """Describe a shape by its area."""
    return f"area {shape.area()}"
```

```python
from abc import ABC, abstractmethod


class Reader(ABC):
    """Something that reads."""

    @abstractmethod
    def read(self) -> str:
        """Return what was read."""


class Writer(ABC):
    """Something that writes."""

    @abstractmethod
    def write(self, text: str) -> int:
        """Write `text`, returning how much was written."""


class Store(Reader, Writer):
    """A store, read and written."""

    def read(self) -> str:
        """Return the store's text."""
        return ""

    def write(self, text: str) -> int:
        """Write `text` to the store."""
        return len(text)
```

Done the steer's way:

```python
from abc import ABC, abstractmethod


class Reader(ABC):
    """Something that reads."""

    @abstractmethod
    def read(self) -> str:
        """Return what was read."""


class Writer(ABC):
    """Something that writes."""

    @abstractmethod
    def write(self, text: str) -> int:
        """Write `text`, returning how much was written."""


class StoreReader(Reader):
    """A store, read."""

    def read(self) -> str:
        """Return the store's text."""
        return ""


class StoreWriter(Writer):
    """A store, written."""

    def write(self, text: str) -> int:
        """Write `text` to the store."""
        return len(text)
```

**Leaves alone:**

```python
from abc import ABC, abstractmethod


class Shape(ABC):
    """A shape that knows its area."""

    @abstractmethod
    def area(self) -> float:
        """Return the shape's area."""


class Square(Shape):
    """A square, by its side."""

    def __init__(self, side: float) -> None:
        """Make a square of `side`."""
        self.side = side

    def area(self) -> float:
        """Return the square's area."""
        return self.side * self.side
```


## `own-model-dispatch`

Choosing by which implementation of one of our ABCs you hold bypasses the seam the ABC is, and leaves the others to drift.

**Steer:** Add a method to the ABC, which each implementation answers, and call it.

**Flags:**

```python
from abc import ABC, abstractmethod


class Runtime(ABC):
    """An agent runtime."""

    @abstractmethod
    def name(self) -> str:
        """Return the runtime's name."""


class Local(Runtime):
    """A runtime on this machine."""

    def name(self) -> str:
        """Return the runtime's name."""
        return "local"


def asks_first(runtime: Runtime) -> bool:
    """Say whether a runtime asks before a call runs."""
    return isinstance(runtime, Local)
```

Done the steer's way:

```python
from abc import ABC, abstractmethod


class Runtime(ABC):
    """An agent runtime."""

    @abstractmethod
    def name(self) -> str:
        """Return the runtime's name."""

    @abstractmethod
    def asks_before(self) -> bool:
        """Say whether the runtime asks before a call runs."""


class Local(Runtime):
    """A runtime on this machine."""

    def name(self) -> str:
        """Return the runtime's name."""
        return "local"

    def asks_before(self) -> bool:
        """Say whether the runtime asks before a call runs: it does."""
        return True


def asks_first(runtime: Runtime) -> bool:
    """Say whether a runtime asks before a call runs."""
    return runtime.asks_before()
```

**Leaves alone:**

```python
from abc import ABC, abstractmethod


class Runtime(ABC):
    """An agent runtime."""

    @abstractmethod
    def name(self) -> str:
        """Return the runtime's name."""


def named(value: Runtime | str) -> str:
    """Return a runtime's name, or a name given as it is."""
    return value.name() if isinstance(value, Runtime) else value
```


## `error-root`

An exception outside its package's root error escapes a caller catching everything the package raises.

**Steer:** Derive it from the package's root error, named for the package (`LupDevError` in `lup_dev`), or from an error below it.

**Flags:**

```python
class ParseError(ValueError):
    """The text isn't in the format."""
```

Done the steer's way:

```python
class ExampleError(Exception):
    """Anything this package raises."""


class ParseError(ExampleError):
    """The text isn't in the format."""
```

**Leaves alone:**

```python
from lup.types import Model


class ErrorReport(Model):
    """What went wrong, as a person reads it."""

    summary: str
```


## `error-text`

Deciding on an exception's message breaks quietly when the message is reworded.

**Steer:** Decide on the exception's type, or on its structured fields (`errno`, `status_code`).

**Flags:**

```python
from pathlib import Path


def removed(path: str) -> bool:
    """Remove a file, saying whether it was there."""
    try:
        Path(path).unlink()
    except OSError as error:
        if "No such file" in str(error):
            return False
        raise
    return True
```

Done the steer's way:

```python
from pathlib import Path


def removed(path: str) -> bool:
    """Remove a file, saying whether it was there."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        return False
    return True
```

**Leaves alone:**

```python
def described(error: Exception) -> str:
    """Describe an error for a person to read."""
    return f"failed: {error}"
```


## `private-name`

A leading underscore is a second kind of visibility, beside public, that a reviewer has to second-guess.

**Steer:** Make the name public, or nest a helper inside its only caller; inline a wrapper around one call. An unused parameter keeps its underscore.

**Flags:**

```python
def _cleaned(text: str) -> str:
    return text.strip()


def words(text: str) -> list[str]:
    """Split text into its words."""
    return _cleaned(text).split()
```

Done the steer's way:

```python
def words(text: str) -> list[str]:
    """Split text into its words."""
    return text.strip().split()
```

**Leaves alone:**

```python
def count(values: list[int], _reason: str = "") -> int:
    """Count the values; the reason is for the caller's records."""
    return sum(1 for _ in values)
```
