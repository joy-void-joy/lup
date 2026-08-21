"""Reaching a remote from inside the boundary, on a credential worth the reach.

The ssh key stays on the host and nothing routes to it, so what a contained
session can reach is exactly what the token admits. Two things must stay true
for that to be a boundary rather than a nuisance, and both are easy to lose:
the rewrite that makes the token reachable has to be decided outside, and it
has to arrive somewhere the confined thing cannot reach behind.
"""

from pathlib import Path

from lup.harness.credential import (
    AgentKey,
    GitAccess,
    InheritedSigning,
    RemoteRewrite,
    SigningOff,
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


def test_no_token_configures_nothing_at_all() -> None:
    """A rewrite with no credential is a prompt nobody in here can answer.

    Half of this arrangement is worse than none: the remote would be
    redirected to HTTPS and then ask for a password, in a session with no
    human at the other end of it.
    """
    assert GitAccess().environment("", REWRITE) == {}


def test_the_absence_of_a_token_is_said_at_launch() -> None:
    """Not an error -- plenty of work never touches a remote.

    But discovering it as a credential prompt inside a non-interactive
    session is exactly the failure the manifest exists to prevent, so the
    variable is named before anything needs it.
    """
    spoken = " ".join(GitAccess().notice("", []))
    assert "LUP_GIT_TOKEN" in spoken
    assert "ssh key is on the host" in spoken


def test_the_launch_says_the_agent_can_read_the_token() -> None:
    """Stated rather than implied, because hiding it would be theatre.

    An agent that can run `git push` with a credential can also read it. The
    scope is the boundary, not the secrecy, and a reader who believed
    otherwise would scope the token wrongly.
    """
    assert "not the secrecy" in " ".join(GitAccess().notice("tok", REWRITE))


def test_an_ssh_config_alias_is_taken_apart_rather_than_pattern_matched() -> None:
    """The case that refuted a prefix list, and it is this repository's own remote.

    `jvj:joy-void-joy/lup.git` begins with none of `git@`, `ssh://git@` or
    `ssh://`. A list of ssh spellings produced no rewrite for it at all, so a
    contained session would have kept an ssh remote with no ssh to reach it,
    and the push would have failed in the transport's vocabulary rather than
    the boundary's.
    """
    parsed = parse_remote("jvj:joy-void-joy/lup.git")
    assert parsed is not None
    assert parsed.prefix == "jvj:"
    assert parsed.host == "jvj"
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
    assert "unsigned" in " ".join(SigningOff().notice())


def test_the_agent_key_signs_as_the_agent_and_admits_it_is_unverified() -> None:
    """The honest version of signing inside a container.

    A green badge would need the public half on the operator's account,
    which would render agent commits as theirs -- the untrue claim the
    default exists to avoid, arrived at from the other direction.
    """
    settings = {item.key: item.value for item in AgentKey().configuration()}
    assert settings["gpg.format"] == "ssh"
    assert settings["commit.gpgsign"] == "true"
    assert "unverified" in " ".join(AgentKey().notice())


def test_inheriting_the_checkouts_signing_says_what_it_will_cost() -> None:
    """The usual outcome is a mid-commit failure debugged as a GPG problem."""
    assert InheritedSigning().configuration() == []
    assert "boundary, not a GPG fault" in " ".join(InheritedSigning().notice())


def test_the_signing_choice_reaches_the_configuration_the_container_starts_with() -> (
    None
):
    """Otherwise the declaration is a preference nothing acts on."""
    keys = {item.key for item in GitAccess(signing=AgentKey()).configuration(REWRITE)}
    assert "user.signingkey" in keys
