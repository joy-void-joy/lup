"""What a join must account for, and what it is allowed to do.

Two obligations rather than two prohibitions. Content one parent contributed
that the joined tree no longer holds must be dispositioned; an edit outside
the conflict set must be declared. Neither forbids the merger anything — a
rewrite and a clean-file fix are both correct answers — and both make the
choice visible.
"""

from pathlib import Path

from lup.harness.process import ExitStatus, LaunchRequest, ProcessLauncher
from lup.resolver.core import merge_problems
from lup.resolver.models import (
    DeclaredEdit,
    DropCandidate,
    HunkDisposition,
    MergeReport,
)
from lup.resolver.orchestrator import report_mismatch
from lup_template.devtools.harness.resolve import integration_branch

PARENT = "a1b2c3d4e5f6"


def candidate(path: str, missing: str = "value = compute()") -> DropCandidate:
    return DropCandidate(parent=PARENT, path=Path(path), missing=[missing])


def report(**overrides: object) -> MergeReport:
    fields = {"completed": True, "summary": "joined", **overrides}
    return MergeReport.model_validate(fields)


def test_lost_content_with_nothing_said_about_it_is_the_rejection() -> None:
    problems = merge_problems(report(), [], [candidate("src/api.py")])

    assert len(problems) == 1
    assert "src/api.py" in problems[0]


def test_a_declared_rewrite_settles_a_candidate() -> None:
    """A resolution that rewrites what it merges is correct, not suspect."""
    settled = report(
        dispositions=[
            HunkDisposition(
                path=Path("src/api.py"),
                parent=PARENT,
                fate="rewritten",
                rationale="folded into the signature the sibling introduced",
            )
        ],
        out_of_conflict_edits=[
            DeclaredEdit(path=Path("src/api.py"), rationale="same")
        ],
    )

    assert merge_problems(settled, [], [candidate("src/api.py")]) == []


def test_dispositioning_without_a_reason_does_not_settle_anything() -> None:
    silent = report(
        dispositions=[
            HunkDisposition(
                path=Path("src/api.py"), parent=PARENT, fate="dropped", rationale="  "
            )
        ]
    )

    problems = merge_problems(silent, [Path("src/api.py")], [candidate("src/api.py")])

    assert any("rationale" in problem for problem in problems)


def test_more_dispositions_than_candidates_is_never_a_problem() -> None:
    """Containment, not equality — a merger may account for more than it was asked."""
    generous = report(
        dispositions=[
            HunkDisposition(
                path=Path("src/other.py"),
                parent=PARENT,
                fate="kept",
                rationale="carried through unchanged",
            )
        ]
    )

    assert merge_problems(generous, [], []) == []


def test_a_clean_file_edited_without_declaring_it_is_the_rejection() -> None:
    """The canonical joint failure is fixed in a file that never conflicted.

    So the rule cannot be that changed files stay within conflicted files —
    it is that going outside is declared.
    """
    undeclared = report(
        dispositions=[
            HunkDisposition(
                path=Path("src/caller.py"),
                parent=PARENT,
                fate="rewritten",
                rationale="updated for the new signature",
            )
        ]
    )

    problems = merge_problems(undeclared, [Path("src/api.py")], [])

    assert any("src/caller.py" in problem for problem in problems)


def test_declaring_the_clean_file_edit_permits_it() -> None:
    declared = report(
        dispositions=[
            HunkDisposition(
                path=Path("src/caller.py"),
                parent=PARENT,
                fate="rewritten",
                rationale="updated for the new signature",
            )
        ],
        out_of_conflict_edits=[
            DeclaredEdit(
                path=Path("src/caller.py"),
                rationale="its call site still used the old arity",
            )
        ],
    )

    assert merge_problems(declared, [Path("src/api.py")], []) == []


def test_a_kept_hunk_inside_the_conflict_set_needs_no_declaration() -> None:
    kept = report(
        dispositions=[
            HunkDisposition(
                path=Path("src/api.py"),
                parent=PARENT,
                fate="kept",
                rationale="both sides agreed",
            )
        ]
    )

    assert merge_problems(kept, [Path("src/api.py")], []) == []


def test_the_containment_gate_names_the_paths_it_rejected_over() -> None:
    """A round that cannot read which path failed re-derives the same report."""
    reason = report_mismatch(["src/new.py"], ["src/stale.py"])

    assert "src/new.py" in reason
    assert "src/stale.py" in reason


def test_over_reporting_alone_passes_the_containment_gate() -> None:
    """Nothing changed undeclared is containment; equality cost 71 files."""
    assert report_mismatch([], []) == ""


class BranchLauncher(ProcessLauncher):
    """Report one checked-out branch and refuse anything else."""

    def __init__(self, branch: str) -> None:
        self.branch = branch

    def launch(self, request: LaunchRequest) -> ExitStatus:
        assert request.arguments == ["git", "branch", "--show-current"]
        return ExitStatus(code=0, stdout=f"{self.branch}\n", stderr="")


def test_a_fresh_run_mints_its_own_review_branch() -> None:
    branch = integration_branch(BranchLauncher("dev"), Path("."), "r1")

    assert branch == "resolve/r1/review"


def test_a_run_launched_on_a_review_branch_advances_that_branch() -> None:
    """A nested run is resolving that branch's own feedback.

    Minting a second review branch strands the work somewhere nobody asked
    for and leaves the human two branches to reconcile.
    """
    branch = integration_branch(
        BranchLauncher("resolve/earlier/review"), Path("."), "r2"
    )

    assert branch == "resolve/earlier/review"


def test_a_branch_merely_named_like_one_does_not_count() -> None:
    branch = integration_branch(BranchLauncher("resolve/r1/wip"), Path("."), "r3")

    assert branch == "resolve/r3/review"
