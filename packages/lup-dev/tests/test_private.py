"""The `Private` module: its list built on the host, how a value is found, and how the declaration chooses them.

Every value here is made up: a home `/home/op`, a user `op`, a host
`kestrel-box`, an alias `forge-op`. The host's account, ssh and GitHub are a
stub (`StubFacts`); git runs for real on a scratch repository.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev import Modules, Private, Project, ProjectError, Values
from lup_dev.declaration.resolve import resolve
from lup_dev.forge.github import GitHubError
from lup_dev.private.found import added_lines, counted, found, textual
from lup_dev.private.module import Details
from lup_dev.private.withheld import (
    Held,
    Neighbour,
    Seen,
    Withheld,
    built,
    said,
)

if TYPE_CHECKING:
    from conftest import Shell, StubFacts

HOME = "/home/op"
USER = Held(kind="user", text="op")
WITHHELD = Withheld(
    held=[
        Held(kind="repository-path", text="/home/op/src/demo.git"),
        Held(kind="home", text=HOME),
        Held(kind="value", text="Kestrel Labs"),
        USER,
    ]
)


def places(text: str, withheld: Withheld = WITHHELD) -> list[tuple[str, int, int]]:
    return [(each.held.kind, each.line, each.column) for each in found(text, withheld)]


# Finding a value


def test_a_value_is_found_whatever_its_case_and_placed_by_line_and_column() -> None:
    assert places("first\nOP said so\n  kestrel labs too") == [
        ("user", 2, 1),
        ("value", 3, 3),
    ]


def test_a_value_inside_a_longer_word_isnt_found() -> None:
    assert places("the operator ran a loop in /home/opal; ops") == []


def test_a_value_beside_punctuation_or_in_a_dashed_path_is_found() -> None:
    assert places("op@kestrel-box, -home-op-src-, `op`, (op)") == [
        ("user", 1, 1),
        ("user", 1, 23),
        ("user", 1, 33),
        ("user", 1, 39),
    ]


def test_of_overlapping_values_the_longest_is_found() -> None:
    assert places("cd /home/op/src/demo.git/tree and /home/op/x") == [
        ("repository-path", 1, 4),
        ("home", 1, 35),
    ]


def test_a_place_counts_characters_as_written_past_wide_and_folding_ones() -> None:
    assert places("🦊 é Straße op") == [("user", 1, 12)]
    assert places(
        "STRASSE op", Withheld(held=[Held(kind="value", text="straße"), USER])
    ) == [
        ("value", 1, 1),
        ("user", 1, 9),
    ]


def test_a_file_that_isnt_text_is_counted_ignoring_ascii_case() -> None:
    assert textual(b"\x89PNG\x00/HOME/OP") is None
    assert counted(
        b"\x89PNG\x00/HOME/OP and /home/opal", Held(kind="home", text=HOME)
    ) == [5]


def test_only_lines_a_change_adds_count_for_a_push() -> None:
    assert added_lines(None, "a\nb\n") == [1, 2]
    assert added_lines("a\nb\nc\n", "a\nc\n") == []
    assert added_lines("a\nb\n", "a\nB\nc\n") == [2, 3]


def test_what_a_refusal_says_of_a_kind_never_holds_a_value() -> None:
    assert said("value").what == "one of the operator's private values"
    assert said("home").steer.startswith("write it as `~`")


# Building the list on the host


@pytest.fixture
def demo(tmp_path: Path, shell: Shell) -> Path:
    """A bare repository whose remotes name an SSH alias and GitHub's own host."""
    git = tmp_path / "home" / "op" / "src" / "demo.git"
    git.mkdir(parents=True)
    shell.git(git, "init", "-q", "--bare")
    shell.git(git, "remote", "add", "origin", "forge-op:op/demo.git")
    shell.git(git, "remote", "add", "mirror", "https://github.com/op/demo")
    shell.git(git, "config", "remote.mirror.pushurl", "ssh://git@forge-op:22/op/demo")
    return git


def building(
    facts: StubFacts,
    git: Path,
    *,
    related: list[Neighbour] | None = None,
    details: list[str] | None = None,
    values: list[str] | None = None,
    last: Withheld | None = None,
) -> tuple[list[tuple[str, str]], list[str], list[Seen]]:
    chosen = Private(details=Details.only(*details)) if details else Private()
    made = asyncio.run(
        built(
            facts,
            git,
            own=[git],
            related=related or [],
            details=chosen.chosen_details(),
            values=values or [],
            last=last,
        )
    )
    held = [(each.kind, each.text) for each in made.withheld.held]
    return held, made.notes, made.withheld.seen


def test_the_list_holds_the_machine_the_alias_and_the_repository_s_paths(
    demo: Path, stub_facts: type[StubFacts]
) -> None:
    home = demo.parents[1]
    facts = stub_facts(home=home, aliases={"forge-op": "github.com"})
    held, notes, _ = building(facts, demo, values=[" Kestrel Labs "])
    assert held == sorted(
        [
            ("repository-path", str(demo)),
            ("repository-path", "~/src/demo.git"),
            ("home", str(home)),
            ("hostname", "kestrel-box"),
            ("alias", "forge-op"),
            ("value", "Kestrel Labs"),
            ("user", "op"),
        ],
        key=lambda each: -len(each[1]),
    )
    assert notes == []


def test_a_detail_dropped_isn_t_read(demo: Path, stub_facts: type[StubFacts]) -> None:
    facts = stub_facts(home=demo.parents[1], aliases={"forge-op": "github.com"})
    held, _, _ = building(facts, demo, details=["user", "home"])
    assert [kind for kind, _ in held] == ["home", "user"]


def test_a_related_repository_that_isn_t_public_is_kept_by_its_names(
    demo: Path, stub_facts: type[StubFacts], tmp_path: Path
) -> None:
    facts = stub_facts(
        home=Path("/home/elsewhere"),
        visible={
            "op/atlas": "private",
            "op/gull": GitHubError("gh couldn't reach GitHub"),
            "op/tern": GitHubError("gh couldn't reach GitHub"),
        },
    )
    related = [
        Neighbour(name="gannet", path=tmp_path / "gannet", github=None),
        Neighbour(name="atlas", path=tmp_path / "atlas", github="op/atlas"),
        Neighbour(name="public-one", path=tmp_path / "pub", github="op/pub"),
        Neighbour(name="gull", path=tmp_path / "gull", github="op/gull"),
        Neighbour(name="tern", path=tmp_path / "tern", github="op/tern"),
    ]
    last = Withheld(seen=[Seen(repository="op/gull", visibility="private")])
    held, notes, seen = building(
        facts, demo, related=related, details=["private-repository"], last=last
    )
    assert sorted(text for _, text in held) == sorted(
        ["gannet", "atlas", "op/atlas", "gull", "op/gull"]
    )
    assert facts.asked == ["op/atlas", "op/pub", "op/gull", "op/tern"]
    assert notes == [
        (
            "GitHub didn't say whether `op/gull` is public (gh couldn't reach "
            "GitHub): its word at the last launch, private, stands"
        ),
        (
            "GitHub didn't say whether `op/tern` is public (gh couldn't reach "
            "GitHub): its name isn't checked until it does"
        ),
    ]
    assert [each.repository for each in seen] == ["op/atlas", "op/pub", "op/gull"]


def test_a_value_given_twice_whatever_its_case_is_kept_once(
    demo: Path, stub_facts: type[StubFacts]
) -> None:
    facts = stub_facts(home=Path("/home/elsewhere"))
    held, _, _ = building(facts, demo, details=["user"], values=["OP", "kestrel"])
    assert held == [("value", "kestrel"), ("user", "op")]


# Declaring it


def test_private_is_one_of_lup_s_default_modules_and_drops_with_its_reason() -> None:
    assert "private" in [each.name for each in resolve(Project()).modules]
    dropped = Project(
        modules=Modules.default().drop("private", why="a scratch project")
    )
    assert "private" not in [each.name for each in resolve(dropped).modules]


def test_a_person_s_values_and_a_dropped_detail_compose_over_the_project_s() -> None:
    project = Modules.default().edit(Private(values=Values().add("kestrel")))
    person = Modules().edit(
        Private(
            values=Values().add("gull"),
            details=Details().drop("hostname", why="it's an ordinary word here"),
        )
    )
    resolved = resolve(Project(modules=person.over(project)))
    [private] = [each for each in resolved.modules if isinstance(each, Private)]
    assert private.chosen_values() == ["kestrel", "gull"]
    assert "hostname" not in private.chosen_details()


def test_a_detail_that_isn_t_one_or_a_blank_value_is_refused_where_written() -> None:
    with pytest.raises(ProjectError, match=r"`Details` has no detail `hostnme`"):
        Details().drop("hostnme")
    with pytest.raises(ProjectError, match=r"blank or spans lines"):
        Values().add("two\nlines")
