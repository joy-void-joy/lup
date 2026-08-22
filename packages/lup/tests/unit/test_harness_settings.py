"""What the settings artifact carries out of a declaration.

The artifact is committed and drift-checked, so most of the rendering proves
itself. What does not is anything a value could be lost to on the way — a
refusal is falsey, and it has to reach the file as a decision rather than be
filtered out for looking like an absence.
"""

from lup.devtools.harness.settings import (
    Settings,
    credential_read_denials,
    project_settings,
)
from lup.harness.models import HookSandbox, HookSet


def test_a_refused_plugin_is_rendered_rather_than_dropped() -> None:
    """False says something absence cannot, so it has to survive the render.

    Settings scopes resolve per key: a project entry outranks the user's, so a
    refusal here holds against a plugin that is enabled globally. Leaving the
    key out defers to whatever the user has instead — which for an editor
    language server is a second checker over the same files, contending with
    the per-edit check that is actually wired to the gates.
    """
    declared = Settings(official_plugins={"kept@vendor": True, "refused@vendor": False})

    rendered = project_settings(declared, None)

    assert rendered["enabledPlugins"] == {"kept@vendor": True, "refused@vendor": False}


def test_a_declared_credential_is_denied_to_the_file_tools_too() -> None:
    """The sandbox deny governs Bash alone, and Read never reaches it.

    Read, Edit, Grep and Glob run in the session's own process, so a path
    declared as a credential was denied to the shell and readable by the file
    tools. Both renderings come from the one declaration, so the pair cannot
    name different paths.

    Two patterns per path because the declaration does not say which entries
    are directories, and `Read` rather than `Grep` because Claude Code
    consults file permissions against `Read` and `Edit` rules only.
    """
    hooks = HookSet(
        id="probe",
        policy_ids=[],
        sandbox=HookSandbox(credential_paths=["~/.ssh", "~/.aws/credentials"]),
    )

    assert credential_read_denials(hooks) == [
        "Read(~/.ssh)",
        "Read(~/.ssh/**)",
        "Read(~/.aws/credentials)",
        "Read(~/.aws/credentials/**)",
    ]


def test_a_declaration_without_a_sandbox_denies_nothing_extra() -> None:
    """A project that declares no boundary gets no rules invented for it."""
    assert credential_read_denials(None) == []
    assert credential_read_denials(HookSet(id="probe", policy_ids=[])) == []
