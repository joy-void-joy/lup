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
