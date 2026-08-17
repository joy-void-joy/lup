"""Which models reach disk, and where the walk admits it cannot tell.

The walk exists because the by-hand answer kept being wrong in one direction:
a class reaches a file by being held, at some depth, by one a persistence call
names, and no search for pydantic's method names finds that. So what is pinned
here is the transitive reach, and — just as important — that a call it cannot
name is reported rather than passed over. A walk that silently resolved
nothing would answer "nothing is persisted", which is the one answer that
costs something.
"""

from pathlib import Path

from lup.codescan.common import PythonSource
from lup.devtools.dev.persistence import persistence_report

PREAMBLE = """
from pydantic import BaseModel, TypeAdapter

from lup.channels.models import publish_atomic
"""


def source(text: str, module: str = "sample") -> PythonSource:
    return PythonSource(path=Path(f"{module}.py"), module=module, text=text)


def reached(text: str) -> list[str]:
    whole = PREAMBLE + text
    return [
        name.removeprefix("sample.")
        for name in persistence_report([source(whole)]).reached
    ]


def unresolved(text: str) -> list[str]:
    whole = PREAMBLE + text
    return [site.argument for site in persistence_report([source(whole)]).unresolved]


def test_a_model_a_sink_names_is_a_root() -> None:
    assert reached(
        "class Record(BaseModel):\n    value: str\n\n"
        "def save(path):\n    publish_atomic(path, Record(value='x'))\n"
    ) == ["Record"]


def test_a_model_a_root_holds_is_reached() -> None:
    assert reached(
        "class Leaf(BaseModel):\n    value: str\n\n"
        "class Record(BaseModel):\n    leaf: Leaf\n\n"
        "def save(path):\n    publish_atomic(path, Record(leaf=Leaf(value='x')))\n"
    ) == ["Leaf", "Record"]


def test_a_container_field_is_descended_into() -> None:
    """The member is what persists; the list around it is not a model."""
    assert reached(
        "class Leaf(BaseModel):\n    value: str\n\n"
        "class Record(BaseModel):\n    leaves: list[Leaf]\n\n"
        "def save(path):\n    publish_atomic(path, Record(leaves=[]))\n"
    ) == ["Leaf", "Record"]


def test_a_subclass_of_a_reached_model_is_reached() -> None:
    """A field annotated with a base accepts any kind, so any kind is written."""
    assert reached(
        "class Leaf(BaseModel):\n    value: str\n\n"
        "class Special(Leaf):\n    extra: str\n\n"
        "class Record(BaseModel):\n    leaf: Leaf\n\n"
        "def save(path):\n    publish_atomic(path, Record(leaf=Special(value='x', extra='y')))\n"
    ) == ["Leaf", "Record", "Special"]


def test_reach_survives_a_depth_no_search_would_follow() -> None:
    """The shape that cost five rounds by hand: held three models deep."""
    assert reached(
        "class Invocation(BaseModel):\n    skill: str\n\n"
        "class Spec(BaseModel):\n    worker: Invocation\n\n"
        "class State(BaseModel):\n    spec: Spec\n\n"
        "def save(path, state):\n    publish_atomic(path, State(spec=Spec(worker=Invocation(skill='x'))))\n"
    ) == ["Invocation", "Spec", "State"]


def test_a_model_nothing_persists_is_absent() -> None:
    assert reached("class Loose(BaseModel):\n    value: str\n") == []


def test_a_type_adapter_names_its_model() -> None:
    assert reached(
        "class Record(BaseModel):\n    value: str\n\nADAPTER = TypeAdapter(Record)\n"
    ) == ["Record"]


def test_validating_on_the_class_names_it() -> None:
    assert reached(
        "class Record(BaseModel):\n    value: str\n\n"
        "def load(raw):\n    return Record.model_validate_json(raw)\n"
    ) == ["Record"]


def test_a_sink_argument_the_walk_cannot_name_is_reported() -> None:
    """Reported rather than skipped: silence here reads as 'nothing persists'."""
    assert unresolved(
        "class Record(BaseModel):\n    value: str\n\n"
        "def save(path, built):\n    publish_atomic(path, built_from(built))\n"
    ) == ["built_from(built)"]


def test_an_unresolved_sink_does_not_silently_widen_the_reach() -> None:
    assert (
        reached(
            "class Record(BaseModel):\n    value: str\n\n"
            "def save(path, built):\n    publish_atomic(path, built_from(built))\n"
        )
        == []
    )
