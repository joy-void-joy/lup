"""How much a launched session asks before it acts, in each runtime's words.

Each runtime has its own words for this and no two of them line up: Claude
Code takes one permission mode, Codex an approval policy and a sandbox mode
that move independently. So the declaration carries each runtime's own words
as validated data — the way an image names the CLIs it installs — and the
launcher spells them onto each command line. What is shared is the rule that
decides where they apply, :func:`unconfining`, stated once rather than per
runtime.

The words are the runtimes' own, taken from their documentation and measured
against the installed CLIs: Claude Code 2.1.282 accepts every mode below for
``--permission-mode`` — it lists ``manual`` and still parses ``default``, the
spelling ``manual`` became an alias of in 2.1.200 — and Codex 0.156.1 lists
``on-request`` and ``never`` for ``--ask-for-approval``, its documentation
calling ``untrusted`` unsupported and ``on-failure`` deprecated, and the three
sandbox modes for ``--sandbox``.

Spoken at launch rather than written into a settings file for a reason the
vendor documentation gives for Claude Code: ``auto`` and ``bypassPermissions``
do not take effect from a project's or a checkout's own settings file, only
from the user's, the managed settings, or the command line. A repository that
wants a posture therefore has to say it at launch, which is what this is.

Plain assignments rather than ``type`` statements, as :data:`NetworkMode` is,
because the launchers take these as options and the CLI framework reads a
``Literal`` but not an alias wrapping one.
"""

from typing import Literal

from pydantic import BaseModel, Field

ClaudePermissionMode = Literal[
    "default",
    "manual",
    "acceptEdits",
    "plan",
    "auto",
    "dontAsk",
    "bypassPermissions",
]
"""Claude Code's permission modes, as ``--permission-mode`` spells them.

Both spellings of the asking mode are here: ``default`` is the one every
release parses and ``manual`` the one current releases list, so a declaration
written for either still reaches the CLI it was written against."""

CodexApprovalPolicy = Literal["on-request", "never"]
"""When Codex asks before running a command, as ``--ask-for-approval`` spells it."""

CodexSandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
"""Codex's own sandbox, as ``--sandbox`` spells it."""


def unconfining(value: str | bool) -> bool:
    """Whether a posture value stops a runtime asking or confining on its own.

    These are the values only a container may stand in for: Claude Code's
    ``auto``, where a classifier answers in place of a person, and
    ``bypassPermissions``, where nothing does; Codex never asking; Codex's own
    sandbox switched off; Claude Code's Bash sandbox switched off. Everything
    else leaves the runtime's own asking or its own sandbox standing.
    """
    match value:
        case "auto" | "bypassPermissions" | "never" | "danger-full-access" | False:
            return True
        case _:
            return False


class LaunchPosture(BaseModel, frozen=True):
    """What each runtime is told about asking, at the moment it is launched.

    A mode's knob: a normal session carries no posture of its own and runs
    on whatever each runtime's configuration says, a machine may default
    one in its registry, and a launch's own flags outrank both. Every field
    left unset passes nothing.

    A value that stops a runtime asking or confining — see
    :func:`unconfining` — is the container's to stand in for, so a declared
    one applies to a contained launch only: a mode naming one is refused on
    the host, and a machine default naming one is left behind there with a
    line saying so. A flag stands wherever it is typed.
    """

    permission_mode: ClaudePermissionMode | None = Field(
        default=None,
        description=(
            "Claude Code's permission mode. ``auto`` has a classifier approve "
            "or refuse each action in place of a person; ``bypassPermissions`` "
            "approves everything and is the runtime's own boundary switched "
            "off"
        ),
    )
    approval_policy: CodexApprovalPolicy | None = Field(
        default=None,
        description=(
            "Whether Codex asks before a command: ``on-request`` lets the "
            "model ask when it judges it should, ``never`` never asks"
        ),
    )
    sandbox_mode: CodexSandboxMode | None = Field(
        default=None,
        description=(
            "Codex's own sandbox. Inside the container the launcher already "
            "stands it down to ``danger-full-access`` when nothing is declared, "
            "because ``workspace-write`` cuts the network the session's proxy "
            "is reached over; declaring a mode here overrides that"
        ),
    )
    bash_sandbox: bool | None = Field(
        default=None,
        description=(
            "Claude Code's own Bash sandbox. ``False`` stands it down for the "
            "launch, which a contained launch already does on its own; "
            "declared, it holds on the host too, where a project's settings "
            "would otherwise switch it on"
        ),
    )

    @classmethod
    def unattended(cls) -> "LaunchPosture":
        """A session nothing asks, in each runtime's own words for it.

        Claude Code's ``auto``, whose classifier answers in place of a person,
        with its own Bash sandbox off, and Codex's nearest equivalent — it has
        no such mode — which is never asking with its own sandbox off, the
        pairing its documentation names for a container that provides the
        isolation. Both are meant for the inside of a container, which is the
        only place a declared posture is applied.
        """
        return cls(
            permission_mode="auto",
            approval_policy="never",
            sandbox_mode="danger-full-access",
            bash_sandbox=False,
        )
