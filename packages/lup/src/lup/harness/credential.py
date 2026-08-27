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
from lup.harness.notice import Notice
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


class GitIdentity(BaseModel, frozen=True):
    """Who a commit made inside the boundary is authored as.

    Read off the host checkout and passed in, for the same reason the remote
    rewrites are: the file that answers it is `.git/config`, which the
    container can write, so an identity resolved in there is one the confined
    thing chose for itself.

    Sent at all because git has no usable fallback. With nothing configured
    it assembles one from the container's hostname and then refuses to use
    it -- `Author identity unknown ... got 'agent@9c9dff017051.(none)'` --
    which stops every commit and names a machine that exists for the length
    of one session.

    Authorship rather than a claim about who wrote the code. The signing
    member is what makes that claim, and declines to; a `Co-Authored-By`
    trailer is what records the agent. A commit authored as the operator is
    the same arrangement an editor has always had -- the person the work is
    being done for.
    """

    name: str = Field(description="The author name a contained commit carries")
    email: str = Field(description="The author address a contained commit carries")

    def configuration(self) -> list[GitSetting]:
        """The two keys git refuses to commit without."""
        return [
            GitSetting(key="user.name", value=self.name),
            GitSetting(key="user.email", value=self.email),
        ]


def committer(root: Path) -> GitIdentity | None:
    """The identity this checkout commits under, as git itself resolves it.

    Asked of `git config` rather than read out of a file, for the reason
    :func:`resolved_host` is asked of ssh: the answer is assembled from the
    system, global, local and worktree scopes in a precedence only git
    implements, and an adopter who set theirs per repository would be missed
    by anything reading one file.

    Nothing comes back unless both halves are there. Git needs both, and a
    name with no address refuses exactly as an absent one does -- so half an
    identity would be a launch that reported success and a commit that
    failed anyway.
    """

    def configured(key: str) -> str:
        try:
            return git.out("-C", str(root), "config", "--get", key).strip()
        except sh.ErrorReturnCode:
            return ""

    name, email = configured("user.name"), configured("user.email")
    return GitIdentity(name=name, email=email) if name and email else None


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

    def notice(self) -> list[Notice]:
        """A capability the session does not have, which is not a fault."""
        return [
            Notice(
                text=(
                    "Signing: off for agent commits. The signing key stays "
                    "on the host, so a commit made in here is unsigned — "
                    "sign at the merge that lands the work, or set "
                    "`signing` on the image declaration."
                ),
                urgency="boundary",
            )
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

    def notice(self) -> list[Notice]:
        """A capability the session has, said in the terms it is true in."""
        return [
            Notice(
                text=(
                    f"Signing: on, as {self.identity}, with a key held in "
                    "this container. A forge will show these as unverified "
                    "until the public half is registered — which is "
                    "correct, since they were not signed by you."
                ),
                urgency="ready",
            )
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

    def notice(self) -> list[Notice]:
        """The loud one, because its usual outcome is a mid-commit failure."""
        return [
            Notice(
                text=(
                    "Signing: inherited from this checkout. If it is "
                    "configured and the key is on the host, commits will "
                    "fail mid-way with `gpg: signing failed` — which is a "
                    "boundary, not a GPG fault."
                ),
                urgency="warning",
            )
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
    Measured rather than assumed: ``urlsplit`` reads ``forge:owner/repo.git``
    as a URL whose *scheme* is ``forge``, and reads ``git@github.com:owner/repo``
    as a path with no scheme at all -- so it cannot even be used to tell the
    two apart, let alone to take either one apart correctly.

    The obvious PyPI parser was tried and refuted for this job. ``giturlparse``
    does handle scp-like syntax, but validates against a roster of known
    forges, so it answers ``valid: False`` for a URL spelled through an ssh
    config alias -- which is precisely the case this exists for.

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

    An ssh config alias is a hostname only ssh knows: ``forge`` in a remote
    reaches ``github.com`` because ``~/.ssh/config`` says so, and nothing in
    the URL records it. Comparing the written name against a forge would
    therefore miss every remote spelled through an alias -- which is what any
    checkout looks like once its author keeps an ssh config, and is exactly
    the case a list of prefixes silently failed.

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
    first draft matched three prefixes and produced no rewrite at all for a
    remote spelled `forge:owner/repo.git` -- an ssh config alias, which no
    prefix list can recognize and only ssh can resolve. The
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
    maintains: bool = Field(
        default=False,
        description=(
            "Whether a session runs git's own repository maintenance. False "
            "because it cannot: the gitdir's root is mounted read-only, so "
            "the `pack-refs` task the automatic run starts fails on "
            "`packed-refs.lock` and prints three errors after every commit "
            "that otherwise landed — which made one commit read as failed "
            "when it had not. A project mounting its gitdir writable turns "
            "this back on and gets git's ordinary housekeeping"
        ),
    )

    def maintenance(self) -> list[GitSetting]:
        """Whether git may start its own housekeeping, as a setting or nothing.

        Nothing when it may, so a session that can maintain its repository is
        one this said nothing about rather than one told to do what it would
        have done anyway.

        Not about the forge, unlike everything else here, and it sits beside
        them because :meth:`configuration` is the one channel a contained
        session's git settings travel through -- ``GIT_CONFIG_COUNT`` has to
        match the pairs beneath it, so a second assembly would be a second
        thing to keep in step with this one.
        """
        return [] if self.maintains else [GitSetting(key="maintenance.auto", value="0")]

    def helper(self, token: str) -> GitSetting:
        """What git answers an authentication challenge with, token or not.

        With a token, the variable is read out of the environment rather than
        out of a file, so nothing lands in the tree and nothing survives the
        container: ``store`` would write it into the config home, and a
        prompt would hang a non-interactive session forever.

        Without one, a helper is installed anyway and refuses on stderr. That
        is the boundary's only chance to get a sentence in at the moment
        somebody needs it -- git's own account of an unanswerable challenge
        names the URL and never the variable that would have answered it, and
        the launch notice that did name it has scrolled past by then.
        """
        answered = (
            f"echo username={self.username}; echo password=${self.token_variable}"
            if token
            else (
                f'echo "lup: no token in {self.token_variable}, so this '
                "session cannot authenticate to a forge; export it on the "
                'host before the launch" >&2; exit 1'
            )
        )
        return GitSetting(key="credential.helper", value=f"!f() {{ {answered}; }}; f")

    def configuration(
        self,
        rewrites: list[RemoteRewrite],
        token: str,
        identity: GitIdentity | None = None,
    ) -> list[GitSetting]:
        """Every git setting the container starts with, in one list.

        The rewrites point each ssh spelling at HTTPS, the helper answers for
        the token or refuses in its name, the identity says who a commit is
        authored as, and the signing member says what it claims.

        A rewrite used to be withheld unless a token came with it, on the
        reasoning that half this arrangement is worse than none: a remote
        redirected to HTTPS and then asked for a password, in a session with
        no human at the other end. What refutes it is that the prompt is
        gone. Terminal prompting is off inside the image, so the unanswerable
        challenge that argument feared is now a refusal with a reason, and
        the rewrite is the only thing making a remote addressable at all.
        """
        return [
            *[rewrite.setting() for rewrite in rewrites],
            *(identity.configuration() if identity is not None else []),
            *self.signing.configuration(),
            *self.maintenance(),
            self.helper(token),
        ]

    def environment(
        self,
        token: str,
        rewrites: list[RemoteRewrite],
        identity: GitIdentity | None = None,
    ) -> EnvVars:
        """The variables that carry the token and the configuration inside.

        ``GIT_CONFIG_COUNT`` and its numbered pairs, because git reads them
        above every configuration file: nothing inside the checkout can
        override what was decided out here, and nothing has to be written
        into a tree the agent can edit. A file would be both.

        Sent whether or not there is a token, which is the part that used to
        be withheld. An ssh remote is unreachable from in here for a reason
        that has nothing to do with credentials -- the session's network
        resolves no names at all -- so the rewrite is what makes a remote
        addressable, and a public repository is readable through it on no
        credential whatsoever. Holding it back until a token appeared turned
        every tokenless fetch into a hostname that would not resolve, which
        reads as a broken container rather than as a boundary, and left the
        signing settings unsent beside it: the launch said commits were
        unsigned while the checkout's own ``commit.gpgsign`` still stood.
        """
        settings = self.configuration(rewrites, token, identity)
        carried = (
            # `gh` reads its own variable and shares the one credential.
            {self.token_variable: token, "GH_TOKEN": token} if token else {}
        )
        return {
            **carried,
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

    def authorship(self, identity: GitIdentity | None) -> list[Notice]:
        """Who a commit made in here will be authored as, or that none can be.

        The absent case is the one worth a line. Git's own account of it
        names a container hostname and no way to fix it from where the
        reader is standing, and it arrives in the middle of the commit that
        was the point of the session rather than before it.
        """
        return [
            Notice(
                text=(
                    f"Commits: authored as {identity.name} <{identity.email}>, "
                    "carried from this checkout. Signing is the separate "
                    "claim, said below."
                ),
                urgency="ready",
            )
            if identity is not None
            else Notice(
                text=(
                    "Commits: this checkout sets no `user.name` and "
                    "`user.email`, so a commit in here refuses with `Author "
                    "identity unknown` and a hostname that lives as long as "
                    "the container. Set them on the host and relaunch."
                ),
                urgency="warning",
            )
        ]

    def notice(
        self,
        token: str,
        rewrites: list[RemoteRewrite],
        identity: GitIdentity | None = None,
    ) -> list[Notice]:
        """What the launch says about reaching the forge, before it is needed.

        The absent-token case is the one worth being careful about. It is not
        an error -- plenty of work never touches a remote -- but discovering
        it as a credential prompt inside a non-interactive session is the
        failure the manifest exists to prevent, so it is said at launch with
        the variable named.
        """
        if not token:
            reach = (
                f"{len(rewrites)} ssh remote spelling(s) rewritten to HTTPS, so "
                "a public repository still reads"
                if rewrites
                else "no ssh remote to rewrite"
            )
            return [
                Notice(
                    text=(
                        f"Forge: no token in {self.token_variable}; {reach}. "
                        "Whatever needs a credential — a push, a private "
                        "repository — refuses in that variable's name rather "
                        "than prompting. The ssh key is on the host by design "
                        "and nothing routes to it, so nothing falls back to it."
                    ),
                    urgency="boundary",
                ),
                *self.authorship(identity),
                *self.signing.notice(),
            ]
        rewritten = (
            f"{len(rewrites)} ssh remote spelling(s) rewritten"
            if rewrites
            else "no ssh remote to rewrite"
        )
        return [
            Notice(
                text=(
                    f"Forge: {self.host} over HTTPS with the token in "
                    f"{self.token_variable}; {rewritten}. The agent can read "
                    "this token — the scope is the boundary, not the secrecy."
                ),
                urgency="ready",
            ),
            *self.authorship(identity),
            *self.signing.notice(),
        ]
