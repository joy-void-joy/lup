"""Non-interactive shell environment for agent-run commands.

Credential helpers prompt on ``/dev/tty`` — the terminal the native TUI or
resolver console owns — so a passphrase or editor prompt raised from an agent
shell wedges the whole session instead of failing. These variables make every
such command fail fast with a readable error: ssh refuses to prompt (keys
already loaded in ssh-agent keep working), git never opens an editor or pager,
and gh and keyring lookups stay non-interactive. The devtools launch and
resolver flows merge these defaults beneath the inherited environment at
every agent spawn point. Explicit caller values win except ``VIRTUAL_ENV``:
the child project must select its own environment from its working directory.
"""

from collections.abc import Mapping

from lup.types import EnvVars

# lup: ignore[library-default] — each pair is the variable and off-value git, ssh, gh, and keyring document
NON_INTERACTIVE_SHELL_ENV: EnvVars = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_EDITOR": "true",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GH_PAGER": "cat",
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
}


def non_interactive_environment(
    base: Mapping[str, str],  # lup: ignore[dict-str-payload] — open env-var map
) -> EnvVars:
    """Merge shell defaults without binding a session to its caller's venv."""
    merged = {**NON_INTERACTIVE_SHELL_ENV, **base}
    return {name: value for name, value in merged.items() if name != "VIRTUAL_ENV"}


# lup: ignore[library-default] — each name is one a launcher decides for the
# process it starts, listed so a caller can take them away rather than guess
LAUNCHER_DECIDED_ENV: list[str] = [
    "LUP_CONTAINED",
    "UV_PROJECT_ENVIRONMENT",
    "GIT_CONFIG_COUNT",
]
"""What a launched process is told about where it is, rather than what it does."""


def launcher_decided_names(
    environ: Mapping[str, str],  # lup: ignore[dict-str-payload] — open env-var map
    declared: list[str] = LAUNCHER_DECIDED_ENV,
) -> list[str]:
    """Every variable name a launcher set, with the numbered ones expanded.

    A test suite is the caller this exists for. Each of these answers a
    question a test means to ask of the code: whether a boundary sits under
    it, where a sync lands, who the checkout commits as. A suite that
    inherits them measures the session it runs in -- so the same test passes
    on the machine that wrote it and fails inside the container that machine
    builds, which is where the whole class was found.

    ``GIT_CONFIG_COUNT`` is expanded rather than cleared alone, because git
    reads it as the length of a numbered series. Clearing the count is enough
    to stop git reading the pairs and leaves them behind for whoever reads the
    environment next, and a half-cleared scope is worse than either.
    """
    counted = (
        environ["GIT_CONFIG_COUNT"].strip() if "GIT_CONFIG_COUNT" in environ else ""
    )
    return [
        *declared,
        *(
            f"GIT_CONFIG_{half}_{index}"
            for index in range(int(counted) if counted.isdigit() else 0)
            for half in ("KEY", "VALUE")
        ),
    ]
