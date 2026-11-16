# The declaration

What a project writes to say which modules it's made of, and how lup reads it. A declaration is a Python file binding `project`, a `Project`:

```python
from lup import Module, Modules, Named, Project


class Voices(Named[str]):
    """The voices a story is read in."""


class Narration(Module):
    """Reading a story aloud."""

    name = "narration"
    speed: float = 1.0
    voices: Voices = Voices.of("narrator")


project = Project(
    modules=Modules.default()
    .add(Narration(speed=1.5))
    .edit(Narration(voices=Voices().add("villain")), why="the villain speaks")
)
```

Its library side (`lup.declaration`, re-exported by `lup`) is what a declaration imports; loading and resolving it is the environment's (`lup.environment.declaration`), which nothing on the library side imports.

## A project

`Project` holds the modules a project is made of: lup's default ones, `Modules.default()`, unless it says otherwise. Loading runs the file and returns its `project`; a file that binds none, binds something else or fails as it runs raises `ProjectError`, never standing in the defaults, which would run the project as something it isn't. Loading runs the file and everything it imports, so it runs where a branch's code is harmless, never in the program on the operator's machine (`DESIGN.md`, *Where code runs*).

Resolving applies every layer in order over lup's default modules, then checks that the selection holds a module named `core` (`Core`, `lup/core.py`, or another put in its place with `.replace`), and every module a selected one `requires`, with no cycle among them. lup never adds or drops a module behind the declaration's back. What comes out (`Resolved`) is the modules, and what they serve behind their doors (`lup/doors/README.md`).

## What a module is

A `Module` subclass: its `name` and the modules it `requires` as class attributes, its docstring's first paragraph as its one sentence, and its parts and settings as fields whose defaults are the module's own. Defining the class checks it, each failure naming the module and the field:
- a module with no `name` or docstring;
- a field with no default, since a module added with nothing set stands on its own defaults;
- a plain `list` or `dict`, which a layer would replace whole, so a base couldn't be extended without restating it: it takes a selection;
- a default starting from `Kind.default()`, which would start from itself.

Unknown fields are refused, so a misspelled one fails the load rather than vanishing.

A module's methods are in classes it lists in its `serving` field, each method behind one of lup's doors (`lup/doors/README.md`). `Module.held(Kind)` gives every entry of a kind a module holds, each of its fields of that kind resolved over the module's own default.

## The verbs on modules

Everything a declaration writes is a layer on what's below it, naming only what it changes. A module, wherever it's written, means "that module below, with these changes": the fields it set apply, even at their default value, and every other field stays as below has it. A selection starting from `Kind()` keeps below's start and adds its operations after below's; one that starts over (`.default()`, `.all()`, `.only(…)`, `.of(…)`) replaces below's whole. Any other value replaces below's.

| Verb | Means |
|---|---|
| `Modules.default()` | lup's default modules |
| `Modules.only(*modules)` | exactly these, so a module a later release adds to the default doesn't come in |
| `Modules()` | the modules below, to change |
| `.add(*modules)` | a module that isn't there, or one a layer below gives, with this as a layer on it |
| `.drop(name, why=…)` | without the module of that name |
| `.edit(module, why=…)` | the module of that name, with `module` as a layer on it; another class is refused, so a swap is said with `.replace` |
| `.replace(name, module, why=…)` | another module in its place, from its own defaults |

A name that isn't there fails, naming those that are. What a field can't do: a field a base set can't be unset, since writing the default back sets it again; only a `.replace` with a fresh module unsets it.

## One grammar for every kind

Every collection a module holds is a selection (`Selection`): where its entries start from, and the operations changing them, recorded as written and resolved only when the module's owner reads it, so `Kind.default()` takes whatever a later release adds to the default and `Kind.only(…)` doesn't.

| Start or verb | Means |
|---|---|
| `Kind()` | the value below, to change |
| `Kind.default()` | the defaults: the module's own inside a module |
| `Kind.all()` | every entry lup knows |
| `Kind.only(*names)` | these known entries, and no other |
| `Kind.of(*entries, before=…, after=…)` | these entries, with no defaults: a module's own |
| `.add(*entries, before=…, after=…)` | beside the entries there; a name from below takes the entry as `.edit` would; one this layer gave already is an error |
| `.drop(*names, why=…)` | without these; a name not there is an error |
| `.replace(name, entry, why=…)` | `entry` in place of the one named |

Entries placed `before=` or `after=` another go there, whichever module holds it; the rest keep the order of their modules. A `Layer` is a model of settings changed field by field, as a module is.
