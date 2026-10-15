"""The selection grammar: its starts, its operations, composing layers, resolving."""

from pathlib import Path

import pytest

from lup_dev.catalog.gate import Step
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Drop, Placed
from lup_dev.declaration.kinds import (
    Exemption,
    Exemptions,
    Gate,
    Guidance,
    Package,
    Packages,
    Paths,
    Pytest,
    RemovedTools,
    Rules,
    Section,
    Session,
    TestRoots,
)

DEFAULTS = ["regex", "tuple-shape", "set-shape"]
KNOWN = [*DEFAULTS, "runtime-mention"]


def names(placed: list[Placed[str]]) -> list[str]:
    return [each.entry for each in placed]


def step(name: str) -> Step:
    return Step(name=name, command=[name])


# Starts


def test_the_value_below_with_nothing_composed_beneath_is_nothing() -> None:
    assert names(Rules().resolve(DEFAULTS, KNOWN)) == []
    assert names(Rules().add("mine").resolve(DEFAULTS, KNOWN)) == ["mine"]


def test_a_layer_over_a_default_written_from_below_applies_the_default_once() -> None:
    own = Rules().add("mine")
    layered = Rules().add("yours").over(own)
    assert names(layered.resolve(names(own.resolve([], [])), KNOWN)) == [
        "mine",
        "yours",
    ]
    restarted = Rules.default().add("yours").over(own)
    assert names(restarted.resolve(names(own.resolve([], [])), KNOWN)) == [
        "mine",
        "yours",
    ]


def test_default_starts_from_the_defaults() -> None:
    assert names(Rules.default().resolve(DEFAULTS, KNOWN)) == DEFAULTS


def test_all_starts_from_every_known_entry() -> None:
    assert names(Rules.all().resolve(DEFAULTS, KNOWN)) == KNOWN


def test_only_picks_known_entries_by_name() -> None:
    picked = Rules.only("runtime-mention", "regex").resolve(DEFAULTS, KNOWN)
    assert names(picked) == ["runtime-mention", "regex"]


def test_only_refuses_an_unknown_name_naming_the_known_ones() -> None:
    with pytest.raises(
        ProjectError, match=r"`Rules.only` names `regx`.*`regex`, `tuple-shape`"
    ):
        Rules.only("regx").resolve(DEFAULTS, KNOWN)


def test_of_gives_its_own_entries_without_defaults() -> None:
    assert names(Rules.of("mine").resolve(DEFAULTS, KNOWN)) == ["mine"]


def test_of_with_nothing_is_nothing() -> None:
    assert Rules.of().resolve(DEFAULTS, KNOWN) == []


def test_a_start_naming_one_entry_twice_is_refused() -> None:
    with pytest.raises(ProjectError, match=r"`regex` more than once"):
        Rules.of("regex", "regex").resolve([], [])


# Operations


def test_each_verb_returns_a_new_selection_and_records_its_operation() -> None:
    first = Rules.default()
    second = first.drop("regex", why="a grammar")
    assert first.operations == []
    assert [operation.verb for operation in second.operations] == ["drop"]
    assert second.drop("set-shape").operations[1] == Drop(names=["set-shape"], why=None)


def test_drop_leaves_out_the_names_given() -> None:
    dropped = Rules.default().drop("regex", "set-shape").resolve(DEFAULTS, KNOWN)
    assert names(dropped) == ["tuple-shape"]


def test_dropping_a_name_that_isnt_there_names_the_ones_that_are() -> None:
    with pytest.raises(
        ProjectError,
        match=r"`Rules.drop` names `regx`, which isn't there; there are `regex`, `tuple-shape` and `set-shape`",
    ):
        Rules.default().drop("regx").resolve(DEFAULTS, KNOWN)


def test_add_puts_entries_beside_the_ones_there() -> None:
    added = Rules.default().add("runtime-mention").resolve(DEFAULTS, KNOWN)
    assert names(added) == [*DEFAULTS, "runtime-mention"]


def test_adding_a_name_already_there_is_refused() -> None:
    with pytest.raises(ProjectError, match=r"`Rules.add` names `regex`, already there"):
        Rules.default().add("regex").resolve(DEFAULTS, KNOWN)


def test_adding_one_name_twice_is_refused() -> None:
    with pytest.raises(ProjectError, match=r"`Rules.add` names `mine`, already there"):
        Rules.default().add("mine", "mine").resolve(DEFAULTS, KNOWN)


def test_replace_puts_an_entry_where_the_named_one_was() -> None:
    gate = Gate.of(step("ruff"), step("pytest")).replace(
        "ruff", step("lint"), why="ours"
    )
    placed = gate.resolve([], [])
    assert [each.entry.name for each in placed] == ["lint", "pytest"]
    assert placed[0].why == "ours"
    assert placed[0].position == 1


def test_replacing_a_name_that_isnt_there_is_refused() -> None:
    with pytest.raises(
        ProjectError, match=r"`Gate.replace` names `mypy`, which isn't there"
    ):
        Gate.of(step("ruff")).replace("mypy", step("pyright")).resolve([], [])


def test_replacing_with_a_name_already_there_is_refused() -> None:
    gate = Gate.of(step("ruff"), step("pytest")).replace("ruff", step("pytest"))
    with pytest.raises(ProjectError, match=r"`pytest` is already there"):
        gate.resolve([], [])


def test_a_replaced_entry_keeps_its_place() -> None:
    gate = (
        Gate.of(step("ruff"))
        .add(step("docs"), after="ruff")
        .replace("docs", step("site"))
    )
    assert [each.after for each in gate.resolve([], [])] == [None, "ruff"]


def test_operations_apply_in_the_order_written() -> None:
    rules = Rules.default().drop("regex").add("regex")
    assert names(rules.resolve(DEFAULTS, KNOWN)) == [
        "tuple-shape",
        "set-shape",
        "regex",
    ]


# Layers


def test_a_layer_from_below_keeps_belows_start_and_adds_its_operations() -> None:
    below = Rules.default().drop("regex", why="a grammar")
    layered = Rules().drop("tuple-shape").over(below)
    assert layered.start.kind == "default"
    assert [
        operation.names for operation in layered.operations if operation.verb == "drop"
    ] == [
        ["regex"],
        ["tuple-shape"],
    ]
    assert names(layered.resolve(DEFAULTS, KNOWN)) == ["set-shape"]


def test_a_layer_starting_over_replaces_below_whole() -> None:
    below = Rules.default().drop("regex")
    for layer in [Rules.default(), Rules.only("regex"), Rules.of("mine"), Rules.all()]:
        assert layer.over(below) == layer


def test_layers_stack_three_deep() -> None:
    first = Exemptions().add(Exemption(rule="regex", paths=["a/**"], why="a"))
    second = Exemptions().add(Exemption(rule="set-shape", paths=["b/**"], why="b"))
    third = Exemptions().drop("regex")
    stacked = third.over(second.over(first))
    assert [each.entry.rule for each in stacked.resolve([], [])] == ["set-shape"]


def test_a_part_with_no_defaults_starts_from_nothing() -> None:
    assert Exemptions().resolve([], []) == []


# Order across modules


def test_entries_without_anchors_keep_the_order_they_come_in() -> None:
    placed = [Placed(entry=step(name)) for name in ["ruff", "pyright", "pytest"]]
    assert [each.name for each in Gate().ordered(placed)] == [
        "ruff",
        "pyright",
        "pytest",
    ]


def test_an_entry_goes_after_or_before_another_wherever_it_is() -> None:
    placed = [
        Placed(entry=step("ruff")),
        Placed(entry=step("pytest")),
        Placed(entry=step("docs"), after="ruff"),
        Placed(entry=step("engine"), before="ruff"),
        Placed(entry=step("site"), after="ruff"),
    ]
    ordered = [each.name for each in Gate().ordered(placed)]
    assert ordered == ["engine", "ruff", "docs", "site", "pytest"]


def test_an_entry_can_be_placed_by_one_placed_itself() -> None:
    placed = [
        Placed(entry=step("site"), after="docs"),
        Placed(entry=step("ruff")),
        Placed(entry=step("docs"), after="ruff"),
    ]
    assert [each.name for each in Gate().ordered(placed)] == ["ruff", "docs", "site"]


def test_an_anchor_naming_no_entry_is_refused() -> None:
    placed = [Placed(entry=step("ruff")), Placed(entry=step("docs"), after="pytst")]
    with pytest.raises(
        ProjectError,
        match=r"by `pytst`, which isn't there; there are `ruff` and `docs`",
    ):
        Gate().ordered(placed)


def test_entries_placed_only_by_each_other_are_refused() -> None:
    placed = [
        Placed(entry=step("ruff")),
        Placed(entry=step("a"), after="b"),
        Placed(entry=step("b"), before="a"),
    ]
    with pytest.raises(ProjectError, match=r"places `a` and `b` only by each other"):
        Gate().ordered(placed)


def test_an_entry_placed_both_before_and_after_is_refused() -> None:
    with pytest.raises(ProjectError, match=r"not both"):
        Gate().add(step("docs"), before="ruff", after="pytest")


# The kinds


def test_paths_take_roles_as_keywords() -> None:
    paths = Paths.of(data=["episodes/**"], scratch=["renders/**"]).add(
        data=["takes/**"]
    )
    resolved = paths.resolve(Paths())
    assert resolved["data"] == ["episodes/**", "takes/**"]
    assert resolved["scratch"] == ["renders/**"]
    assert resolved["protected"] == []


def test_paths_of_starts_every_role_over() -> None:
    own = Paths.of(protected=["a"], data=["*.yaml"])
    layered = Paths.of(protected=["b"]).over(own).resolve(own)
    assert layered["protected"] == ["b"]
    assert layered["data"] == []


def test_paths_compose_role_by_role_over_the_module_s_own() -> None:
    own = Paths.of(protected=["a"], data=["*.yaml", "*.json"])
    layer = Paths().add(protected=["b"]).drop(data=["*.yaml"], why="configuration here")
    resolved = layer.over(own).resolve(own)
    assert resolved["protected"] == ["a", "b"]
    assert resolved["data"] == ["*.json"]
    assert layer.data.operations == [Drop(names=["*.yaml"], why="configuration here")]


def test_paths_default_starts_from_the_module_s_own() -> None:
    own = Paths.of(protected=["a"])
    assert Paths.default().add(protected=["b"]).resolve(own)["protected"] == ["a", "b"]


def test_paths_refuse_a_role_that_isnt_one() -> None:
    with pytest.raises(ProjectError, match=r"`Paths` has no role `protcted`"):
        Paths().add(protcted=["x"])


def test_dropping_a_pattern_that_isnt_there_names_the_ones_that_are() -> None:
    own = Paths.of(data=["*.json"])
    with pytest.raises(
        ProjectError,
        match=r"`Patterns.drop` names `\*.yaml`, which isn't there; there are `\*.json`",
    ):
        Paths().drop(data=["*.yaml"]).over(own).resolve(own)


def test_steps_exemptions_and_test_roots_are_named_by_their_own_field() -> None:
    assert Gate().named(step("ruff")) == "ruff"
    assert Exemptions().named(Exemption(rule="regex", paths=[], why="")) == "regex"
    assert (
        TestRoots().named(Pytest(root=Path("packages/*/tests"))) == "packages/*/tests"
    )
    assert Packages().named(Package(name="git", why="")) == "git"
    assert Guidance().named(Section(name="core", path=Path("core.md"))) == "core"


def test_a_layer_keeps_what_it_didn_t_set_and_composes_a_selection_it_holds() -> None:
    below = Session(subagent_cache="5m", removed_tools=RemovedTools.of("A", "B"))
    layered = Session(
        auto_memory=True, removed_tools=RemovedTools().drop("A").add("C")
    ).over(below)
    assert layered.subagent_cache == "5m"
    assert layered.auto_memory is True
    assert names(layered.removed_tools.resolve([], [])) == ["B", "C"]


def test_a_layer_given_a_field_at_its_default_value_sets_it() -> None:
    assert (
        Session(auto_memory=False).over(Session(auto_memory=True)).auto_memory is False
    )
    assert Session().over(Session(auto_memory=True)).auto_memory is True
