"""A shell write that carries its content is judged by what it would write.

The premise a redirection was answered on: a command produces its output by
running, so before the fact there is nothing for the content gates to read,
and the write is judged by its path alone. `written_review` exists because
that premise is true — it puts the same gates to the file afterwards, which is
the best that can be done for `dev render > docs/api.md`.

It is not true of `cat > f <<'EOF'` or `echo x > f`. The bytes are sitting in
the command, and the anti-pattern audit, the review-note gate and the size
budget can read exactly what an `Edit` would have shown them, at the moment
that still changes the answer. Measured before this: a heredoc replaced a
tracked library module with one line, allowed and unprompted.
"""

from pathlib import Path

from lup.policy.kernel.lex import authored_writes
from lup.policy.kernel.rows import PathRoleRow
from lup.policy.models import Decision, ShellCommand
from lup.policy.rules import EditPolicy, ShellPolicy
from lup.policy.vocabulary import default_vocabulary

SCRATCH = [PathRoleRow(root="tmp", role="scratch")]
"""The one role these cases turn on, declared as a project would declare it."""


def judged(command: str, root: Path) -> Decision:
    """One command, put to a shell policy whose writes reach the edit gates."""
    return ShellPolicy(
        default_vocabulary(),
        path_roles=SCRATCH,
        authored=EditPolicy(protected=[], path_roles=SCRATCH),
    ).decide(ShellCommand(command=command, cwd=root))


def unreviewed(command: str, root: Path) -> Decision:
    """The same command with no edit policy behind it, as it was judged before."""
    return ShellPolicy(default_vocabulary(), path_roles=SCRATCH).decide(
        ShellCommand(command=command, cwd=root)
    )


def test_a_heredoc_replacing_a_source_file_reaches_the_gates(tmp_path: Path) -> None:
    """The hole this closes, stated against the shape that opened it.

    A redirection declares its route reviewed, which is what lets the write
    row allow an overwrite of tracked source: the gates do read it, just
    afterwards. Here they can read it now, and what they are shown is a whole
    module replaced by one line.
    """
    module = tmp_path / "engine.py"
    module.write_text("def run() -> int:\n    return 1\n", encoding="utf-8")
    command = "cat > engine.py <<'EOF'\nx = 1\nEOF"

    assert unreviewed(command, tmp_path).effect == "allow"
    assert judged(command, tmp_path).effect == "ask"


def test_a_write_that_drops_a_review_note_is_refused(tmp_path: Path) -> None:
    """The gate the route was going around, and the reason it is not advisory.

    Deleting review feedback is denied wherever an edit reaches, and a
    redirection reached nowhere: the note was in the file, the replacement
    does not carry it, and nothing before this compared the two.
    """
    module = tmp_path / "engine.py"
    module.write_text("# lup: this needs a second look\nx = 1\n", encoding="utf-8")

    verdict = judged("cat > engine.py <<'EOF'\nx = 1\nEOF", tmp_path)

    assert verdict.effect == "deny"


def test_content_produced_by_running_keeps_the_answer_it_had(tmp_path: Path) -> None:
    """The premise still holds where it holds, and nothing is refused for it.

    A command whose output only exists once it has run offers the gates
    nothing to read, and being unreadable is not a reason to stop it — that
    is what the after-the-fact review is for.
    """
    (tmp_path / "engine.py").write_text("x = 1\n", encoding="utf-8")

    assert judged("ls -la > engine.py", tmp_path).effect == "allow"


def test_a_scratch_write_is_still_ordinary_work(tmp_path: Path) -> None:
    """The common case, which must not become a question.

    Scratch is disposable by declaration, and the gates read it as such —
    which is the whole reason this can be turned on without putting an
    approval in front of every `echo x > tmp/out`.
    """
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    (scratch / "out.txt").write_text("old\n", encoding="utf-8")

    assert judged("echo hello > tmp/out.txt", tmp_path).effect == "allow"
    assert judged("echo hello >> tmp/out.txt", tmp_path).effect == "allow"


def test_only_the_shapes_that_can_be_read_are_read() -> None:
    """What the reader claims, stated as the list of shapes it claims it for.

    A reading that was wrong would hand the gates a document the command
    never writes, which is worse than handing them nothing — so an unquoted
    heredoc, which the shell substitutes into, is absent on purpose, and so
    is every printf conversion outside the grammar the reader states.
    """
    assert authored_writes("cat > f.py <<'EOF'\nx = 1\nEOF") == [
        {"path": "f.py", "content": "x = 1\n", "append": False}
    ]
    assert authored_writes("echo -n 'x' >> f.py") == [
        {"path": "f.py", "content": "x", "append": True}
    ]
    assert authored_writes("printf '%s' x > f.py") == [
        {"path": "f.py", "content": "x", "append": False}
    ]
    assert authored_writes("cat > f.py <<EOF\nx = 1\nEOF") == []
    assert authored_writes('echo "$HOME" > f.py') == []
    assert authored_writes("cat a.txt b.txt > c.txt") == []
    assert authored_writes("dev render > docs/api.md") == []


def test_a_printf_format_is_rendered_or_left_alone() -> None:
    """The format printf reuses, and the conversions this declines to render.

    printf's first argument is a program: escapes, conversions and a cycle
    that reapplies the whole format until the operands run out. What that
    argues for is a stated grammar rather than an absence — `%s`, `%%` and
    the eight named escapes — and a refusal of everything outside it, since
    `%d` formats a number this reader does not know how to write.
    """
    assert authored_writes("printf 'x = 1\\n' > f.py") == [
        {"path": "f.py", "content": "x = 1\n", "append": False}
    ]
    assert authored_writes("printf '%s = %s\\n' x 1 y 2 > f.py") == [
        {"path": "f.py", "content": "x = 1\ny = 2\n", "append": False}
    ]
    assert authored_writes("printf '%d\\n' 5 > f.py") == []
    assert authored_writes("printf '\\043\\n' > f.py") == []
    assert authored_writes("printf 'x' spare > f.py") == []
    assert authored_writes("printf -v out 'x' > f.py") == []


def test_a_tee_is_read_through_its_operands_and_its_pipe() -> None:
    """The other route to a file, and the way it is nearly always spelled.

    `tee` names its targets as operands rather than through a redirection,
    and what it copies to them arrives on standard input — from a heredoc of
    its own, or down a pipe from a segment that carried its bytes. Measured
    before this: `echo 'x = 1' | tee packages/lup/src/lup/seams.py` replaced
    a tracked library module, settled by a capture rather than asked about.
    """
    assert authored_writes("tee f.py <<'EOF'\nx = 1\nEOF") == [
        {"path": "f.py", "content": "x = 1\n", "append": False}
    ]
    assert authored_writes("echo 'x = 1' | tee -a f.py") == [
        {"path": "f.py", "content": "x = 1\n", "append": True}
    ]
    assert authored_writes("cat <<'EOF' | tee a.py b.py\nx = 1\nEOF") == [
        {"path": "a.py", "content": "x = 1\n", "append": False},
        {"path": "b.py", "content": "x = 1\n", "append": False},
    ]
    assert authored_writes("ls | tee f.py") == []
    assert authored_writes("echo 'x = 1' | tee /dev/null") == []
    assert authored_writes("echo 'x = 1' | tee --output-error=warn f.py") == []


def test_a_stream_sink_beside_the_write_does_not_hide_it() -> None:
    """`2>/dev/null` is not a second target, so it does not make the read give up.

    A segment is read only where it writes one file, because two targets and
    one body says nothing about which file gets the bytes. A sink is neither:
    nothing is destroyed there and no gate has anything to read, which is
    already why `shell_write_targets` leaves it out.
    """
    assert authored_writes("cat > f.py <<'EOF' 2>/dev/null\nx = 1\nEOF") == [
        {"path": "f.py", "content": "x = 1\n", "append": False}
    ]
