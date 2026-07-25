"""Codex apply_patch decoding and the edit policy it finally reaches.

Codex hands a hook one opaque envelope where Claude hands over structured
before/after text, so the dispatcher refused every patch unread and the
canonical edit policy never ran for a Codex edit. These tests pin the
decode, the per-file decisions it enables, and the path resolution that
keeps repo-relative rules matching inside a sibling worktree.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from lup.adapters.codex.patch import patched_files
from lup.types import JsonObject

GREETING = 'def greet():\n    return "hi"\n'


def update_envelope(path: str, body: str) -> str:
    return f"*** Begin Patch\n*** Update File: {path}\n@@\n{body}\n*** End Patch"


def document(text: str) -> Callable[[str], str | None]:
    return lambda _path: text


def test_update_applies_hunks_over_the_current_document() -> None:
    envelope = update_envelope(
        "module.py", ' def greet():\n-    return "hi"\n+    return "hello"'
    )

    changes = patched_files(envelope, document(GREETING))

    assert len(changes) == 1
    assert changes[0].path == "module.py"
    assert changes[0].before == GREETING
    assert changes[0].after == 'def greet():\n    return "hello"\n'


def test_add_file_carries_no_preimage() -> None:
    envelope = "*** Begin Patch\n*** Add File: new.py\n+one\n+two\n*** End Patch"

    changes = patched_files(envelope, document(""))

    assert changes[0].before is None
    assert changes[0].after == "one\ntwo"


def test_delete_file_carries_no_postimage() -> None:
    envelope = "*** Begin Patch\n*** Delete File: gone.py\n*** End Patch"

    changes = patched_files(envelope, document("body\n"))

    assert changes[0].before == "body\n"
    assert changes[0].after is None


def test_move_reports_the_destination_path() -> None:
    envelope = (
        "*** Begin Patch\n*** Update File: old.py\n*** Move to: new.py\n"
        "@@\n context\n*** End Patch"
    )

    changes = patched_files(envelope, document("context\n"))

    assert changes[0].path == "new.py"


def test_one_envelope_yields_every_file_it_touches() -> None:
    envelope = (
        "*** Begin Patch\n*** Add File: a.py\n+a\n*** Delete File: b.py\n*** End Patch"
    )

    changes = patched_files(envelope, document("b\n"))

    assert [change.path for change in changes] == ["a.py", "b.py"]


@pytest.mark.parametrize(
    ("envelope", "message"),
    [
        ("no header at all", "Begin Patch"),
        ("*** Begin Patch\n*** End Patch", "no file changes"),
        (update_envelope("m.py", " missing"), "does not match"),
    ],
)
def test_an_envelope_the_parser_cannot_vouch_for_raises(
    envelope: str, message: str
) -> None:
    """Refusing to guess keeps the caller on its conservative branch."""
    with pytest.raises(ValueError, match=message):
        patched_files(envelope, document("other\n"))


def bundled_dispatcher() -> ModuleType:
    path = Path.cwd() / ".codex/plugins/lup/hooks/scripts/policy.py"
    spec = importlib.util.spec_from_file_location("bundled_codex_policy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worktree(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    return root


def patch_payload(envelope: str) -> JsonObject:
    return {"tool_name": "apply_patch", "tool_input": {"command": envelope}}


class TestDispatchedPatches:
    def test_an_ordinary_small_edit_is_allowed(self, tmp_path: Path) -> None:
        root = worktree(tmp_path / "feature")
        target = root / "module.py"
        target.write_text(GREETING, encoding="utf-8")
        envelope = update_envelope(
            str(target), ' def greet():\n-    return "hi"\n+    return "hello"'
        )

        decision = bundled_dispatcher().dispatch(patch_payload(envelope))

        assert decision.effect == "allow"

    def test_a_human_owned_file_is_still_protected_in_a_sibling_worktree(
        self, tmp_path: Path
    ) -> None:
        """The rule matches README.md repo-relative, not cwd-relative."""
        root = worktree(tmp_path / "feature")
        target = root / "README.md"
        target.write_text("# Title\n", encoding="utf-8")
        envelope = update_envelope(str(target), "-# Title\n+# Rewritten")

        decision = bundled_dispatcher().dispatch(patch_payload(envelope))

        assert decision.effect != "allow"

    def test_an_unparsable_envelope_never_reports_allow(self) -> None:
        with pytest.raises(ValueError):
            bundled_dispatcher().dispatch(patch_payload("garbage"))


def test_worktree_path_relativizes_against_the_holding_worktree(
    tmp_path: Path,
) -> None:
    root = worktree(tmp_path / "feature")

    resolved = bundled_dispatcher().worktree_path(str(root / "src" / "app.py"))

    assert resolved == "src/app.py"
