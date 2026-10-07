"""The shared bases: models and settings are frozen; a `MutableModel` is not."""

import pytest
from pydantic import ValidationError

from lup.types import Model, MutableModel, Settings


class Point(Model):
    x: int


class Box[T](Model):
    item: T


class Counter(MutableModel):
    count: int


class Paths(Settings, env_prefix="LUP_TEST_"):
    home: str = "default"


@pytest.mark.parametrize(
    ("value", "field"),
    [(Point(x=1), "x"), (Box[int](item=1), "item")],
)
def test_a_model_is_frozen_without_saying_so(value: Model, field: str) -> None:
    # Assigned by name: pyright refuses the plain assignment before it can run.
    with pytest.raises(ValidationError):
        setattr(value, field, 2)


def test_a_frozen_model_hashes_by_its_fields() -> None:
    assert hash(Point(x=1)) == hash(Point(x=1))


def test_a_mutable_model_can_change() -> None:
    counter = Counter(count=1)
    counter.count = 2
    assert counter.count == 2


def test_settings_read_the_environment_and_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUP_TEST_HOME", "/somewhere")
    paths = Paths()
    assert paths.home == "/somewhere"
    with pytest.raises(ValidationError):
        paths.home = "/elsewhere"
