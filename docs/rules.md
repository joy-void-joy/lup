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
