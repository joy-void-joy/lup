"""Which paths a patch writes, and how they reach the gates that read content.

`git apply` replaces tracked content wholesale by a route no content gate
sees, which is what the write row refuses -- and refusing is the one answer
that cannot be right for it, because re-authoring every hunk through `Edit` is
a transcription of the operation rather than a substitute for it.

So the targets are read instead. They are neither operands nor flag values but
lines inside the file the command is handed, in a format whose one
authoritative reader is already installed: `git apply --numstat` says what a
patch touches without applying a byte of it.
"""

from pathlib import Path

import sh

from lup.policy.assets.host import patch_write_targets
from lup.policy.kernel.lex import shell_patch_operands


def repository(root: Path, name: str, body: str) -> None:
    """A repository holding one committed file, which a patch can be cut from."""
    sh.Command("git")("init", "-q", str(root))
    (root / name).write_text(body, encoding="utf-8")
    git = sh.Command("git").bake(
        "-C", str(root), "-c", "user.email=t@e", "-c", "user.name=t"
    )
    git("add", "-A")
    git("commit", "-qm", "in")


def test_the_patch_a_command_hands_over_is_named() -> None:
    """The operand is the file to read, not the file that gets written."""
    assert shell_patch_operands("git apply fix.patch") == ["fix.patch"]


def test_flags_are_not_patches() -> None:
    """A word beginning with a dash describes the application, not the input."""
    assert shell_patch_operands("git apply -v --3way fix.patch") == ["fix.patch"]
    assert shell_patch_operands("git apply --check -- fix.patch") == ["fix.patch"]


def test_a_patch_arriving_on_standard_input_names_nothing() -> None:
    """A spelling this cannot see, and must not guess at.

    `git apply < f` carries no operand. Reporting the redirection's source
    would name the wrong file in the wrong direction -- it is read, not
    written -- so the row's own verdict answers for this form instead.
    """
    assert shell_patch_operands("git apply < fix.patch") == []


def test_a_word_that_expands_at_run_time_names_nothing() -> None:
    """What `$PATCH` is cannot be known here, so it is not claimed to be known."""
    assert shell_patch_operands("git apply $PATCH") == []


def test_another_git_subcommand_is_not_applying_a_patch() -> None:
    """`git log fix.patch` reads a path; nothing about it applies anything."""
    assert shell_patch_operands("git log fix.patch") == []


def test_git_reads_out_the_paths_a_patch_would_write(tmp_path: Path) -> None:
    """The whole point: the targets come from the format's own reader.

    Asserted against a patch Git itself produced, because the thing under test
    is that the two halves of Git agree -- what `diff` writes is what
    `apply --numstat` reports, and no reader of ours sits between them.
    """
    repository(tmp_path, "notes.md", "one\n")
    # Colour off, because `sh` hands Git a terminal and a coloured diff is not
    # a patch any more -- the escapes land between the marker and the line.
    git = sh.Command("git").bake("-C", str(tmp_path), "-c", "color.ui=false")
    (tmp_path / "notes.md").write_text("two\n", encoding="utf-8")
    (tmp_path / "fix.patch").write_text(str(git("diff")), encoding="utf-8")
    git("restore", "notes.md")

    assert patch_write_targets(["fix.patch"], tmp_path) == ["notes.md"]


def test_a_file_that_is_not_a_patch_contributes_no_target(tmp_path: Path) -> None:
    """Over-naming an operand is safe precisely because of this.

    Nothing consults these words as paths -- they go to a reader that rejects
    whatever is not a patch -- so a flag value swept up by mistake yields no
    target rather than a target nobody writes.
    """
    repository(tmp_path, "notes.md", "one\n")

    assert patch_write_targets(["notes.md"], tmp_path) == []


def test_a_missing_patch_contributes_no_target(tmp_path: Path) -> None:
    """Git cannot answer, so nothing is claimed on its behalf."""
    repository(tmp_path, "notes.md", "one\n")

    assert patch_write_targets(["absent.patch"], tmp_path) == []
