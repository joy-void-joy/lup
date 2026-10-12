"""Checking requirements all at once, every probe stubbed."""

from typing import override

import pytest

from lup_dev import Requirement
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.requirements import (
    Needed,
    Printed,
    RequirementError,
    Tools,
    check,
)

NODE = Requirement(
    tool="node",
    version=">=22.18",
    probe=["node", "-p", "process.versions.node"],
    why="runs the rule engine",
    install="https://nodejs.org/en/download",
)
UV = Requirement(tool="uv", why="runs the project's tools", install="its installer")
CLIPBOARD = Requirement(
    any_of=["wl-copy", "xclip"], optional=True, why="copies a review"
)


class Stubbed(Tools):
    def __init__(
        self, programs: list[str], printed: dict[str, Printed] | None = None
    ) -> None:
        self.programs = programs
        self.printed = printed or {}
        self.ran: list[list[str]] = []

    @override
    def found(self, program: str) -> bool:
        return program in self.programs

    @override
    def run(self, command: list[str]) -> Printed:
        self.ran.append(command)
        return self.printed.get(command[0], Printed(code=127, output=""))


def needed(*requirements: Requirement) -> list[Needed]:
    return [Needed(module="code-rules", requirement=each) for each in requirements]


def test_requirements_met() -> None:
    tools = Stubbed(
        ["node", "uv", "xclip"], {"node": Printed(code=0, output="26.10.0\n")}
    )
    report = check(needed(NODE, UV, CLIPBOARD), tools).require()
    assert [(each.status, each.found) for each in report.checked] == [
        ("met", "26.10.0"),
        ("met", "uv"),
        ("met", "xclip"),
    ]
    assert tools.ran == [["node", "-p", "process.versions.node"]]


def test_a_missing_required_one_stops_naming_every_one_missing() -> None:
    report = check(needed(NODE, UV), Stubbed([]))
    assert [each.status for each in report.unmet] == ["missing", "missing"]
    with pytest.raises(RequirementError) as refused:
        report.require()
    message = str(refused.value)
    assert (
        "`node`, for `code-rules` (runs the rule engine): not on the `PATH`." in message
    )
    assert "Install: https://nodejs.org/en/download." in message
    assert "`uv`, for `code-rules` (runs the project's tools)" in message


def test_a_missing_optional_one_turns_its_feature_off() -> None:
    report = check(needed(CLIPBOARD), Stubbed([])).require()
    assert report.unmet == []
    assert [each.needed.requirement.named() for each in report.off] == [
        "wl-copy or xclip"
    ]


def test_a_version_too_old_is_unmet() -> None:
    tools = Stubbed(["node"], {"node": Printed(code=0, output="20.11.1\n")})
    with pytest.raises(RequirementError, match=r"takes >=22.18, found 20.11.1"):
        check(needed(NODE), tools).require()


def test_a_probe_printing_no_version_is_unmet() -> None:
    tools = Stubbed(["node"], {"node": Printed(code=0, output="v26 (current)\n")})
    [checked] = check(needed(NODE), tools).checked
    assert checked.status == "unreadable"
    assert "printed no version: 'v26 (current)'" in checked.described()
    failing = Stubbed(["node"], {"node": Printed(code=1, output="")})
    assert check(needed(NODE), failing).checked[0].status == "unreadable"


def test_two_modules_needing_one_tool_are_both_checked() -> None:
    newer = NODE.model_copy(update={"version": ">=24.12"})
    tools = Stubbed(["node"], {"node": Printed(code=0, output="22.18.0")})
    report = check(
        [
            Needed(module="code-rules", requirement=NODE),
            Needed(module="rooms", requirement=newer),
        ],
        tools,
    )
    assert [each.status for each in report.checked] == ["met", "wrong version"]


@pytest.mark.parametrize(
    ("fields", "failure"),
    [
        ({}, "names one `tool`"),
        ({"tool": "node", "any_of": ["nodejs"]}, "names one `tool`"),
        ({"tool": "node", "version": ">=22"}, "needs a `probe`"),
        (
            {"tool": "node", "version": "newest", "probe": ["node", "-v"]},
            "isn't a specifier",
        ),
    ],
)
def test_a_requirement_it_can_t_check_is_refused(
    fields: dict[str, object], failure: str
) -> None:
    with pytest.raises(ProjectError, match=failure):
        Requirement.model_validate(fields)
