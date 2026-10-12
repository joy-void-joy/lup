"""Modules as layers, and a declaration resolved from them."""

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

import pydantic
import pytest

import lup_dev
from lup_dev import (
    CodeRules,
    Core,
    Exemption,
    Exemptions,
    Gate,
    Module,
    Modules,
    Paths,
    Plain,
    Project,
    Pytest,
    Python,
    Requirement,
    Rules,
    Step,
    TestRoots,
    Uv,
)
from lup_dev.catalog.paths import CorePaths, PythonPaths
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.module import Origin
from lup_dev.declaration.resolve import Resolved, resolve


def drops(resolved: Resolved, module: str) -> list[str]:
    [selected] = [each for each in resolved.rules if each.module == module]
    return [
        name
        for operation in selected.rules.operations
        if operation.verb == "drop"
        for name in operation.names
    ]


def module(resolved: Resolved, name: str) -> Module:
    [found] = [each for each in resolved.modules if each.name == name]
    return found


class Ledger(Module):
    """Where work is recorded."""

    name = "ledger"

    directory: str = "ledger"


class Coordination(Module):
    """Agents working at once, through the ledger."""

    name = "coordination"
    requires: ClassVar[list[type[Module]]] = [Ledger]


class Narration(Module):
    """Turning a page into an episode."""

    name = "narration"
    requirements = [Requirement(tool="ffmpeg", why="encodes the episodes")]

    paths: Paths = Paths.of(data=["episodes/**"], protected=["**/pyproject.toml"])
    gate: Gate = Gate.of(
        Step(name="episodes", command=["check-episodes"]), after="pytest"
    )


# What a module is


def defined(name: str, namespace: dict[str, object]) -> type[Module]:
    """Define a module class from its namespace, as a `class` statement would."""
    return type(name, (Module,), namespace)


def test_a_module_with_a_plain_collection_is_refused() -> None:
    with pytest.raises(ProjectError) as refused:
        defined(
            "Listed",
            {
                "__doc__": "A module with a list.",
                "__annotations__": {"patterns": list[str]},
                "name": "listed",
                "patterns": [],
            },
        )
    message = str(refused.value)
    assert "`Listed` holds `patterns` as a plain collection" in message
    assert "a layer would replace it whole" in message
    assert "Make each a selection" in message


@pytest.mark.parametrize(
    "annotation",
    [
        list[str] | None,
        dict[str, int],
        set[str],
        frozenset[str],
        tuple[str, ...],
        Sequence[str],
    ],
)
def test_every_plain_collection_is_refused_optional_or_not(annotation: object) -> None:
    namespace: dict[str, object] = {
        "__doc__": "A module.",
        "__annotations__": {"held": annotation},
        "held": None,
        "name": "holding",
    }
    with pytest.raises(ProjectError, match=r"plain collection"):
        defined("Holding", namespace)


def test_a_module_with_a_selection_field_is_accepted() -> None:
    class Selecting(Module):
        """A module with a selection."""

        name = "selecting"

        rules: Rules = Rules.of("mine")

    assert Selecting().rules == Rules.of("mine")


def test_a_class_variable_list_is_not_a_field() -> None:
    class Needing(Module):
        """A module needing tools."""

        name = "needing"
        requires: ClassVar[list[type[Module]]] = [Ledger]
        requirements = [Requirement(tool="ffmpeg")]

    assert Needing.requires == [Ledger]


def test_a_module_without_a_name_or_sentence_or_default_is_refused() -> None:
    with pytest.raises(ProjectError, match=r"has no `name`"):
        defined("Nameless", {"__doc__": "No name."})
    with pytest.raises(ProjectError, match=r"has no docstring"):
        defined("Silent", {"name": "silent"})
    with pytest.raises(ProjectError, match=r"gives `share` no default"):
        defined(
            "Budgets",
            {
                "__doc__": "Shares.",
                "__annotations__": {"share": float},
                "name": "budgets",
            },
        )


def test_a_module_s_sentence_is_its_docstring_s_first_paragraph() -> None:
    assert Narration.sentence() == "Turning a page into an episode."


def test_project_and_modules_refuse_fields_they_don_t_know() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"modlues"):
        Project.model_validate({"modlues": []})
    with pytest.raises(pydantic.ValidationError, match=r"rule"):
        CodeRules.model_validate({"rule": Rules()})


# Modules as layers


def test_a_module_over_another_changes_only_the_fields_it_set() -> None:
    below = Python(runner=Plain(), tests=TestRoots.of(Pytest(root=Path("t"))))
    layered = Python(tests=TestRoots().add(Pytest(root=Path("u")))).over(below)
    assert layered.runner == Plain()
    assert [each.entry.root for each in layered.tests.resolve([], [])] == [
        Path("t"),
        Path("u"),
    ]


def test_a_field_given_at_its_default_value_counts_as_set() -> None:
    assert Python(runner=Uv()).over(Python(runner=Plain())).runner == Uv()


def test_edit_on_a_module_is_that_module_with_a_layer_on_it() -> None:
    ours = CodeRules(rules=Rules().drop("collection-loop"))
    edited = ours.edit(CodeRules(rules=Rules().drop("tuple-shape")), why="legacy code")
    assert [
        operation.names
        for operation in edited.rules.operations
        if operation.verb == "drop"
    ] == [
        ["collection-loop"],
        ["tuple-shape"],
    ]
    assert edited.origins.of("rules") == Origin(field="rules", why="legacy code")


def test_edit_with_another_class_points_at_replace() -> None:
    def held(module: Module) -> Module:
        return module

    with pytest.raises(ProjectError, match=r'`.replace\("python", …\)`'):
        held(Python()).edit(Core())


def test_modules_edit_needs_the_module_there() -> None:
    with pytest.raises(
        ProjectError, match=r"`Modules.edit` names `ledger`, which isn't there"
    ):
        resolve(Project(modules=Modules.default().edit(Ledger(directory="work"))))
    resolved = resolve(
        Project(modules=Modules.default().add(Ledger()).edit(Ledger(directory="work")))
    )
    ledger = module(resolved, "ledger")
    assert isinstance(ledger, Ledger)
    assert ledger.directory == "work"
    assert ledger.origins.each == [Origin(field="directory", position=2)]


def test_modules_edit_with_another_class_points_at_replace() -> None:
    class Pythonish(Python):
        """Python, another way."""

    with pytest.raises(ProjectError, match=r"`.edit` puts a `Pythonish` on `Python`"):
        resolve(Project(modules=Modules.default().edit(Pythonish())))


# A declaration resolved


def test_the_defaults_resolve_to_lup_s_modules_and_parts() -> None:
    resolved = resolve(Project())
    assert [each.name for each in resolved.modules] == ["core", "python", "code-rules"]
    assert resolved.paths.protected == [
        *CorePaths().protected,
        *PythonPaths().protected,
    ]
    assert resolved.paths.operator_documents == ["DESIGN.md", "AGENTS.md"]
    assert resolved.paths.conftest == ["conftest.py"]
    assert resolved.paths.excluded == []
    assert [each.name for each in resolved.gate] == [
        "engine",
        "rules",
        "ruff",
        "format",
        "pyright",
        "pytest",
        "lint-imports",
    ]
    assert resolved.tests == [Pytest(root=Path("tests"))]
    assert resolved.runner == Uv()
    assert resolved.rules[0].rules == Rules.default()
    assert resolved.exempt == []
    assert resolved.conditions == []
    assert resolved.asks == "every"
    assert [(each.module, each.requirement.tool) for each in resolved.requirements] == [
        ("code-rules", "node"),
        ("python", "uv"),
    ]


def test_core_and_python_split_lup_s_protected_paths() -> None:
    core = Core().paths.resolve(Paths())
    python = Python().paths.resolve(Paths())
    assert "**/pyproject.toml" in python["protected"]
    assert "**/pyproject.toml" not in core["protected"]
    assert ".github/**" in core["protected"]
    assert core["protected"] == CorePaths().protected
    assert python["protected"] == PythonPaths().protected


def test_the_note_s_layers_resolve_to_both_drops_and_both_exemptions() -> None:
    ours = CodeRules(
        rules=Rules().drop("collection-loop"),
        exempt=Exemptions().add(
            Exemption(rule="set-shape", paths=["**/schedule/**"], why="a schedule")
        ),
    )
    project = Project(
        modules=Modules.default()
        .edit(ours)
        .edit(
            CodeRules(
                rules=Rules().drop("tuple-shape"),
                exempt=Exemptions().add(
                    Exemption(rule="tuple-shape", paths=["src/legacy/**"], why="legacy")
                ),
            ),
            why="the legacy code",
        ),
    )
    resolved = resolve(project)
    assert drops(resolved, "code-rules") == ["collection-loop", "tuple-shape"]
    assert resolved.rules[0].rules.start.kind == "default"
    assert [each.rule for each in resolved.exempt] == ["set-shape", "tuple-shape"]
    assert module(resolved, "code-rules").origins.each == [
        Origin(field="rules", position=2, why="the legacy code"),
        Origin(field="exempt", position=2, why="the legacy code"),
    ]
    assert module(resolved, "python").origins.each == []


def test_a_shared_base_and_a_project_stack_with_each_value_s_layer() -> None:
    base = (
        Modules.default()
        .edit(CodeRules(rules=Rules().drop("collection-loop", why="pipelines loop")))
        .edit(Python(runner=Plain()), why="no uv here")
    )
    project = Project(
        modules=base.add(Narration()).edit(
            CodeRules(rules=Rules().drop("tuple-shape"))
        ),
    )
    resolved = resolve(project)
    assert drops(resolved, "code-rules") == ["collection-loop", "tuple-shape"]
    rules = resolved.rules[0].rules
    assert [
        operation.why for operation in rules.operations if operation.verb == "drop"
    ] == ["pipelines loop", None]
    assert module(resolved, "code-rules").origins.of("rules") == Origin(
        field="rules", position=4
    )
    assert module(resolved, "python").origins.of("runner") == Origin(
        field="runner", position=2, why="no uv here"
    )
    assert resolved.runner == Plain()
    assert [each.requirement.named() for each in resolved.requirements] == [
        "node",
        "ffmpeg",
    ]


def test_an_edit_inside_a_layer_keeps_its_own_reason() -> None:
    ours = CodeRules(rules=Rules().drop("regex")).edit(
        CodeRules(
            exempt=Exemptions().add(Exemption(rule="elif", paths=["a/**"], why="a"))
        ),
        why="inner",
    )
    resolved = resolve(Project(modules=Modules.default().edit(ours, why="outer")))
    origins = module(resolved, "code-rules").origins
    assert origins.of("rules") == Origin(field="rules", position=1, why="outer")
    assert origins.of("exempt") == Origin(field="exempt", position=1, why="inner")


def test_a_later_layer_s_scalar_wins() -> None:
    modules = Modules.default().edit(Python(runner=Plain())).edit(Python(runner=Uv()))
    assert resolve(Project(modules=modules)).runner == Uv()


def test_a_layer_starting_over_replaces_what_s_below() -> None:
    modules = (
        Modules.default()
        .edit(
            CodeRules(
                rules=Rules().drop("regex"),
                exempt=Exemptions().add(Exemption(rule="elif", paths=["a"], why="a")),
            )
        )
        .edit(CodeRules(rules=Rules.only("regex"), exempt=Exemptions.of()))
        .edit(Python(gate=Gate.of(Step(name="pytest", command=["pytest"]))))
    )
    resolved = resolve(Project(modules=modules))
    assert resolved.rules[0].rules == Rules.only("regex")
    assert resolved.exempt == []
    assert [each.name for each in resolved.gate] == ["pytest"]


def test_modules_only_is_an_exact_list_with_settings() -> None:
    resolved = resolve(Project(modules=Modules.only(Core(), Python(runner=Plain()))))
    assert [each.name for each in resolved.modules] == ["core", "python"]
    assert resolved.rules == []
    assert resolved.runner == Plain()
    assert module(resolved, "python").origins.of("runner") == Origin(
        field="runner", position=0
    )


def test_a_module_added_starts_from_its_own_defaults() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Ledger(), Narration())))
    assert [each.name for each in resolved.modules] == [
        "core",
        "python",
        "code-rules",
        "ledger",
        "narration",
    ]
    assert module(resolved, "ledger") == Ledger()
    assert "episodes/**" in resolved.paths.data


def test_a_module_added_goes_where_it_s_placed() -> None:
    modules = Modules.default().add(Ledger(), before="python")
    assert [each.name for each in resolve(Project(modules=modules)).modules] == [
        "core",
        "ledger",
        "python",
        "code-rules",
    ]


def test_all_is_every_module_lup_ships() -> None:
    assert [each.name for each in resolve(Project(modules=Modules.all())).modules] == [
        "core",
        "python",
        "code-rules",
    ]


def test_adding_a_module_already_there_is_refused() -> None:
    with pytest.raises(
        ProjectError, match=r"`Modules.add` names `python`, already there"
    ):
        resolve(Project(modules=Modules.default().add(Python())))


def test_replace_puts_another_module_in_place_from_its_own_defaults() -> None:
    class Lean(Module):
        """Lean's tools."""

        name = "lean"

        gate: Gate = Gate.of(Step(name="lake", command=["lake", "build"]))

    resolved = resolve(
        Project(
            modules=Modules.default().replace("python", Lean(), why="a Lean project")
        )
    )
    assert [each.name for each in resolved.modules] == ["core", "lean", "code-rules"]
    assert [each.name for each in resolved.gate] == ["lake"]
    assert resolved.runner == Plain()
    assert "**/pyproject.toml" not in resolved.paths.protected


def test_steps_from_another_module_go_where_they_re_placed() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Narration())))
    names = [each.name for each in resolved.gate]
    assert names[names.index("pytest") + 1] == "episodes"


def test_a_pattern_from_two_modules_is_one_pattern() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Narration())))
    assert resolved.paths.protected.count("**/pyproject.toml") == 1


def test_a_name_from_two_modules_is_refused_naming_both() -> None:
    class Linting(Module):
        """Another ruff."""

        name = "linting"

        gate: Gate = Gate.of(Step(name="ruff", command=["ruff"]))

    with pytest.raises(ProjectError, match=r"`ruff` from `python` and `linting`"):
        resolve(Project(modules=Modules.default().add(Linting())))


def test_two_modules_exempting_one_rule_each_keep_theirs() -> None:
    class Lifting(Module):
        """Lifting a rule."""

        name = "lifting"

        exempt: Exemptions = Exemptions.of(
            Exemption(rule="regex", paths=["b/**"], why="b")
        )

    modules = Modules.default().edit(
        CodeRules(
            exempt=Exemptions().add(Exemption(rule="regex", paths=["a/**"], why="a"))
        )
    )
    resolved = resolve(Project(modules=modules.add(Lifting())))
    assert [(each.rule, each.paths) for each in resolved.exempt] == [
        ("regex", ["a/**"]),
        ("regex", ["b/**"]),
    ]


def test_core_is_required() -> None:
    class Kernel(Core):
        """Another core."""

    for modules in [
        Modules.default().drop("core"),
        Modules.only(Python(), CodeRules()),
        Modules.default().replace("core", Kernel()),
    ]:
        with pytest.raises(ProjectError, match=r"`Core` is required"):
            resolve(Project(modules=modules))


def test_a_required_module_missing_is_refused_naming_both() -> None:
    with pytest.raises(
        ProjectError, match=r"`coordination` requires `ledger`, which isn't selected"
    ):
        resolve(Project(modules=Modules.default().add(Coordination())))
    resolved = resolve(Project(modules=Modules.default().add(Ledger(), Coordination())))
    assert [each.name for each in resolved.modules][-2:] == ["ledger", "coordination"]
    with pytest.raises(ProjectError, match=r"`coordination` requires `ledger`"):
        resolve(
            Project(
                modules=Modules.default().add(Ledger(), Coordination()).drop("ledger")
            )
        )


def test_modules_requiring_each_other_in_a_cycle_are_refused() -> None:
    class Hen(Module):
        """The hen."""

        name = "hen"

    class Egg(Module):
        """The egg."""

        name = "egg"
        requires: ClassVar[list[type[Module]]] = [Hen]

    Hen.requires = [Egg]
    with pytest.raises(
        ProjectError, match=r"cycle: `hen` requires `egg` requires `hen`"
    ):
        resolve(Project(modules=Modules.default().add(Hen(), Egg())))


def test_one_runner_at_most() -> None:
    class Poetry(Plain):
        """Through poetry."""

    class Running(Module):
        """Another runner."""

        name = "running"

        runner: Plain = Poetry()

    with pytest.raises(
        ProjectError, match=r"`python` and `running` each give a runner"
    ):
        resolve(Project(modules=Modules.default().add(Running())))
    assert resolve(Project(modules=Modules.default().drop("python"))).runner == Plain()


def test_a_runner_brings_its_requirements() -> None:
    resolved = resolve(Project(modules=Modules.default().edit(Python(runner=Plain()))))
    assert [each.requirement.named() for each in resolved.requirements] == ["node"]


def test_conditions_are_an_address_any_module_fills() -> None:
    modules = (
        Modules.default()
        .edit(Core(conditions="audiobook.conditions"))
        .add(Ledger(conditions="ledger.conditions"))
    )
    assert resolve(Project(modules=modules)).conditions == [
        "audiobook.conditions",
        "ledger.conditions",
    ]


def test_asks_keeps_its_meaning() -> None:
    assert resolve(Project(asks="protected")).asks == "protected"


@pytest.mark.parametrize("dropped", ["python", "code-rules"])
def test_dropping_a_module_drops_its_parts(dropped: str) -> None:
    resolved = resolve(Project(modules=Modules.default().drop(dropped)))
    assert dropped not in [each.name for each in resolved.modules]
    assert all(each.module != dropped for each in resolved.requirements)
    match dropped:
        case "python":
            assert resolved.gate == []
            assert resolved.tests == []
            assert resolved.paths.python == []
            assert "**/pyproject.toml" not in resolved.paths.protected
        case _:
            assert resolved.rules == []
            assert resolved.exempt == []


def test_the_front_door_imports_only_the_declaration_s_models() -> None:
    listed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys, lup_dev; print(json.dumps(sorted(sys.modules)))",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    imported = json.loads(listed.stdout)
    assert "lup_dev.declaration.module" in imported
    for heavy in [
        "lup_dev.policy",
        "lup_dev.codescan",
        "lup_dev.declaration.resolve",
        "lup_dev.declaration.load",
        "typer",
    ]:
        assert heavy not in imported
    assert set(lup_dev.__all__) <= set(dir(lup_dev))
