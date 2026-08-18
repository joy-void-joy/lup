"""What the settings artifact carries out of a declaration.

The artifact is committed and drift-checked, so most of the rendering proves
itself. What does not is anything a value could be lost to on the way — a
refusal is falsey, and it has to reach the file as a decision rather than be
filtered out for looking like an absence.
"""

from lup.devtools.harness.settings import Settings, project_settings


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
