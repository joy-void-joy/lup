"""Reaching the forge from inside the boundary, on a credential worth the reach.

The ssh key stays on the host and nothing routes to it. That is the decision
the container rests on, and it is not negotiable by convenience: an agent
holding an ssh-agent socket can sign anything and reach every host that key
reaches, which is all-or-nothing in the one direction that matters. A forge
token is not all-or-nothing, and that asymmetry is the entire opening.

So the session reaches the forge over HTTPS with a token scoped to what the
work needs -- contents and pull requests on the repositories in play, and
nothing else -- and every ssh remote is rewritten to the HTTPS spelling on
the way in.

**Where the rewrite is computed is load-bearing.** Remote spellings are
unbounded: ``git@host:``, ``ssh://``, an ssh config alias, an ``insteadOf``
already in play, a non-GitHub host entirely. So the rewrite cannot match on
spelling -- it has to resolve each remote to a URL and rewrite by resolved
host. But resolving means reading ``.git/config``, and inside the container
that file is writable by the thing being confined: it carries
``core.sshCommand``, ``diff.external`` and ``url.*.insteadOf`` pointing at
``ext::sh -c``, so a container that could decide its own rewrite could decide
to have none. The resolution happens on the host, before the container
starts, and arrives as configuration the container cannot reach behind.

**And the configuration arrives in the environment, not in a file.** Git
reads ``GIT_CONFIG_COUNT`` and its numbered pairs at the highest precedence,
above every file -- so nothing inside the checkout can override what the
launcher decided, and nothing has to be written into a tree the agent can
edit. A file would be both.

**The agent can read the token.** That is not a leak this could close: an
agent that can run ``git push`` with a credential can also read it, and
hiding it would be theatre. The scope is the boundary, not the secrecy --
which is why the scope is the part worth getting right, and why the token
lives outside the checkout rather than in a gitignored file the undo layer
cannot restore and ``git clean -fdx`` destroys.
"""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import sh
from pydantic import BaseModel, Discriminator, Field

from lup.devtools.utils import git
from lup.types import EnvVars


class RemoteAddress(BaseModel, frozen=True):
    """One remote URL taken apart the way git's own grammar takes it apart.

    Three fields, because three different questions get asked of a remote and
    matching on its spelling answers none of them reliably. ``prefix`` is what
    an ``insteadOf`` rewrite has to match, character for character. ``host`` is
    what the URL *names*, which may be an ssh config alias rather than a
    hostname. ``proxied`` is whether the transport survives an HTTP proxy as
    written -- which is the question that actually matters, because a filtered
    container's only way out speaks HTTP and HTTPS and nothing else.
    """

    prefix: str = Field(description="What an insteadOf rewrite must match")
    host: str = Field(description="What the URL names, possibly an ssh alias")
    proxied: bool = Field(
        description="Whether this transport can cross an HTTP proxy as written"
    )


class GitSetting(BaseModel, frozen=True):
    """One git configuration key and what it is set to."""

    key: str = Field(description="The configuration key, e.g. `commit.gpgsign`")
    value: str = Field(description="What it is set to")


class RemoteRewrite(BaseModel, frozen=True):
    """One ssh spelling a remote uses, and the HTTPS prefix standing in for it."""

    spelling: str = Field(description="The ssh prefix a remote URL begins with")
    https: str = Field(description="What git should reach instead")

    def setting(self) -> GitSetting:
        """This rewrite as the configuration git reads it out of."""
        return GitSetting(key=f"url.{self.https}.insteadOf", value=self.spelling)


class SigningOff(BaseModel, frozen=True):
    """Agent commits are not signed, and the launch says so once.

    The default, and the honest one. A signature claims that a particular
    human vouched for a particular commit; an agent commit is not that, and
    signing it with the operator's key would make the signature assert
    something untrue. What it costs is real and worth stating: a branch
    protection rule requiring signed commits fails on agent branches -- as a
    visible check, at push time, rather than as `gpg: signing failed` in the
    middle of a commit the agent then debugs as a GPG problem.
    """

    kind: Literal["off"] = "off"

    def configuration(self) -> list[GitSetting]:
        """Turn signing off inside the container, whatever the checkout says."""
        return [
            GitSetting(key="commit.gpgsign", value="false"),
            GitSetting(key="tag.gpgsign", value="false"),
        ]

    def notice(self) -> list[str]:
        return [
            "Signing: off for agent commits. The signing key stays on the "
            "host, so a commit made in here is unsigned — sign at the merge "
            "that lands the work, or set `signing` on the image declaration."
        ]


class AgentKey(BaseModel, frozen=True):
    """Agent commits sign, as the agent rather than as the operator.

    An ssh key held inside the container, which git has been able to sign
    with since 2.34 -- no GPG agent, no hardware token, nothing of the
    operator's reachable. The signature then says something true: a commit
    made by an agent in this container.

    What it does not buy is a green badge, and saying so is the point.
    Verification needs the public half registered somewhere: an
    ``allowed_signers`` file committed to the repository makes
    ``git log --show-signature`` verify it locally under a distinct identity,
    which is honest; registering it on the operator's forge account instead
    would render agent commits as *theirs*, which is the untrue claim this
    member exists to avoid. A bot account or a forge app is the
    honest-and-green answer, and is real per-adopter setup.
    """

    kind: Literal["agent_key"] = "agent_key"
    path: str = Field(
        default="/cfg/agent-signing",
        description=(
            "Where the key lives, inside the config home so it outlives one "
            "container and never reaches the host's own key material"
        ),
    )
    identity: str = Field(
        default="agent@lup.local",
        description="Who the signature says made the commit, which is not the operator",
    )

    def configuration(self) -> list[GitSetting]:
        """Sign with an ssh key, which needs no agent and no hardware."""
        return [
            GitSetting(key="gpg.format", value="ssh"),
            GitSetting(key="user.signingkey", value=f"{self.path}.pub"),
            GitSetting(key="commit.gpgsign", value="true"),
        ]

    def notice(self) -> list[str]:
        return [
            f"Signing: on, as {self.identity}, with a key held in this "
            "container. A forge will show these as unverified until the "
            "public half is registered — which is correct, since they were "
            "not signed by you."
        ]


class InheritedSigning(BaseModel, frozen=True):
    """Whatever the checkout's own configuration says, and what that will cost.

    Kept expressible because an adopter may have arranged for a key to be
    reachable inside the container and this policy has no business overruling
    them. Kept loud because the usual outcome is the failure the whole
    manifest exists to prevent: ``commit.gpgsign=true`` in a repository whose
    key is on the host, discovered as ``gpg: signing failed: No secret key``
    in the middle of a commit, and debugged as a GPG problem for as long as
    it takes somebody to remember there is a boundary.
    """

    kind: Literal["inherit"] = "inherit"

    def configuration(self) -> list[GitSetting]:
        """Nothing. The checkout's configuration decides, for better or worse."""
        return []

    def notice(self) -> list[str]:
        return [
            "Signing: inherited from this checkout. If it is configured and "
            "the key is on the host, commits will fail mid-way with "
            "`gpg: signing failed` — which is a boundary, not a GPG fault."
        ]


type CommitSigning = Annotated[
    SigningOff | AgentKey | InheritedSigning, Discriminator("kind")
]
"""What a commit made inside the boundary claims, if anything."""


def parse_remote(url: str) -> RemoteAddress | None:
    """Take a remote URL apart, or decline when it is not one this can rewrite.

    Git accepts three shapes and only one of them is a URL that a parser in
    the standard library reads. ``scheme://[user@]host/path`` is; the
    scp-like ``[user@]host:path`` is not, and neither is a bare local path.
    Measured rather than assumed: ``urlsplit`` reads ``jvj:owner/repo.git`` as
    a URL whose *scheme* is ``jvj``, and reads ``git@github.com:owner/repo``
    as a path with no scheme at all -- so it cannot even be used to tell the
    two apart, let alone to take either one apart correctly.

    The obvious PyPI parser was tried and refuted for this job. ``giturlparse``
    does handle scp-like syntax, but validates against a roster of known
    forges, so it answers ``valid: False`` for a URL spelled through an ssh
    config alias -- which is precisely the case this exists for, and is this
    repository's own remote.

    A local path yields nothing, which is right: there is no transport to
    rewrite, and a checkout whose remote is a directory keeps working
    unchanged inside the container as long as that directory is mounted.
    """
    if "://" in url:
        split = urlsplit(url)
        return RemoteAddress(
            prefix=f"{split.scheme}://{split.netloc}/",
            # The host without the port and without the user, because that is
            # what ssh resolves and what a forge is compared against.
            host=split.hostname or "",
            proxied=split.scheme == "https",
        )
    colon = url.find(":")
    slash = url.find("/")
    if colon < 0 or (0 <= slash < colon):
        # A bare path. It names no transport, so there is nothing to rewrite.
        return None
    # lup: ignore[string-split] — git's scp-like remote syntax, which no
    # parser in the standard library reads and which `urlsplit` actively
    # misreads; both measurements are in this function's docstring
    authority, _, _path = url.partition(":")
    # lup: ignore[string-split] — the same syntax one field further in: an
    # optional user sits before an `@`, which a hostname may not contain
    _user, _, named = authority.rpartition("@")
    return RemoteAddress(prefix=f"{authority}:", host=named or authority, proxied=False)


def resolved_host(alias: str) -> str:
    """What ssh says a name actually reaches, which may not be the name itself.

    An ssh config alias is a hostname only ssh knows: ``jvj`` in a remote
    reaches ``github.com`` because ``~/.ssh/config`` says so, and nothing in
    the URL records it. Comparing the written name against a forge would
    therefore miss every remote spelled through an alias -- which is not an
    exotic arrangement, it is this repository's own, and it is exactly the
    case a list of prefixes silently failed.

    Asked of ssh rather than read out of its configuration file, because the
    file is not the whole answer: ``Include`` directives, ``Match`` blocks, a
    system-wide config and per-user overrides all contribute, and ssh is the
    only thing that composes them. ``ssh -G`` is the documented way to ask.

    Falls back to the name as written when ssh cannot answer. That is the safe
    direction: an unresolved alias fails to match the forge, produces no
    rewrite, and leaves the remote exactly as it was outside the container.
    """
    try:
        reported = sh.Command("ssh")("-G", alias)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return alias
    for line in str(reported).splitlines():
        if line.startswith("hostname "):
            return line.removeprefix("hostname ").strip() or alias
    return alias


def remote_url(root: Path, name: str) -> str:
    """One remote's URL as git resolves it, or nothing when it cannot be had.

    Through ``get-url`` rather than by reading a listing, because git already
    has a command whose whole output is the value -- and because it applies
    the resolution: an ``insteadOf`` already in play is followed to the URL
    the remote actually reaches rather than matched on whatever somebody
    typed.
    """
    try:
        return git.out("-C", str(root), "remote", "get-url", name).strip()
    except sh.ErrorReturnCode:
        return ""


def remote_rewrites(root: Path, host: str) -> list[RemoteRewrite]:
    """Each ssh spelling this checkout's remotes use, and its HTTPS equivalent.

    Resolved here, on the host, and never inside: the file that answers this
    question is ``.git/config``, which the container can write. A rewrite
    computed in there is a rewrite the confined thing chose.

    Decided on the *resolved* host rather than on the URL's spelling, which
    is the whole of what §9.2 meant by remote spellings being unbounded. A
    first draft matched three prefixes and produced no rewrite at all for
    this repository's own remote, `jvj:joy-void-joy/lup.git` -- an ssh config
    alias, which no prefix list can recognize and only ssh can resolve. The
    container would have kept an ssh remote it has no ssh to reach, and the
    push would have failed in the transport's vocabulary rather than in the
    boundary's.
    """
    try:
        names = git.lines("-C", str(root), "remote")
    except sh.ErrorReturnCode:
        return []
    addresses = [
        address
        for name in names
        if name
        for address in [parse_remote(remote_url(root, name))]
        if address is not None and not address.proxied
    ]
    found = {
        address.prefix: RemoteRewrite(spelling=address.prefix, https=f"https://{host}/")
        for address in addresses
        if resolved_host(address.host) == host
    }
    return list(found.values())


class GitAccess(BaseModel, frozen=True):
    """How a contained session reaches the forge, and what it claims when it does."""

    host: str = Field(
        default="github.com",
        description=(
            "The forge this rewrites toward. A fine-grained, repository-"
            "scoped token is a GitHub feature; an adopter on GitLab, Gitea "
            "or a corporate host names their own host here and supplies "
            "whatever their forge's equivalent is, and gets the same rewrite"
        ),
    )
    token_variable: str = Field(
        default="LUP_GIT_TOKEN",
        description=(
            "Where the launcher reads the token from. An environment "
            "variable rather than a file inside the checkout, because a "
            "gitignored file is exactly what the undo layer cannot restore "
            "and what `git clean -fdx` destroys — the one command the "
            "recoverability argument has to keep refusing"
        ),
    )
    username: str = Field(
        default="x-access-token",
        description="What the forge expects as the username beside a token",
    )
    signing: CommitSigning = Field(
        default=SigningOff(),
        description="What a commit made inside the boundary claims, if anything",
    )

    def configuration(self, rewrites: list[RemoteRewrite]) -> list[GitSetting]:
        """Every git setting the container starts with, in one list.

        The rewrites point each ssh spelling at HTTPS, the credential helper
        answers with the token, and the signing member says what a commit
        claims. Assembled here because the three are only correct together: a
        rewrite with no credential is a prompt nobody can answer, and a
        credential with no rewrite is never reached.
        """
        return [
            *[rewrite.setting() for rewrite in rewrites],
            *self.signing.configuration(),
            # Reads the token out of the environment rather than out of a
            # file, so nothing lands in the tree and nothing survives the
            # container. `store` would write it into the config home, and a
            # prompt would hang a non-interactive session forever.
            GitSetting(
                key="credential.helper",
                value=(
                    f"!f() {{ echo username={self.username}; "
                    f"echo password=${self.token_variable}; }}; f"
                ),
            ),
        ]

    def environment(self, token: str, rewrites: list[RemoteRewrite]) -> EnvVars:
        """The variables that carry the token and the configuration inside.

        ``GIT_CONFIG_COUNT`` and its numbered pairs, because git reads them
        above every configuration file: nothing inside the checkout can
        override what was decided out here, and nothing has to be written
        into a tree the agent can edit. A file would be both.
        """
        if not token:
            return {}
        settings = self.configuration(rewrites)
        return {
            self.token_variable: token,
            # `gh` reads its own variable and shares the one credential.
            "GH_TOKEN": token,
            "GIT_CONFIG_COUNT": str(len(settings)),
            **{
                name: value
                for index, setting in enumerate(settings)
                for name, value in (
                    (f"GIT_CONFIG_KEY_{index}", setting.key),
                    (f"GIT_CONFIG_VALUE_{index}", setting.value),
                )
            },
        }

    def notice(self, token: str, rewrites: list[RemoteRewrite]) -> list[str]:
        """What the launch says about reaching the forge, before it is needed.

        The absent-token case is the one worth being careful about. It is not
        an error -- plenty of work never touches a remote -- but discovering
        it as a credential prompt inside a non-interactive session is the
        failure the manifest exists to prevent, so it is said at launch with
        the variable named.
        """
        if not token:
            return [
                f"Forge: no token in {self.token_variable}, so nothing in "
                "this session can reach a remote. The ssh key is on the host "
                "by design and nothing routes to it, so a push or a fetch "
                "will fail rather than quietly fall back to it.",
                *self.signing.notice(),
            ]
        rewritten = (
            f"{len(rewrites)} ssh remote spelling(s) rewritten"
            if rewrites
            else "no ssh remote to rewrite"
        )
        return [
            f"Forge: {self.host} over HTTPS with the token in "
            f"{self.token_variable}; {rewritten}. The agent can read this "
            "token — the scope is the boundary, not the secrecy.",
            *self.signing.notice(),
        ]
