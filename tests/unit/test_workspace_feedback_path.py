"""A committed artifact names the checkout's feedback directory, never a session's.

The notes override moves where a process writes, and the fb-status prose is
rendered into the checkout by whichever process regenerates it. Rendered under
an override it would name that session's private directory, and every other
session would then read the artifact as stale. These pin that the checkout
path ignores the override and that the rendered prose uses it.
"""

import importlib
from pathlib import Path

from lup.devtools.harness.content.skills import fb_status
from lup.workspace import paths


def test_checkout_feedback_path_ignores_the_notes_override(tmp_path: Path) -> None:
    paths.configure(root=tmp_path, notes_dir=tmp_path / "elsewhere", version="0.0.0")

    assert paths.feedback_path() == tmp_path / "elsewhere" / "feedback_loop"
    assert paths.checkout_feedback_path() == tmp_path / "notes" / "feedback_loop"


def test_fb_status_names_the_checkout_directory_under_an_override(
    tmp_path: Path,
) -> None:
    """The regeneration a session runs must render what every session shares."""
    paths.configure(
        root=tmp_path, notes_dir=tmp_path / "session" / "nested", version="0.0.0"
    )

    rendered = importlib.reload(fb_status)

    assert rendered.ANALYSIS_DIRECTORY == "notes/feedback_loop"
    assert "notes/feedback_loop" in rendered.SKILL.prompt.parts[0].text
