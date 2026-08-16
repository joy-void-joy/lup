"""Project-indexed model-method rule tests.

The rule states a shape exactly — a `def` in the body of a model we declare —
so what has to be pinned is the boundary of that shape: which declarations are
behaviour, which are the schema and therefore exempt, and which classes the
rule reaches at all. A defect here degrades silently toward *fewer* findings
rather than failing, which is why each case is named rather than left to one
"clean file" assertion.

The line a finding names is pinned by text rather than by number, because
reporting the `def` of a decorated member instead of its first decorator would
leave the accepted directive placement wedged between a decorator and what it
decorates.
"""

from pathlib import Path

from lup.codescan.behaviour import audit_model_methods
from lup.codescan.common import PythonSource
from lup.codescan.project import RuleFinding

MODEL_PREAMBLE = """
from abc import abstractmethod

from pydantic import BaseModel, computed_field, field_validator, model_validator


class Part(BaseModel):
    kind: str
"""


def source(text: str, module: str = "models") -> PythonSource:
    return PythonSource(path=Path(f"{module}.py"), module=module, text=text)


def reported(text: str, findings: list[RuleFinding]) -> list[str]:
    """Each finding as its kind and the line it names, rather than a number."""
    lines = text.splitlines()
    return [f"{finding.kind}:{lines[finding.line - 1].strip()}" for finding in findings]


def audit(body: str) -> list[str]:
    """Findings for a model whose body is the supplied members."""
    whole = MODEL_PREAMBLE + body
    return reported(whole, audit_model_methods([source(whole)]))


def test_a_field_only_model_is_clean() -> None:
    assert audit("    text: str = ''\n") == []


def test_a_plain_method_is_reported() -> None:
    assert audit("    def spell(self) -> str:\n        return self.kind\n") == [
        "missing:def spell(self) -> str:"
    ]


def test_a_property_is_reported_at_its_decorator() -> None:
    assert audit("    @property\n    def payload(self) -> str:\n        return ''\n") == [
        "missing:@property"
    ]


def test_an_abstract_method_is_reported() -> None:
    assert audit(
        "    @abstractmethod\n    def spell(self) -> str: ...\n"
    ) == ["missing:@abstractmethod"]


def test_a_classmethod_is_reported() -> None:
    assert audit(
        "    @classmethod\n    def build(cls) -> 'Part':\n        return cls(kind='')\n"
    ) == ["missing:@classmethod"]


def test_a_computed_field_is_reported() -> None:
    assert audit(
        "    @computed_field\n    @property\n    def size(self) -> int:\n        return 0\n"
    ) == ["missing:@computed_field"]


def test_a_model_validator_is_not_reported() -> None:
    assert (
        audit(
            "    @model_validator(mode='after')\n"
            "    def coherent(self) -> 'Part':\n"
            "        return self\n"
        )
        == []
    )


def test_a_field_validator_is_not_reported() -> None:
    assert (
        audit(
            "    @field_validator('kind')\n"
            "    @classmethod\n"
            "    def known(cls, kind: str) -> str:\n"
            "        return kind\n"
        )
        == []
    )


def test_a_def_nested_inside_a_member_is_not_reported_separately() -> None:
    assert audit(
        "    def spell(self) -> str:\n"
        "        def inner() -> str:\n"
        "            return ''\n"
        "        return inner()\n"
    ) == ["missing:def spell(self) -> str:"]


def test_a_class_we_do_not_declare_as_a_model_is_not_reported() -> None:
    assert (
        reported(
            "class Plain:\n    def act(self) -> None: ...\n",
            audit_model_methods([source("class Plain:\n    def act(self) -> None: ...\n")]),
        )
        == []
    )


def test_a_transitive_descendant_is_reported() -> None:
    whole = MODEL_PREAMBLE + (
        "\n\nclass TextPart(Part):\n    def spell(self) -> str:\n        return ''\n"
    )
    assert reported(whole, audit_model_methods([source(whole)])) == [
        "missing:def spell(self) -> str:"
    ]


def test_a_settings_descendant_is_reported() -> None:
    whole = (
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        "    name: str = ''\n\n"
        "    def warn(self) -> None: ...\n"
    )
    assert reported(whole, audit_model_methods([source(whole)])) == [
        "missing:def warn(self) -> None: ..."
    ]


def test_a_typed_suppression_covers_the_site() -> None:
    assert (
        audit(
            "    # lup: ignore[model-method] — reason\n"
            "    def spell(self) -> str:\n"
            "        return ''\n"
        )
        == []
    )


def test_a_bare_suppression_is_reported_as_untyped() -> None:
    assert audit(
        "    def spell(self) -> str:  # lup: ignore — reason\n        return ''\n"
    ) == ["untyped:def spell(self) -> str:  # lup: ignore — reason"]


def test_a_suppression_guarding_nothing_is_reported_as_spurious() -> None:
    assert audit(
        "    text: str = ''  # lup: ignore[model-method] — stale\n"
    ) == ["spurious:text: str = ''  # lup: ignore[model-method] — stale"]
