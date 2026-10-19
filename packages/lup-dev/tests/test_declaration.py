"""Modules as layers, and a declaration resolved from them."""

import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar

import pydantic
import pytest
from pydantic import ValidationError

import lup_dev
from lup.rooms.container import Mount
from lup_dev import (
    Actions,
    CodeRules,
    Core,
    Credentials,
    Exemption,
    Exemptions,
    Gate,
    Guidance,
    Module,
    Modules,
    Package,
    Packages,
    Paths,
    Patterns,
    Plain,
    Project,
    Pytest,
    Python,
    Refs,
    RemovedTools,
    Repositories,
    Repository,
    Requirement,
    Rules,
    Section,
    Session,
    Step,
    TestRoots,
    Uv,
)
from lup_dev.catalog.credentials import CredentialDefaults
from lup_dev.catalog.paths import CorePaths, PythonPaths
from lup_dev.catalog.room import SessionDefaults, StandardMachine
from lup_dev.catalog.rules import DefaultRules
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Drop
from lup_dev.declaration.kinds import lup_actions
from lup_dev.declaration.load import load
from lup_dev.declaration.module import Origin
from lup_dev.declaration.modules.code_rules import lup_default
from lup_dev.declaration.requirements import Printed, Tools
from lup_dev.declaration.resolve import Resolved, SessionChoices, resolve
from lup_dev.declaration.runner import (
    Interpreter,
    Prefixed,
    RoomNeeds,
    RunnerError,
)
from lup_dev.host.protocol import Action, Limits, actions


def layered(resolved: Resolved, module: str) -> list[Drop]:
    """Return the drops a module's layers make, after its own default's."""
    [selected] = [each for each in resolved.rules if each.module == module]
    own = len(selected.default.operations)
    return [
        operation
        for operation in selected.rules.operations[own:]
        if isinstance(operation, Drop)
    ]


def drops(resolved: Resolved, module: str) -> list[str]:
    return [name for operation in layered(resolved, module) for name in operation.names]


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


def test_a_default_starting_from_itself_is_refused_at_the_class_definition() -> None:
    def declared() -> type[Module]:
        class Circular(Module):
            """Its own default, and a step more."""

            name = "circular"

            gate: Gate = Gate.default().add(Step(name="x", command=["true"]))

        return Circular

    with pytest.raises(ProjectError) as refused:
        declared()
    message = str(refused.value)
    assert (
        "`Circular` starts its own default for `gate` from `Gate.default()`, "
        "which is that default itself"
    ) in message
    assert "Start each from `Kind.of(…)` or `Kind()`" in message


@pytest.mark.parametrize(
    ("field", "default", "named"),
    [
        ("gate", Gate.default(), "`gate` from `Gate.default()`"),
        (
            "paths",
            Paths.default().add(data=["episodes/**"]),
            "`paths.data` from `Patterns.default()`",
        ),
        (
            "paths",
            Paths(scratch=Patterns.default().add("renders/**")),
            "`paths.scratch` from `Patterns.default()`",
        ),
        (
            "session",
            Session(removed_tools=RemovedTools.default().add("Bash")),
            "`session.removed_tools` from `RemovedTools.default()`",
        ),
    ],
)
def test_a_default_starting_from_itself_is_refused_naming_the_field(
    field: str, default: Gate | Paths | Session, named: str
) -> None:
    namespace: dict[str, object] = {
        "__doc__": "A module.",
        "__annotations__": {field: type(default)},
        field: default,
        "name": "circular",
    }
    with pytest.raises(
        ProjectError, match=r"`Circular` starts its own default"
    ) as refused:
        defined("Circular", namespace)
    assert named in str(refused.value)


def test_a_default_starting_from_nothing_or_over_is_accepted() -> None:
    class Own(Module):
        """Its own entries, written each way."""

        name = "own"

        gate: Gate = Gate().add(Step(name="x", command=["true"]))
        paths: Paths = Paths().add(data=["episodes/**"])
        rules: Rules = Rules.all().drop("regex")

    assert Own().gate.start.kind == "below"


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
    assert [each.name for each in resolved.modules] == [
        "core",
        "python",
        "code-rules",
        "github",
        "transcripts",
        "private",
    ]
    assert resolved.paths.protected == [
        *CorePaths().protected,
        *PythonPaths().protected,
    ]
    assert resolved.paths.operator_documents == ["DESIGN.md", "AGENTS.md"]
    assert resolved.paths.conftest == ["conftest.py"]
    assert resolved.paths.excluded == []
    assert [each.name for each in resolved.gate] == [
        "rules",
        "format",
        "pytest",
        "lint-imports",
        "private",
    ]
    assert resolved.tests == [Pytest(root=Path("tests"))]
    assert resolved.runner == Uv()
    [code_rules] = resolved.rules
    assert code_rules.rules == code_rules.default == lup_default()
    assert lup_default() == Rules.all().drop(
        "runtime-mention", why=DefaultRules().left_out[0].why
    )
    assert resolved.exempt == []
    assert resolved.conditions == []
    assert (resolved.held, resolved.flagged) == (
        ["protected", "operator", "ignore"],
        ["new-file", "whole-file", "public-api", "private"],
    )
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
    assert resolved.rules[0].rules.start.kind == "all"
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
    assert [operation.why for operation in layered(resolved, "code-rules")] == [
        "pipelines loop",
        None,
    ]
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
    assert [each.name for each in resolved.gate] == ["pytest", "private"]


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
        "github",
        "transcripts",
        "private",
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
        "github",
        "transcripts",
        "private",
    ]


def test_all_is_every_module_lup_ships() -> None:
    assert [each.name for each in resolve(Project(modules=Modules.all())).modules] == [
        "core",
        "python",
        "code-rules",
        "github",
        "transcripts",
        "private",
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
    assert [each.name for each in resolved.modules] == [
        "core",
        "lean",
        "code-rules",
        "github",
        "transcripts",
        "private",
    ]
    assert [each.name for each in resolved.gate] == ["lake", "private"]
    assert resolved.runner == Plain()
    assert "**/pyproject.toml" not in resolved.paths.protected


class Mine(Module):
    """A module whose own defaults are written from the value below."""

    name = "mine"

    gate: Gate = Gate().add(Step(name="x", command=["true"]))


class Episodes(Module):
    """Episodes as data, renders as scratch, written from the value below."""

    name = "episodes"

    paths: Paths = Paths().add(data=["episodes/**"], scratch=["renders/**"])


def own_steps(resolved: Resolved) -> list[str]:
    """Return the gate's steps that aren't lup's own, in order."""
    lups = [each.name for each in resolve(Project()).gate]
    return [each.name for each in resolved.gate if each.name not in lups]


def test_a_module_s_own_default_written_from_below_applies_once() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Mine())))
    assert own_steps(resolved) == ["x"]


def test_a_module_s_own_paths_written_from_below_apply_once() -> None:
    own = Episodes().paths
    assert own.resolve(own)["data"] == ["episodes/**"]
    resolved = resolve(Project(modules=Modules.default().add(Episodes())))
    assert resolved.paths.data.count("episodes/**") == 1
    assert resolved.paths.scratch[-1:] == ["renders/**"]


@pytest.mark.parametrize(
    ("layer", "steps"),
    [
        (Gate().add(Step(name="y", command=["true"])), ["x", "y"]),
        (Gate.default().add(Step(name="y", command=["true"])), ["x", "y"]),
        (Gate().drop("x"), []),
        (Gate.of(Step(name="y", command=["true"])), ["y"]),
    ],
)
def test_a_project_s_edit_on_a_default_written_from_below_applies_once(
    layer: Gate, steps: list[str]
) -> None:
    modules = Modules.default().add(Mine()).edit(Mine(gate=layer))
    assert own_steps(resolve(Project(modules=modules))) == steps


def test_a_project_s_edit_on_paths_written_from_below_applies_once() -> None:
    modules = (
        Modules.default()
        .add(Episodes())
        .edit(Episodes(paths=Paths().add(data=["takes/**"])))
        .edit(Episodes(paths=Paths().drop(scratch=["renders/**"])))
    )
    resolved = resolve(Project(modules=modules))
    assert resolved.paths.data[-2:] == ["episodes/**", "takes/**"]
    assert "renders/**" not in resolved.paths.scratch


def test_a_project_s_modules_from_below_start_from_lup_s() -> None:
    resolved = resolve(Project(modules=Modules().add(Ledger())))
    assert [each.name for each in resolved.modules] == [
        *(each.name for each in resolve(Project()).modules),
        "ledger",
    ]


def test_steps_from_another_module_go_where_they_re_placed() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Narration())))
    names = [each.name for each in resolved.gate]
    assert names[names.index("pytest") + 1] == "episodes"


def test_a_pattern_from_two_modules_is_one_pattern() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Narration())))
    assert resolved.paths.protected.count("**/pyproject.toml") == 1


def test_a_name_from_two_modules_is_refused_naming_both() -> None:
    class Linting(Module):
        """Another pytest."""

        name = "linting"

        gate: Gate = Gate.of(Step(name="pytest", command=["pytest"]))

    with pytest.raises(ProjectError, match=r"`pytest` from `python` and `linting`"):
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


class AskedUv(Tools):
    """uv's answers by the words after `--directory <root>`, each command kept."""

    def __init__(self, answers: dict[str, Printed]) -> None:
        self.answers = answers
        self.asked: list[list[str]] = []

    def found(self, program: str) -> bool:
        return True

    def run(self, command: list[str]) -> Printed:
        self.asked.append(command)
        return self.answers[" ".join(command[6:])]


def test_uv_mounts_its_interpreters_and_cache_where_uv_keeps_them(
    tmp_path: Path,
) -> None:
    root = tmp_path / "work" / "tree"
    store = tmp_path / "data" / "uv" / "python"
    cache = tmp_path / "cache" / "uv"
    tools = AskedUv(
        {
            "python dir": Printed(code=0, output=f"{store}\n"),
            "cache dir": Printed(code=0, output=f"{cache}\n"),
            "python find": Printed(code=0, output=f"{root}/.venv/bin/python\n"),
        }
    )

    needs = Uv().room(root, tools)

    assert needs == RoomNeeds(
        mounts=[Mount(source=store, read_only=True), Mount(source=cache)],
        env={
            "UV_CACHE_DIR": str(cache),
            "UV_PYTHON_INSTALL_DIR": str(store),
            "UV_PYTHON_DOWNLOADS": "never",
        },
        interpreter=Interpreter(
            path=root / ".venv" / "bin" / "python",
            remedy=(
                "run `uv sync --managed-python` in the project, which remakes "
                "`.venv` on a Python uv manages, installing one if there's none"
            ),
        ),
    )
    assert cache.is_dir()
    assert tools.asked == [
        ["env", "-u", "VIRTUAL_ENV", "uv", "--directory", str(root), *words]
        for words in [["python", "dir"], ["cache", "dir"], ["python", "find"]]
    ]


def test_uv_failing_to_answer_is_said(tmp_path: Path) -> None:
    tools = AskedUv({"python dir": Printed(code=2, output="")})
    with pytest.raises(
        RunnerError,
        match=r"`env -u VIRTUAL_ENV uv --directory .* python dir` failed with status 2",
    ):
        Uv().room(tmp_path, tools)


def test_a_plain_runner_mounts_nothing_and_a_kept_one_refuses(tmp_path: Path) -> None:
    tools = AskedUv({})
    assert Plain().room(tmp_path, tools) == RoomNeeds()
    with pytest.raises(RunnerError, match="can't say what a room mounts"):
        Prefixed.of(Uv()).room(tmp_path, tools)
    assert tools.asked == []


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


def test_what_is_held_and_flagged_is_named_once_and_checked_as_it_loads() -> None:
    held = resolve(Project(held=["protected", "regex"], flagged=["new-file"]))
    assert (held.held, held.flagged) == (["protected", "regex"], ["new-file"])
    with pytest.raises(ValidationError, match="name nothing held or flagged"):
        Project(held=["Protected Paths"])
    with pytest.raises(
        ValidationError, match=r"\['new-file'\] are both held and flagged"
    ):
        Project(held=["new-file"])


@pytest.mark.parametrize("dropped", ["python", "code-rules"])
def test_dropping_a_module_drops_its_parts(dropped: str) -> None:
    resolved = resolve(Project(modules=Modules.default().drop(dropped)))
    assert dropped not in [each.name for each in resolved.modules]
    assert all(each.module != dropped for each in resolved.requirements)
    packages = [each.name for each in resolved.packages]
    match dropped:
        case "python":
            assert [each.name for each in resolved.gate] == ["private"]
            assert resolved.tests == []
            assert resolved.paths.python == []
            assert "**/pyproject.toml" not in resolved.paths.protected
            assert "uv" not in packages
        case _:
            assert resolved.rules == []
            assert resolved.exempt == []
            assert "nodejs" not in packages


# The room's parts: packages, session settings, guidance


def machine() -> list[str]:
    return [name for group in StandardMachine().groups for name in group.names]


def test_the_image_is_the_standard_machine_and_each_requirement_s_package() -> None:
    resolved = resolve(Project())
    assert [each.name for each in resolved.packages] == [*machine(), "nodejs", "uv"]
    assert resolved.packages[0] == Package(
        name="bash", why=StandardMachine().groups[0].why
    )
    assert resolved.packages[-2] == Package(
        name="nodejs", why="provides `node` for `code-rules`: runs the rule engine"
    )


def test_a_package_from_two_places_is_one_package_the_first_s() -> None:
    class Studio(Module):
        """The studio."""

        name = "studio"
        requirements = [
            Requirement(tool="ffmpeg", why="encodes", package="ffmpeg"),
            Requirement(tool="node", package="nodejs"),
        ]

        packages: Packages = Packages.of(
            Package(name="ffmpeg", why="encodes the episodes"),
            Package(name="git", why="tags each episode"),
        )

    resolved = resolve(Project(modules=Modules.default().add(Studio())))
    names = [each.name for each in resolved.packages]
    assert [names.count(name) for name in ["ffmpeg", "git", "nodejs"]] == [1, 1, 1]
    assert names.index("ffmpeg") < names.index("nodejs")
    by_name = {each.name: each.why for each in resolved.packages}
    assert by_name["ffmpeg"] == "encodes the episodes"
    assert by_name["git"] == StandardMachine().groups[1].why


def test_a_requirement_without_a_package_brings_none() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Narration())))
    assert "ffmpeg" not in [each.name for each in resolved.packages]


def test_a_layer_changes_core_s_packages_where_they_stand() -> None:
    layer = Core(
        packages=Packages()
        .drop("emacs-nox", why="nobody here uses it")
        .add(Package(name="graphviz", why="draws the pipeline"))
    )
    resolved = resolve(Project(modules=Modules.default().edit(layer)))
    names = [each.name for each in resolved.packages]
    kept = [name for name in machine() if name != "emacs-nox"]
    assert names == [*kept, "graphviz", "nodejs", "uv"]


def test_session_settings_are_lup_s_by_default() -> None:
    assert resolve(Project()).session == SessionChoices(
        subagent_cache="1h",
        auto_memory=False,
        idle_compaction=False,
        removed_tools=SessionDefaults().removed_tools,
        account_connectors=False,
    )
    assert SessionDefaults().removed_tools[:5] == [
        "Artifact",
        "SendFeedback",
        "Workflow",
        "ScheduleWakeup",
        "ReportFindings",
    ]


def test_a_session_layer_changes_only_the_fields_it_sets() -> None:
    modules = Modules.default().edit(
        Core(session=Session(auto_memory=True)), why="this project keeps notes"
    )
    resolved = resolve(Project(modules=modules))
    assert resolved.session == SessionChoices(
        subagent_cache="1h",
        auto_memory=True,
        idle_compaction=False,
        removed_tools=SessionDefaults().removed_tools,
        account_connectors=False,
        declared=["auto_memory"],
    )
    assert module(resolved, "core").origins.of("session") == Origin(
        field="session", position=1, why="this project keeps notes"
    )


def test_the_session_says_which_fields_some_layer_declared() -> None:
    def declared(modules: Modules) -> list[str]:
        return resolve(Project(modules=modules)).session.declared

    assert declared(Modules.default()) == []
    assert declared(
        Modules.default().edit(Core(session=Session(auto_memory=False)))
    ) == ["auto_memory"]
    assert declared(
        Modules.default()
        .edit(Core(session=Session(account_connectors=True)))
        .edit(Core(session=Session(subagent_cache="5m")))
        .edit(Core(paths=Paths().add(scratch=["notes/**"])))
    ) == ["subagent_cache", "account_connectors"]
    assert declared(
        Modules.default().edit(
            Core(session=Session(removed_tools=RemovedTools().add("CronCreate")))
        )
    ) == ["removed_tools"]
    assert declared(
        Modules.default().replace("core", Core(session=Session(auto_memory=True)))
    ) == ["auto_memory"]


def test_a_declared_field_that_isnt_a_session_setting_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"`memory` aren't session"):
        SessionChoices(
            subagent_cache="1h",
            auto_memory=False,
            idle_compaction=False,
            removed_tools=[],
            account_connectors=False,
            declared=["memory"],
        )


def test_a_project_turns_the_account_s_connectors_on_in_a_layer() -> None:
    modules = Modules.default().edit(
        Core(session=Session(account_connectors=True)),
        why="this project reads the operator's calendar",
    )
    session = resolve(Project(modules=modules)).session
    assert session.account_connectors is True
    assert session.removed_tools == SessionDefaults().removed_tools


def test_removed_tools_are_a_selection_each_layer_adds_to_or_drops_from() -> None:
    base = Modules.default().edit(
        Core(session=Session(removed_tools=RemovedTools().add("CronCreate")))
    )
    modules = base.edit(
        Core(
            session=Session(
                subagent_cache="5m",
                removed_tools=RemovedTools().drop("Workflow", why="we run workflows"),
            )
        )
    )
    session = resolve(Project(modules=modules)).session
    lups = [name for name in SessionDefaults().removed_tools if name != "Workflow"]
    assert session.removed_tools == [*lups, "CronCreate"]
    assert session.subagent_cache == "5m"
    assert session.auto_memory is False


def test_removed_tools_default_is_lup_s_and_of_starts_over() -> None:
    def removed(tools: RemovedTools) -> list[str]:
        layer = Core(session=Session(removed_tools=tools))
        return resolve(
            Project(modules=Modules.default().edit(layer))
        ).session.removed_tools

    assert removed(RemovedTools.default().drop("Artifact")) == [
        name for name in SessionDefaults().removed_tools if name != "Artifact"
    ]
    assert removed(RemovedTools.of("NotebookEdit")) == ["NotebookEdit"]
    with pytest.raises(ProjectError, match=r"`RemovedTools.drop` names `Bash`"):
        removed(RemovedTools().drop("Bash"))


def test_session_settings_from_two_modules_are_refused() -> None:
    class Sessions(Module):
        """Another way to run sessions."""

        name = "sessions"

        session: Session = Session(auto_memory=True)

    with pytest.raises(
        ProjectError, match=r"`core` and `sessions` each give session settings"
    ):
        resolve(Project(modules=Modules.default().add(Sessions())))


def test_the_resolved_session_holds_every_session_setting() -> None:
    assert list(SessionChoices.model_fields) == [*Session.model_fields, "declared"]


def test_a_misspelled_session_setting_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"auto_memroy"):
        Session.model_validate({"auto_memroy": True})


# The limits on the operator's credentials


EVERY_BUT_LUP_S_WITHHELD: list[Action] = [
    "fetch",
    "push",
    "read-issues",
    "file-issue",
    "comment",
    "draft-pull-request",
]


def limits(modules: Modules) -> Limits:
    return resolve(Project(modules=modules)).limits


def test_credentials_are_lup_s_by_default() -> None:
    assert resolve(Project()).limits == Limits(
        actions=EVERY_BUT_LUP_S_WITHHELD,
        protected=["refs/heads/main", "refs/tags/*"],
        gated=["refs/heads/dev"],
    )
    [force, delete] = CredentialDefaults().withheld
    assert lup_actions() == Actions.all().drop("force-push", why=force.why).drop(
        "delete-ref", why=delete.why
    )
    assert Core().credentials == Credentials()


def test_credentials_layer_across_a_base_and_a_project() -> None:
    base = Modules.default().edit(
        Core(credentials=Credentials(protected=Refs().add("refs/heads/release/*"))),
        why="release branches are the operator's",
    )
    project = base.edit(
        Core(credentials=Credentials(actions=Actions().add("force-push"))),
        why="feature branches are rebased before review",
    )
    resolved = resolve(Project(modules=project))
    assert resolved.limits == Limits(
        actions=[
            "fetch",
            "push",
            "force-push",
            "read-issues",
            "file-issue",
            "comment",
            "draft-pull-request",
        ],
        protected=["refs/heads/main", "refs/tags/*", "refs/heads/release/*"],
        gated=["refs/heads/dev"],
    )
    assert module(resolved, "core").origins.of("credentials") == Origin(
        field="credentials",
        position=2,
        why="feature branches are rebased before review",
    )
    assert limits(base).actions == EVERY_BUT_LUP_S_WITHHELD


def test_a_project_gates_its_own_integration_branch_in_its_declaration() -> None:
    project = Modules.default().edit(
        Core(
            credentials=Credentials(
                gated=Refs()
                .drop("refs/heads/dev", why="this project integrates on `main`")
                .add("refs/heads/main", "refs/heads/release/*")
            )
        ),
        why="work lands on `main`, and on release branches",
    )
    assert limits(project).gated == ["refs/heads/main", "refs/heads/release/*"]


def allowed(chosen: Actions) -> list[str]:
    layer = Core(credentials=Credentials(actions=chosen))
    return [*limits(Modules.default().edit(layer)).actions]


def test_actions_start_over_from_every_one_lup_s_default_or_a_few() -> None:
    assert allowed(Actions.all()) == [*actions()]
    pushes = Actions.default().drop("push", why="pushes wait for the operator")
    assert allowed(pushes) == [
        name for name in EVERY_BUT_LUP_S_WITHHELD if name != "push"
    ]
    assert allowed(Actions.only("read-issues", "fetch")) == ["fetch", "read-issues"]
    assert allowed(Actions.of()) == []
    with pytest.raises(ProjectError, match=r"`Actions.drop` names `force-push`"):
        allowed(Actions().drop("force-push"))


def test_protected_refs_drop_and_start_over() -> None:
    def protected(chosen: Refs) -> list[str]:
        layer = Core(credentials=Credentials(protected=chosen))
        return limits(Modules.default().edit(layer)).protected

    tags = Refs().drop("refs/tags/*", why="tags are the agents' here")
    assert protected(tags) == ["refs/heads/main"]
    assert protected(Refs.of("refs/heads/trunk")) == ["refs/heads/trunk"]


@pytest.mark.parametrize(
    ("written", "unknown"),
    [
        (lambda: Actions().add("forse-push"), "forse-push"),
        (lambda: Actions.of("fetch", "merge"), "merge"),
        (lambda: Actions.only("deploy"), "deploy"),
        (lambda: Actions().drop("rebase"), "rebase"),
        (lambda: Actions().replace("push", "publish"), "publish"),
    ],
)
def test_a_name_that_isnt_an_action_is_refused_naming_those_that_are(
    written: Callable[[], Actions], unknown: str
) -> None:
    with pytest.raises(
        ProjectError,
        match=(
            rf"^`Actions` has no action `{unknown}`; its actions are `fetch`, "
            r"`push`, `force-push`, `delete-ref`, `read-issues`, `file-issue`, "
            r"`comment` and `draft-pull-request`$"
        ),
    ):
        written()


def test_an_unknown_action_fails_the_load(tmp_path: Path) -> None:
    (tmp_path / "lup_project.py").write_text(
        "from lup_dev import Actions, Core, Credentials, Modules, Project\n"
        "\n"
        "project = Project(\n"
        "    modules=Modules.default().edit(\n"
        '        Core(credentials=Credentials(actions=Actions().add("forse-push")))\n'
        "    )\n"
        ")\n"
    )
    with pytest.raises(
        ProjectError,
        match=(
            r"`lup_project.py` can't be imported: `Actions` has no action "
            r"`forse-push`; its actions are `fetch`"
        ),
    ):
        load(tmp_path)


def test_a_ref_pattern_that_isnt_over_full_ref_names_is_refused() -> None:
    with pytest.raises(
        ProjectError,
        match=r"`Refs` names `main` and `release/\*`, which isn't over full ref",
    ):
        Refs().add("main", "release/*")
    with pytest.raises(ProjectError, match=r"`Refs` names `tags/\*`"):
        Refs().drop("tags/*")


def test_credentials_from_two_modules_are_refused() -> None:
    class Forge(Module):
        """The project's own way with the forge."""

        name = "forge"

        credentials: Credentials = Credentials(actions=Actions.all())

    with pytest.raises(
        ProjectError,
        match=r"`core` and `forge` each give limits on the operator's credentials",
    ):
        resolve(Project(modules=Modules.default().add(Forge())))


def test_a_misspelled_credentials_field_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"protect\b"):
        Credentials.model_validate({"protect": Refs()})


def test_guidance_lists_each_module_s_sections_in_module_order() -> None:
    class Pipeline(Module):
        """The pipeline."""

        name = "pipeline"

        guidance: Guidance = Guidance.of(
            Section(name="pipeline", path=Path("guidance/pipeline.md")),
            Section(name="stages", package="pipeline.docs", path=Path("stages.md")),
        )

    project = Section(name="project", path=Path("AGENTS.md"))
    modules = (
        Modules.default()
        .add(Pipeline(), before="python")
        .edit(Core(guidance=Guidance().add(project)))
    )
    assert [each.name for each in resolve(Project(modules=modules)).guidance] == [
        "core",
        "project",
        "pipeline",
        "stages",
        "python",
        "code-rules",
        "transcripts",
        "private",
    ]
    first = Section(name="first", path=Path("first.md"))
    placed = modules.edit(
        Pipeline(guidance=Guidance().drop("stages").add(first, before="project"))
    )
    assert [each.name for each in resolve(Project(modules=placed)).guidance] == [
        "core",
        "first",
        "project",
        "pipeline",
        "python",
        "code-rules",
        "transcripts",
        "private",
    ]


def test_a_section_name_from_two_modules_is_refused_naming_both() -> None:
    class Notes(Module):
        """Notes."""

        name = "notes"

        guidance: Guidance = Guidance.of(Section(name="project", path=Path("a.md")))

    modules = Modules.default().edit(
        Core(guidance=Guidance().add(Section(name="project", path=Path("b.md"))))
    )
    with pytest.raises(ProjectError, match=r"`project` from `core` and `notes`"):
        resolve(Project(modules=modules.add(Notes())))


def test_lup_s_modules_each_bring_a_section_their_package_ships() -> None:
    assert [
        (each.name, each.package, each.path) for each in resolve(Project()).guidance
    ] == [
        ("core", "lup_dev.declaration.modules", Path("guidance/core.md")),
        ("python", "lup_dev.declaration.modules", Path("guidance/python.md")),
        ("code-rules", "lup_dev.declaration.modules", Path("guidance/code_rules.md")),
        ("transcripts", "lup.transcripts", Path("guidance.md")),
        ("private", "lup_dev.private", Path("guidance.md")),
    ]


def test_a_project_replaces_one_of_lup_s_sections() -> None:
    mine = Section(name="core", path=Path("room.md"))
    modules = Modules.default().edit(
        Core(guidance=Guidance().replace("core", mine, why="our room differs"))
    )
    assert resolve(Project(modules=modules)).guidance[0] == mine


# Other repositories for sessions to read


def entry(**fields: str | Path | None) -> Repository:
    written: dict[str, str | Path | None] = {
        "name": "atlas",
        "path": Path("atlas.git"),
        "about": "a made-up neighbour, read for how it did things",
        "github": "someone/atlas",
    }
    return Repository.model_validate({**written, **fields})


def named(repositories: Repositories) -> list[str]:
    return [each.entry.name for each in repositories.resolve([], [])]


class Neighbours(Module):
    """The repositories beside the project."""

    name = "neighbours"

    repositories: Repositories = Repositories.of(
        entry(),
        entry(name="notes", path=Path("/srv/notes"), github=None, about="notes"),
    )


def test_no_module_of_lup_s_holds_other_repositories() -> None:
    assert not any(
        isinstance(getattr(module, field), Repositories)
        for module in resolve(Project()).modules
        for field in type(module).model_fields
    )
    assert resolve(Project()).repositories == []


def test_a_module_s_repositories_resolve_as_written() -> None:
    resolved = resolve(Project(modules=Modules.default().add(Neighbours())))
    assert resolved.repositories == [
        entry(),
        Repository(name="notes", path=Path("/srv/notes"), about="notes"),
    ]


def test_a_layer_changes_a_module_s_repositories_by_name() -> None:
    later = entry(name="beacon", path=Path("beacon.git"), about="another")
    modules = (
        Modules.default()
        .add(Neighbours())
        .edit(
            Neighbours(repositories=Repositories().add(later).drop("notes")),
            why="beacon is a neighbour; the notes moved",
        )
    )
    resolved = resolve(Project(modules=modules))
    assert [each.name for each in resolved.repositories] == ["atlas", "beacon"]


def test_one_name_from_two_modules_with_one_path_is_one_repository_the_first_s() -> (
    None
):
    class Elsewhere(Module):
        """Another module naming the same neighbour."""

        name = "elsewhere"

        repositories: Repositories = Repositories.of(entry(about="said again"))

    modules = Modules.default().add(Neighbours()).add(Elsewhere())
    resolved = resolve(Project(modules=modules))
    assert [(each.name, each.about) for each in resolved.repositories] == [
        ("atlas", entry().about),
        ("notes", "notes"),
    ]


def test_one_name_from_two_modules_with_two_paths_is_refused_naming_both() -> None:
    class Elsewhere(Module):
        """Another module naming the same neighbour elsewhere."""

        name = "elsewhere"

        repositories: Repositories = Repositories.of(entry(path=Path("/srv/atlas.git")))

    modules = Modules.default().add(Neighbours()).add(Elsewhere())
    with pytest.raises(
        ProjectError,
        match=(
            r"two modules give one repository different paths, `atlas` at "
            r"`atlas.git` and at `/srv/atlas.git`"
        ),
    ):
        resolve(Project(modules=modules))


def test_paths_relative_absolute_and_from_the_home_are_kept_as_written() -> None:
    written = [Path("atlas.git"), Path("../elsewhere/x.git"), Path("/srv/x")]
    paths = [*written, Path("~/src/x.git")]
    assert [entry(path=path).path for path in paths] == paths


def test_repositories_are_named_and_changed_by_name() -> None:
    beacon = entry(
        name="beacon", path=Path("beacon.git"), about="another made-up neighbour"
    )
    notes = entry(name="notes", path=Path("/srv/notes"), github=None, about="notes")
    chosen = Repositories.of(entry(), notes).add(beacon).drop("notes")
    assert named(chosen) == ["atlas", "beacon"]
    moved = chosen.replace(
        "beacon", beacon.model_copy(update={"path": Path("/srv/beacon")})
    )
    assert [each.entry.path for each in moved.resolve([], [])] == [
        Path("atlas.git"),
        Path("/srv/beacon"),
    ]


def test_one_name_twice_is_refused_naming_it() -> None:
    with pytest.raises(ProjectError, match=r"starts from `atlas` more than once"):
        named(Repositories.of(entry(), entry(path=Path("/srv/atlas.git"))))
    with pytest.raises(ProjectError, match=r"`Repositories.add` names `atlas`"):
        named(Repositories.of(entry()).add(entry(path=Path("/srv/x.git"))))


@pytest.mark.parametrize(
    ("fields", "refusal"),
    [
        ({"name": " "}, r"A `Repository` at `atlas.git` has no name"),
        ({"path": Path()}, r"`Repository` `atlas` names no path"),
        ({"about": ""}, r"`Repository` `atlas` says nothing `about` what it is"),
        (
            {"github": "atlas"},
            (
                r"`Repository` `atlas` gives its GitHub repository as "
                r"`atlas`: a repository on GitHub is `owner/name`"
            ),
        ),
        (
            {"github": "someone/atlas/x"},
            r"as `someone/atlas/x`: a repository on GitHub is `owner/name`",
        ),
    ],
)
def test_a_malformed_repository_is_refused_naming_it(
    fields: dict[str, str | Path], refusal: str
) -> None:
    with pytest.raises(ProjectError, match=refusal):
        entry(**fields)


def test_a_repository_refuses_fields_it_doesn_t_know() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"url\b"):
        Repository.model_validate(
            {"name": "x", "path": "x.git", "about": "x", "url": "https://x"}
        )


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
