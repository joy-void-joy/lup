"""Reaching a remote from inside the boundary, on a credential worth the reach.

The ssh key stays on the host and nothing routes to it, so what a contained
session can reach is exactly what the token admits. Two things must stay true
for that to be a boundary rather than a nuisance, and both are easy to lose:
the rewrite that makes the token reachable has to be decided outside, and it
has to arrive somewhere the confined thing cannot reach behind.
"""

from pathlib import Path

import pytest

from lup.devtools.utils import git
from lup.harness.credential import (
    AgentKey,
    GitAccess,
    InheritedSigning,
    RemoteRewrite,
    SigningOff,
    committer,
    parse_remote,
    remote_rewrites,
    resolved_host,
)

REWRITE = [RemoteRewrite(spelling="git@github.com:", https="https://github.com/")]


def test_the_configuration_arrives_above_every_file_the_container_can_write() -> None:
    """`.git/config` is inside the mount, so it is the confined thing's to edit.

    Git reads `GIT_CONFIG_COUNT` and its numbered pairs above every
    configuration file, so what the launcher decided cannot be overridden
    from inside -- and nothing had to be written into a tree the agent can
    edit. A file would have been both.
    """
    environment = GitAccess().environment("tok", REWRITE)
    count = int(environment["GIT_CONFIG_COUNT"])
    keys = {environment[f"GIT_CONFIG_KEY_{index}"] for index in range(count)}
    assert "url.https://github.com/.insteadOf" in keys
    assert "credential.helper" in keys


def test_the_token_reaches_both_the_forge_client_and_git() -> None:
    """One credential, two consumers, and neither prompts for the other's."""
    environment = GitAccess().environment("tok", REWRITE)
    assert environment["GH_TOKEN"] == "tok"
    assert environment["LUP_GIT_TOKEN"] == "tok"


def test_no_token_still_makes_the_remote_addressable() -> None:
    """The rewrite is what a remote needs; the credential is what a push needs.

    An ssh remote is unreachable from inside for a reason that has nothing to
    do with credentials -- the session's network resolves no names at all --
    so withholding the rewrite until a token appeared turned a public fetch
    that would have worked into a hostname that would not resolve, which
    reads as a broken container rather than as a boundary.
    """
    environment = GitAccess().environment("", REWRITE)
    count = int(environment["GIT_CONFIG_COUNT"])
    keys = {environment[f"GIT_CONFIG_KEY_{index}"] for index in range(count)}
    assert "url.https://github.com/.insteadOf" in keys
    assert "LUP_GIT_TOKEN" not in environment
    assert "GH_TOKEN" not in environment


def test_the_helper_refuses_in_the_name_of_the_variable_that_would_answer() -> None:
    """Git names the URL it could not authenticate to, never the way in.

    A helper that fails with the variable's name in it is the boundary's only
    sentence at the moment somebody meets the wall. The launch notice that
    also named it has scrolled past by then.
    """
    helper = GitAccess().helper("")
    assert "LUP_GIT_TOKEN" in helper.value
    assert "exit 1" in helper.value


def test_the_absence_of_a_token_is_said_at_launch() -> None:
    """Not an error -- plenty of work never touches a remote.

    But discovering it as a credential prompt inside a non-interactive
    session is exactly the failure the manifest exists to prevent, so the
    variable is named before anything needs it.
    """
    spoken = " ".join(item.text for item in GitAccess().notice("", []))
    assert "LUP_GIT_TOKEN" in spoken
    assert "ssh key is on the host" in spoken


def test_the_launch_says_what_goes_in_the_variable_it_names() -> None:
    """A variable nobody can fill is the same wall as no notice at all.

    The scope and the forge are read off the declaration rather than spelled
    in the sentence, so an adopter who moved either gets an instruction about
    the host they actually reach instead of one about GitHub.
    """
    granting = next(
        item
        for item in GitAccess(host="gitea.example.test").notice("", [])
        if item.indent
    )

    assert "gitea.example.test" in granting.text
    assert "export" in granting.text.lower()
    assert granting.urgency == "detail"


def test_the_launch_says_the_agent_can_read_the_token() -> None:
    """Stated rather than implied, because hiding it would be theatre.

    An agent that can run `git push` with a credential can also read it. The
    scope is the boundary, not the secrecy, and a reader who believed
    otherwise would scope the token wrongly.
    """
    assert "not the secrecy" in " ".join(
        item.text for item in GitAccess().notice("tok", REWRITE)
    )


def test_an_ssh_config_alias_is_taken_apart_rather_than_pattern_matched() -> None:
    """The case that refuted a prefix list, and what any ssh config produces.

    `forge:owner/repo.git` begins with none of `git@`, `ssh://git@` or
    `ssh://`. A list of ssh spellings produced no rewrite for it at all, so a
    contained session would have kept an ssh remote with no ssh to reach it,
    and the push would have failed in the transport's vocabulary rather than
    the boundary's.
    """
    parsed = parse_remote("forge:owner/repo.git")
    assert parsed is not None
    assert parsed.prefix == "forge:"
    assert parsed.host == "forge"
    assert parsed.proxied is False


def test_the_scp_like_form_separates_the_user_from_the_host() -> None:
    """`git@github.com:` is one prefix and `github.com` is the name ssh resolves."""
    parsed = parse_remote("git@github.com:owner/repo.git")
    assert parsed is not None
    assert (parsed.prefix, parsed.host) == ("git@github.com:", "github.com")


def test_a_scheme_url_is_read_by_a_parser_rather_than_by_hand() -> None:
    """And the port belongs to neither the prefix's host nor the comparison."""
    parsed = parse_remote("ssh://git@github.com:2222/owner/repo.git")
    assert parsed is not None
    assert parsed.host == "github.com"
    assert parsed.proxied is False


def test_https_is_already_reachable_through_the_proxy() -> None:
    parsed = parse_remote("https://github.com/owner/repo.git")
    assert parsed is not None
    assert parsed.proxied is True


def test_the_other_unproxied_transport_is_not_forgotten() -> None:
    """`git://` speaks its own protocol on 9418, which an HTTP proxy will not carry.

    Asking whether a transport is *ssh* would have let this through; asking
    whether it survives the proxy is the question that matters.
    """
    parsed = parse_remote("git://github.com/owner/repo.git")
    assert parsed is not None
    assert parsed.proxied is False


def test_a_local_path_names_no_transport_and_is_declined() -> None:
    """Nothing to rewrite: it keeps working inside if the directory is mounted."""
    assert parse_remote("/srv/mirrors/repo.git") is None
    assert parse_remote("../sibling") is None


def test_an_unresolvable_name_falls_back_to_itself() -> None:
    """The safe direction: no match against the forge, so no rewrite at all."""
    assert resolved_host("lup-no-such-alias-anywhere") == "lup-no-such-alias-anywhere"


def test_this_checkouts_own_remotes_resolve_without_error() -> None:
    """Exercised against a real repository rather than a constructed string."""
    assert isinstance(remote_rewrites(Path.cwd(), "github.com"), list)


def test_a_checkout_with_no_remote_yields_no_rewrite(tmp_path: Path) -> None:
    """A directory that is not a repository answers nothing, and does not raise."""
    assert remote_rewrites(tmp_path, "github.com") == []


def test_signing_is_off_by_default_and_says_so() -> None:
    """A signature claims a human vouched. An agent commit is not that.

    Signing it with the operator's key would make the signature assert
    something untrue, so the default declines and the launch says why once.
    """
    settings = {item.key: item.value for item in SigningOff().configuration()}
    assert settings["commit.gpgsign"] == "false"
    assert "unsigned" in " ".join(item.text for item in SigningOff().notice())


def test_the_agent_key_signs_as_the_agent_and_admits_it_is_unverified() -> None:
    """The honest version of signing inside a container.

    A green badge would need the public half on the operator's account,
    which would render agent commits as theirs -- the untrue claim the
    default exists to avoid, arrived at from the other direction.
    """
    settings = {item.key: item.value for item in AgentKey().configuration()}
    assert settings["gpg.format"] == "ssh"
    assert settings["commit.gpgsign"] == "true"
    assert "unverified" in " ".join(item.text for item in AgentKey().notice())


def test_inheriting_the_checkouts_signing_says_what_it_will_cost() -> None:
    """The usual outcome is a mid-commit failure debugged as a GPG problem."""
    assert InheritedSigning().configuration() == []
    assert "boundary, not a GPG fault" in " ".join(
        item.text for item in InheritedSigning().notice()
    )


def test_the_signing_choice_reaches_the_configuration_the_container_starts_with() -> (
    None
):
    """Otherwise the declaration is a preference nothing acts on."""
    keys = {
        item.key for item in GitAccess(signing=AgentKey()).configuration(REWRITE, "tok")
    }
    assert "user.signingkey" in keys


def test_a_session_is_told_not_to_start_maintenance_it_cannot_finish() -> None:
    """The gitdir's root is read-only, so `pack-refs` cannot take its lock.

    Git starts the automatic run after an ordinary commit and reports the
    failure as three errors on stderr, after the commit has already landed.
    Nothing is wrong and it reads exactly as though something is — one commit
    was read as failed on the strength of it.
    """
    settings = {item.key: item.value for item in GitAccess().configuration(REWRITE, "")}

    assert settings["maintenance.auto"] == "0"


def test_a_writable_gitdir_is_left_to_keep_house_for_itself() -> None:
    """Saying nothing is what a project whose git can maintain itself gets.

    Sending `maintenance.auto=0` there would be this harness overruling git
    about git's own housekeeping, on the strength of a mount topology that
    project does not have.
    """
    keys = {item.key for item in GitAccess(maintains=True).configuration(REWRITE, "")}

    assert "maintenance.auto" not in keys


@pytest.fixture
def only_this_checkout_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Take away the git files a developer machine answers from.

    Git resolves an identity across system, global, local and worktree, which
    is the whole reason :func:`committer` asks git instead of reading a file
    -- and it means a machine with a global `user.email` answers before the
    repository a test builds gets to.

    The scope above all four is the environment's, which is where
    :meth:`GitAccess.environment` puts the launcher's decision so the
    confined thing cannot edit it. That one is the session's to clear, in
    `launcher_decisions_taken_away`, because a suite inheriting it is not a
    fault of this module's tests alone.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "absent-global"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "absent-system"))


def test_a_commit_made_inside_is_authored_as_the_checkout_authors(
    tmp_path: Path, only_this_checkout_answers: None
) -> None:
    """Otherwise git assembles one from the container hostname and refuses it.

    `Author identity unknown ... got 'agent@9c9dff017051.(none)'` stops every
    commit and names a machine that exists for the length of one session --
    which reads as a broken image rather than as a fact nobody carried in.
    """
    git("-C", str(tmp_path), "init", "-q")
    git("-C", str(tmp_path), "config", "user.name", "Some One")
    git("-C", str(tmp_path), "config", "user.email", "some@one.invalid")
    environment = GitAccess().environment("", REWRITE, committer(tmp_path))
    count = int(environment["GIT_CONFIG_COUNT"])
    settled = {
        environment[f"GIT_CONFIG_KEY_{index}"]: environment[f"GIT_CONFIG_VALUE_{index}"]
        for index in range(count)
    }
    assert settled["user.name"] == "Some One"
    assert settled["user.email"] == "some@one.invalid"


def test_half_an_identity_is_no_identity(
    tmp_path: Path, only_this_checkout_answers: None
) -> None:
    """Git needs both, so a name alone would be a launch that reported success.

    The commit fails identically either way; carrying half of it would move
    the failure past the one notice that could have named it.
    """
    git("-C", str(tmp_path), "init", "-q")
    git("-C", str(tmp_path), "config", "user.name", "Some One")
    assert committer(tmp_path) is None


def test_an_absent_identity_is_said_at_launch_rather_than_at_the_commit(
    tmp_path: Path, only_this_checkout_answers: None
) -> None:
    """The one moment the boundary can name what git will not."""
    git("-C", str(tmp_path), "init", "-q")
    lines = "\n".join(
        item.text for item in GitAccess().notice("", REWRITE, committer(tmp_path))
    )
    assert "user.email" in lines
