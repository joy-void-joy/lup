"""Profiles: the person's profiles file run from its approved copy, layered on lup's `default`, and a launch's choice of profile and account."""

import re
import sys
import textwrap
from pathlib import Path

import pytest

from lup_dev import Lend, Lending, Profile, Profiles, Project, RuntimeDefaults
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import declared_profiles
from lup_dev.declaration.profiles import DEFAULT, chosen, resolved_profiles
from lup_dev.layout import Layout
from lup_dev.settings import LupDevSettings

SHOWN = Path("~/.config/lup/profiles.py")
"""How the profiles file is named in what a test reads."""

MINE = textwrap.dedent(
    """
    from pathlib import Path

    from lup_dev import Lend, Lending, Profile, Profiles, RuntimeDefaults

    profiles = (
        Profiles()
        .add(
            Profile(
                name="work",
                account="work",
                accounts={"second": "home"},
                lent=Lending.of(Lend(path=Path("~/notes"))),
                defaults={"first": RuntimeDefaults(model="big", effort="high")},
                guidance=Path("guidance.md"),
                rooms_home="global",
            )
        )
        .edit(Profile(name="default", lent=Lending().add(Lend(path=Path("/scratch"), writable=True))))
    )
    """
)
"""A person's profiles file: one of their own, and `default` lending a directory."""


def test_profiles_and_accounts_are_placed_where_xdg_says(tmp_path: Path) -> None:
    layout = Layout.of(
        LupDevSettings(
            xdg_config_home=tmp_path / "config", xdg_data_home=tmp_path / "data"
        )
    )
    assert layout.profiles.declared == tmp_path / "config" / "lup" / "profiles.py"
    assert layout.profiles.profile("work").runtime("first") == (
        tmp_path / "config" / "lup" / "profiles" / "work" / "first"
    )
    assert layout.accounts.account("work").runtime("first") == (
        tmp_path / "data" / "lup" / "accounts" / "work" / "first"
    )


def named(profiles: list[Profile]) -> dict[str, Profile]:
    return {each.name: each for each in profiles}


def test_without_a_file_default_alone_is_there() -> None:
    assert declared_profiles(None, SHOWN) == [Profile(name=DEFAULT)]
    [default] = declared_profiles(None, SHOWN)
    assert default.account == DEFAULT
    assert default.operator_configuration
    assert default.lent.resolve([], []) == []
    assert default.rooms_home == "project"


def test_the_file_adds_its_own_and_edits_default_field_by_field() -> None:
    profiles = named(declared_profiles(MINE, SHOWN))
    assert list(profiles) == ["default", "work"]
    work = profiles["work"]
    assert work.account_for("first") == "work"
    assert work.account_for("second") == "home"
    assert [each.entry for each in work.lent.resolve([], [])] == [
        Lend(path=Path("~/notes"))
    ]
    assert work.defaults == {"first": RuntimeDefaults(model="big", effort="high")}
    assert work.guidance == Path("guidance.md")
    assert work.rooms_home == "global"
    default = profiles["default"]
    assert default.account == DEFAULT
    assert [each.entry for each in default.lent.resolve([], [])] == [
        Lend(path=Path("/scratch"), writable=True)
    ]
    assert "lup_profiles" not in sys.modules


def test_an_edit_keeps_what_it_doesnt_set_and_composes_what_it_lends() -> None:
    profiles = (
        Profiles()
        .add(
            Profile(name="work", account="work", lent=Lending.of(Lend(path=Path("/a"))))
        )
        .edit(Profile(name="work", lent=Lending().add(Lend(path=Path("/b")))))
    )
    work = named(resolved_profiles(profiles))["work"]
    assert work.account == "work"
    assert [str(each.entry.path) for each in work.lent.resolve([], [])] == ["/a", "/b"]


def test_profiles_leaving_default_out_are_refused() -> None:
    with pytest.raises(ProjectError) as failed:
        resolved_profiles(Profiles.of(Profile(name="work")))
    assert str(failed.value) == (
        "`Profiles` leaves out `default`, which a launch choosing no profile runs: "
        '`.edit(Profile(name="default", …))` changes it'
    )


def test_a_profile_added_twice_or_edited_where_missing_is_refused() -> None:
    with pytest.raises(ProjectError, match="already there"):
        resolved_profiles(Profiles().add(Profile(name="default")))
    with pytest.raises(ProjectError, match=re.escape("`Profiles.edit` names `work`")):
        resolved_profiles(Profiles().edit(Profile(name="work")))


def test_a_file_binding_no_profiles_or_failing_is_refused() -> None:
    with pytest.raises(ProjectError) as unbound:
        declared_profiles("profiles = 3\n", SHOWN)
    assert str(unbound.value) == (
        "`~/.config/lup/profiles.py` binds a `int` as `profiles`, not a `Profiles`"
    )
    with pytest.raises(ProjectError) as failing:
        declared_profiles("raise RuntimeError('broken')\n", SHOWN)
    assert str(failing.value) == "`profiles.py` can't be imported: broken"
    assert "lup_profiles" not in sys.modules


def test_the_file_runs_with_no_import_path_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A module beside the person's file isn't importable: it would run unapproved."""
    (tmp_path / "beside.py").write_text("ran = True\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "path", [each for each in sys.path if each not in ["", "."]]
    )
    with pytest.raises(ProjectError, match="No module named 'beside'"):
        declared_profiles("import beside\n", tmp_path / "profiles.py")


def test_a_name_that_cant_be_a_directory_is_refused() -> None:
    with pytest.raises(ValueError, match="can't name a profile or an account"):
        Profile(name="../work")
    with pytest.raises(ValueError, match="can't name a profile or an account"):
        Profile(name="work", accounts={"first": "a/b"})


def test_a_profile_s_layer_choosing_a_profile_is_refused() -> None:
    with pytest.raises(ProjectError, match="never by another profile"):
        Profile(name="work", layer=Project(profile="home"))


PROFILES = [
    Profile(name=DEFAULT),
    Profile(name="work", account="work", accounts={"second": "home"}),
]
"""The profiles a launch chooses among, in the tests of `chosen`."""

RUNTIMES = ["first", "second"]
"""The runtimes' names, as their adapters give them."""


def test_a_launch_runs_on_default_unless_a_profile_is_named() -> None:
    plain = chosen(PROFILES, "first", RUNTIMES, profile=None, account=None)
    assert plain.profile.name == DEFAULT
    assert plain.account == DEFAULT
    assert plain.said() is None
    work = chosen(PROFILES, "first", RUNTIMES, profile="work", account=None)
    assert work.account == "work"
    assert work.said() == (
        "This launch runs on the profile `work`, with the account `work`."
    )
    assert (
        chosen(PROFILES, "second", RUNTIMES, profile="work", account=None).account
        == "home"
    )


def test_account_replaces_the_profile_s_for_the_launch() -> None:
    mine = chosen(PROFILES, "second", RUNTIMES, profile="work", account="spare")
    assert mine.account == "spare"
    assert chosen(
        PROFILES, "first", RUNTIMES, profile=None, account="spare"
    ).said() == ("This launch runs on the profile `default`, with the account `spare`.")


def test_an_unknown_profile_or_runtime_or_a_malformed_account_is_refused() -> None:
    with pytest.raises(ProjectError) as unknown:
        chosen(PROFILES, "first", RUNTIMES, profile="home", account=None)
    assert str(unknown.value) == (
        "no profile is called `home`: the profiles are `default` and `work`"
    )
    with pytest.raises(ProjectError) as runtime:
        chosen(PROFILES, "first", ["first"], profile="work", account=None)
    assert str(runtime.value) == (
        "Profile `work` names `second`, which no runtime is called: the runtimes "
        "are `first`"
    )
    with pytest.raises(ProjectError, match=re.escape("`--account ../x`: ")):
        chosen(PROFILES, "first", RUNTIMES, profile=None, account="../x")
