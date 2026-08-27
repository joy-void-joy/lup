"""Reaching a remote from inside the boundary, on a credential worth the reach.

A contained session reaches a forge on something the operator lent it, and
which thing was lent decides three separate facts that have to agree: which
transport every remote is rewritten onto, which settings git starts with, and
what the launch says happened. These hold each of the three to the same
selection, and hold the whole arrangement to one rule -- that nothing lent
appears in the argv that starts the container.
"""

from pathlib import Path

import pytest

from lup.execution.shell import git
from lup.harness.credential import (
    AgentKey,
    AgentSocket,
    EphemeralKeys,
    ForgeToken,
    GitAccess,
    HttpsTransport,
    InheritedSigning,
    NoCredential,
    RemoteRewrite,
    SigningOff,
    SshTransport,
    committer,
    parse_remote,
    remote_rewrites,
    resolved_host,
)
from lup.harness.environment import NON_INTERACTIVE_SHELL_ENV
from lup.harness.image import Image
from lup.harness.requirements import Manifest

REWRITE = [RemoteRewrite(spelling="git@github.com:", target="https://github.com/")]
TOKEN = ForgeToken(variable="LUP_GIT_TOKEN")
KEYS = EphemeralKeys(home="/tmp/lup-ssh-x", home_inside="/run/lup/ssh")
AGENT = AgentSocket(
    socket="/run/host-agent",
    inside="/run/lup/ssh-agent",
    home="/tmp/lup-ssh-x",
    home_inside="/run/lup/ssh",
)
NOTHING = NoCredential(variable="LUP_GIT_TOKEN", host="github.com")


def settled(environment: dict[str, str]) -> dict[str, str]:
    """The git configuration a container starts with, back out of its variables."""
    count = int(environment["GIT_CONFIG_COUNT"])
    return {
        environment[f"GIT_CONFIG_KEY_{index}"]: environment[f"GIT_CONFIG_VALUE_{index}"]
        for index in range(count)
    }


def test_the_configuration_arrives_above_every_file_the_container_can_write() -> None:
    """`.git/config` is inside the mount, so it is the confined thing's to edit.

    Git reads `GIT_CONFIG_COUNT` and its numbered pairs above every
    configuration file, so what the launcher decided cannot be overridden
    from inside -- and nothing had to be written into a tree the agent can
    edit. A file would have been both.
    """
    keys = settled(GitAccess().environment(REWRITE, TOKEN, True))

    assert "url.https://github.com/.insteadOf" in keys
    assert "credential.helper" in keys


def test_no_credential_still_makes_the_remote_addressable() -> None:
    """The rewrite is what a remote needs; the credential is what a push needs.

    An ssh remote is unreachable from inside a filtered session for a reason
    that has nothing to do with credentials -- it resolves no names at all --
    so withholding the rewrite until a credential appeared turned a public
    fetch that would have worked into a hostname that would not resolve,
    which reads as a broken container rather than as a boundary.
    """
    environment = GitAccess().environment(REWRITE, NOTHING, False)

    assert "url.https://github.com/.insteadOf" in settled(environment)


def test_the_helper_refuses_in_the_name_of_the_variable_that_would_answer() -> None:
    """Git names the URL it could not authenticate to, never the way in.

    A helper that fails with the variable's name in it is the boundary's only
    sentence at the moment somebody meets the wall. The launch notice that
    also named it has scrolled past by then.
    """
    helper = GitAccess().helper(False)

    assert "LUP_GIT_TOKEN" in helper.value
    assert "exit 1" in helper.value


def test_a_token_session_answers_https_challenges_with_the_variables_name() -> None:
    """The name, never the value: the container's own shell expands it.

    A helper carrying the secret would put it in `GIT_CONFIG_VALUE_n`, which
    is one of the `-e` pairs in the argv that starts the container.
    """
    helper = GitAccess().helper(True)

    assert "$LUP_GIT_TOKEN" in helper.value
    assert "x-access-token" in helper.value


def test_an_ssh_session_still_carries_a_helper_for_what_the_rewrite_did_not_touch() -> (
    None
):
    """A submodule on another forge, an HTTPS dependency, a second remote.

    Those are the ones that would otherwise meet a credential prompt, which
    is the one thing a non-interactive session cannot survive.
    """
    keys = settled(GitAccess().environment([], KEYS, False))

    assert "credential.helper" in keys


def test_an_ssh_session_reaches_its_configuration_through_the_channel_git_obeys() -> (
    None
):
    """`core.sshCommand` is the obvious spelling and the one git would ignore.

    The variable outranks the setting, and the image bakes a variable
    already — so a session set up the obvious way starts with every git
    setting correctly in place, runs `ssh -o BatchMode=yes` with no `-F`,
    never opens the configuration compiled for it, and fails on a key it is
    holding. This asserts the channel rather than the presence, because
    asserting the presence is exactly what passed while the session could
    not authenticate.
    """
    environment = GitAccess().environment([], KEYS, False)

    assert "core.sshCommand" not in settled(environment)
    assert environment["GIT_SSH_COMMAND"] == (
        "ssh -o BatchMode=yes -F /run/lup/ssh/config"
    )


def test_the_baked_non_interactive_flags_survive_being_pointed_at_a_configuration() -> (
    None
):
    """`BatchMode=yes` is what stops ssh prompting with nobody at the other end.

    Dropping it to add a config file would trade a silent failure for a
    hanging one, so the value is composed onto the image's own rather than
    written again here.
    """
    baked = NON_INTERACTIVE_SHELL_ENV["GIT_SSH_COMMAND"]
    reaching = GitAccess().environment([], KEYS, False)["GIT_SSH_COMMAND"]

    assert reaching.startswith(baked)


def test_a_forwarded_agent_carries_its_socket_beside_that_configuration() -> None:
    """Both halves, because either alone is a session that cannot sign."""
    environment = GitAccess().environment([], AGENT, False)

    assert environment["SSH_AUTH_SOCK"] == "/run/lup/ssh-agent"
    assert "-F /run/lup/ssh/config" in environment["GIT_SSH_COMMAND"]


def test_the_credentials_own_variables_come_after_the_ones_the_image_baked(
    tmp_path: Path,
) -> None:
    """Both are in one argv, and both engines take the last of a repeated `-e`.

    The image bakes `GIT_SSH_COMMAND` and the ssh rungs replace it, so which
    of the two the container ends up with is decided by nothing more visible
    than the order these are concatenated in. That is exactly the kind of
    fact that holds until somebody reorders an argv for a reason that has
    nothing to do with it.
    """
    argv = Image().session_arguments(
        tag="lup-agent:test",
        checkout=tmp_path,
        uid=1000,
        gid=1000,
        writable={},
        read_only={},
        state_volume="lup-cfg-test",
        config_home_env="CLAUDE_CONFIG_DIR",
        forge=KEYS,
    )
    spelled = [word for word in argv if word.startswith("GIT_SSH_COMMAND=")]

    assert len(spelled) == 2
    assert spelled[-1].endswith("-F /run/lup/ssh/config")
    assert "-v" in argv
    assert f"{KEYS.home}:{KEYS.home_inside}:ro" in argv


def test_each_credential_says_which_one_it_is_in_one_line() -> None:
    """The whole of what a healthy launch has to say about the forge.

    What used to travel beside it -- how many spellings were rewritten, what
    a token should be scoped to, who commits are authored as, that the agent
    can read the token -- was true and was five paragraphs, in which the one
    sentence that decides whether the session can work was indistinguishable
    from four that do not.
    """
    spoken = {
        arm.kind: [item.text for item in arm.notice()]
        for arm in (
            AgentSocket(
                socket="/run/a",
                inside="/run/lup/ssh-agent",
                home="/tmp/h",
                home_inside="/run/lup/ssh",
            ),
            KEYS,
            TOKEN,
        )
    }

    assert spoken["agent"] == ["Forge authentication: SSH via forwarded agent."]
    assert spoken["files"] == [
        "Forge authentication: SSH via ephemeral host credentials."
    ]
    assert spoken["token"] == ["Forge authentication: HTTPS via LUP_GIT_TOKEN."]


def test_remediation_appears_on_the_one_arm_that_has_something_to_do() -> None:
    """And names why each rung declined, which is what makes it actionable.

    "Configure a credential" and "the agent you are running holds no
    identity" send a reader to different places, and only the second one is
    somewhere they can act.
    """
    unavailable = NoCredential(
        variable="LUP_GIT_TOKEN",
        host="github.com",
        declined=["no ssh agent holding an identity answers at SSH_AUTH_SOCK"],
    ).notice()

    assert unavailable[0].urgency == "warning"
    assert unavailable[0].text.startswith("Forge authentication: unavailable")
    assert "public reads only" in unavailable[0].text
    assert [item.urgency for item in unavailable[1:]] == ["detail", "detail"]
    assert "no ssh agent" in unavailable[1].text


def test_a_healthy_forge_line_is_a_boundary_fact_rather_than_an_alarm() -> None:
    """Which is what puts it under `Security` and keeps `Action required` empty.

    A block where every posture is painted as a warning is a block with no
    warning colour, paid for at the one launch where something is wrong.
    """
    assert [item.urgency for item in TOKEN.notice()] == ["boundary"]
    assert [item.urgency for item in KEYS.notice()] == ["boundary"]


def test_a_token_reaches_the_container_by_name_and_never_by_value() -> None:
    """The value in argv is the value in `ps`, for every process on the host.

    Both engines read a bare `-e NAME` as "take this one from my own
    environment", so the secret crosses without being written down -- and the
    forge client's own variable is derived inside the image rather than
    passed as a second pair, because passing it would mean holding the value
    out here to pass.
    """
    environment = GitAccess().environment(REWRITE, TOKEN, True)

    assert GitAccess().inherited(True) == ["LUP_GIT_TOKEN"]
    assert GitAccess().inherited(False) == []
    assert "LUP_GIT_TOKEN" not in environment
    assert "GH_TOKEN" not in environment


def test_no_secret_reaches_the_argv_that_starts_the_container(tmp_path: Path) -> None:
    """The rule the whole arrangement rests on, checked against real argv.

    A leak here is not a leak into a log somebody could rotate: it is a
    process argument list, readable by every uid on the host for as long as
    the session runs, and copied verbatim by anything that records launches.
    """
    argv = Image().session_arguments(
        tag="lup-agent:test",
        checkout=tmp_path,
        uid=1000,
        gid=1000,
        writable={},
        read_only={},
        state_volume="lup-cfg-test",
        config_home_env="CLAUDE_CONFIG_DIR",
        forge=TOKEN,
        granted=True,
        rewrites=REWRITE,
    )

    assert "-e" in argv
    assert argv[argv.index("LUP_GIT_TOKEN") - 1] == "-e"
    assert not [word for word in argv if word.startswith("LUP_GIT_TOKEN=")]
    assert not [word for word in argv if word.startswith("GH_TOKEN=")]


def test_the_image_derives_the_forge_clients_variable_from_the_one_passed_by_name() -> (
    None
):
    """One credential, two consumers, and neither prompts for the other's.

    `gh` reads a variable of its own, and the launcher cannot pass it without
    holding the value out here -- which is the thing being avoided. So the
    entrypoint derives it from the one that crossed by name, and the
    derivation is rendered from the declaration rather than written twice, so
    an adopter who renamed the variable gets both halves renamed.
    """
    rendered = Image(forge=GitAccess(token_variable="ACME_FORGE")).dockerfile(
        Manifest()
    )

    assert 'export GH_TOKEN="$ACME_FORGE"' in rendered
    assert 'if [ -n "${ACME_FORGE:-}" ]; then' in rendered


def test_an_ssh_credential_rewrites_toward_ssh_rather_than_away_from_it() -> None:
    """Which direction the rewrite runs is the selected credential's to say.

    A token reaches HTTPS and nothing else; a key reaches ssh. Leaving each
    remote on whatever it happened to be spelled as is a checkout where half
    the remotes work.
    """
    assert TOKEN.transport("git").prefix("github.com") == "https://github.com/"
    assert KEYS.transport("git").prefix("github.com") == "git@github.com:"


def test_public_reads_are_pointed_at_the_transport_a_filtered_egress_carries() -> None:
    """Half the capability beats none of it.

    An anonymous clone works over HTTPS on no credential at all, where an ssh
    remote left as written is one a filtered container cannot even resolve.
    """
    assert NOTHING.transport("git").kind == "https"


def test_the_ssh_transport_leaves_a_remote_already_spelled_that_way_alone() -> None:
    """Character equality, because the spellings this rewrites are also ssh.

    A config alias reaches the forge over ssh under a name no container can
    resolve, so "is it ssh" is not the question -- "is it this" is.
    """
    ssh = SshTransport()
    canonical = parse_remote("git@github.com:owner/repo.git")
    alias = parse_remote("forge:owner/repo.git")
    web = parse_remote("https://github.com/owner/repo.git")

    assert canonical is not None and alias is not None and web is not None
    assert ssh.carries(canonical, "github.com")
    assert not ssh.carries(alias, "github.com")
    assert not ssh.carries(web, "github.com")


def test_the_https_transport_leaves_every_remote_that_crosses_a_proxy_alone() -> None:
    """Asked as "does it cross a proxy" rather than "does it start with https".

    A remote that already crosses one may carry a port or a user somebody put
    there on purpose, and rewriting it to a bare prefix would drop both.
    """
    web = parse_remote("https://github.com:8443/owner/repo.git")

    assert web is not None
    assert HttpsTransport().carries(web, "github.com")


def test_an_ssh_config_alias_is_taken_apart_rather_than_pattern_matched() -> None:
    """The case that refuted a prefix list, and what any ssh config produces.

    `forge:owner/repo.git` begins with none of `git@`, `ssh://git@` or
    `ssh://`. A list of ssh spellings produced no rewrite for it at all, so a
    contained session would have kept a remote it has no way to reach, and
    the push would have failed in the transport's vocabulary rather than the
    boundary's.
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
    assert isinstance(remote_rewrites(Path.cwd(), "github.com", HttpsTransport()), list)


def test_a_checkout_with_no_remote_yields_no_rewrite(tmp_path: Path) -> None:
    """A directory that is not a repository answers nothing, and does not raise."""
    assert remote_rewrites(tmp_path, "github.com", HttpsTransport()) == []


def test_a_web_remote_is_rewritten_toward_ssh_when_ssh_is_what_was_lent(
    tmp_path: Path,
) -> None:
    """The direction that did not exist while a token was the only credential.

    A checkout cloned over HTTPS is the common case, and an ssh session that
    left it alone would hold a key it never used and meet a credential prompt
    on the first push.
    """
    git("-C", str(tmp_path), "init", "-q")
    git(
        "-C",
        str(tmp_path),
        "remote",
        "add",
        "origin",
        "https://github.com/owner/repo.git",
    )

    rewrites = remote_rewrites(tmp_path, "github.com", SshTransport())

    assert [(item.spelling, item.target) for item in rewrites] == [
        ("https://github.com/", "git@github.com:")
    ]


def test_an_ssh_remote_is_rewritten_toward_https_when_a_token_is_what_was_lent(
    tmp_path: Path,
) -> None:
    """The direction that always existed, held to the same walk as the new one."""
    git("-C", str(tmp_path), "init", "-q")
    git("-C", str(tmp_path), "remote", "add", "origin", "git@github.com:owner/repo.git")

    rewrites = remote_rewrites(tmp_path, "github.com", HttpsTransport())

    assert [(item.spelling, item.target) for item in rewrites] == [
        ("git@github.com:", "https://github.com/")
    ]


def test_a_remote_on_another_forge_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """The rewrite is about one host, and every other remote keeps working."""
    git("-C", str(tmp_path), "init", "-q")
    git("-C", str(tmp_path), "remote", "add", "origin", "git@gitlab.com:owner/repo.git")

    assert remote_rewrites(tmp_path, "github.com", HttpsTransport()) == []


def test_signing_is_off_by_default_and_says_so_in_one_line() -> None:
    """A signature claims a human vouched. An agent commit is not that.

    Signing it with the operator's key would make the signature assert
    something untrue, so the default declines. What that costs a repository
    whose branch protection requires signatures belongs in the documentation
    rather than in every launch.
    """
    settings = {item.key: item.value for item in SigningOff().configuration()}
    spoken = SigningOff().notice()

    assert settings["commit.gpgsign"] == "false"
    assert [item.text for item in spoken] == ["Signing: off for agent commits."]
    assert [item.urgency for item in spoken] == ["boundary"]


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
        item.key
        for item in GitAccess(signing=AgentKey()).configuration(REWRITE, TOKEN, True)
    }

    assert "user.signingkey" in keys


def test_a_session_is_told_not_to_start_maintenance_it_cannot_finish() -> None:
    """The gitdir's root is read-only, so `pack-refs` cannot take its lock.

    Git starts the automatic run after an ordinary commit and reports the
    failure as three errors on stderr, after the commit has already landed.
    Nothing is wrong and it reads exactly as though something is — one commit
    was read as failed on the strength of it.
    """
    settings = {
        item.key: item.value
        for item in GitAccess().configuration(REWRITE, NOTHING, False)
    }

    assert settings["maintenance.auto"] == "0"


def test_a_writable_gitdir_is_left_to_keep_house_for_itself() -> None:
    """Saying nothing is what a project whose git can maintain itself gets.

    Sending `maintenance.auto=0` there would be this harness overruling git
    about git's own housekeeping, on the strength of a mount topology that
    project does not have.
    """
    keys = {
        item.key
        for item in GitAccess(maintains=True).configuration(REWRITE, NOTHING, False)
    }

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

    keys = settled(
        GitAccess().environment(REWRITE, NOTHING, False, committer(tmp_path))
    )

    assert keys["user.name"] == "Some One"
    assert keys["user.email"] == "some@one.invalid"


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
        item.text for item in GitAccess().notice(TOKEN, committer(tmp_path))
    )

    assert "user.email" in lines


def test_an_identity_that_is_there_says_nothing_at_all(
    tmp_path: Path, only_this_checkout_answers: None
) -> None:
    """A launch reporting the author of commits nobody has made yet is noise.

    It is a paragraph between the reader and the one line that mattered, and
    it was true every single time, which is what made it unreadable.
    """
    git("-C", str(tmp_path), "init", "-q")
    git("-C", str(tmp_path), "config", "user.name", "Some One")
    git("-C", str(tmp_path), "config", "user.email", "some@one.invalid")

    assert GitAccess().authorship(committer(tmp_path)) == []
