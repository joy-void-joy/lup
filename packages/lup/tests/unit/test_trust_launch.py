"""Trust on launch: nothing a checkout holds runs on the host until it was approved.

Every scenario drives :func:`lup.trust.launcher.trusted_launch` over a real
throwaway repository and a throwaway state directory, with the three things a
test must not do replaced: asking a person (an answerer recording into the
launcher's own relay), running the project's generation, and executing the
hand-off. What is pinned is the decision -- asked or not, about which files,
and whether anything was handed off at all.
"""

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath

import pytest
import sh
import typer
from rich.console import Console
from typer.testing import CliRunner

from lup.policy.relay import PersistentQuestion, QuestionRelay
from lup.policy.review import FilePreview
from lup.trust import launcher
from lup.trust.answer import Preview
from lup.trust.approved import APPROVED_TREE_ENV
from lup.trust.handoff import Handoff, Runner
from lup.trust.launcher import Asker, trusted_launch
from lup.trust.record import StateLocation, TrustState
from lup.trust.review import OPERATOR, TRUST_TOOL
from lup.trust.zone import LiveCheckout

PYPROJECT = """\
[project]
name = "studio-under-test"
version = "0.1.0"

[tool.lup.trust]
free = ["studio/", "tmp/"]
"""


def run_git(cwd: Path, *arguments: str) -> str:
    """Run one git command in a fixture repository and answer its output."""
    return str(sh.Command("git")("-C", str(cwd), *arguments, _tty_out=False))


def write(root: Path, name: str, content: str) -> Path:
    """Write one file of a fixture checkout, making its directories."""
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A committed checkout with a host zone and two declared free zones."""
    work = tmp_path / "work"
    run_git(tmp_path, "init", "-q", "-b", "main", str(work))
    write(work, "pyproject.toml", PYPROJECT)
    write(work, "uv.lock", "version = 1\n")
    write(work, "src/app.py", "print('approved')\n")
    write(work, "studio/tool.py", "print('free')\n")
    write(work, ".gitignore", "tmp/\nsync.json.local\n.lup/\n")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-q", "-m", "base")
    return work


def unchanged(_handoff: Handoff) -> bool:
    """A regeneration that finds every generated file current, as a settled tree does."""
    return True


class Launches:
    """Every launch one test makes, with what was asked, handed off and regenerated."""

    def __init__(self, state: Path, approve: bool = True) -> None:
        self.location = StateLocation(xdg_state_home=state)
        self.approve = approve
        self.asked: list[PersistentQuestion] = []
        self.shown: list[FilePreview] = []
        self.relays: list[QuestionRelay] = []
        self.handed: list[Handoff] = []
        self.regenerated: list[Handoff] = []
        self.regeneration: Runner = unchanged
        self.output = io.StringIO()

    def ask(
        self,
        question: PersistentQuestion,
        relay: QuestionRelay,
        preview: Preview,
        root: Path,
    ) -> PersistentQuestion:
        self.asked.append(question)
        self.shown.append(preview(question))
        self.relays.append(relay)
        relay.answer(question.id, OPERATOR, self.approve, "decided by the test")
        answered = relay.find(question.id)
        assert answered is not None
        return answered

    def execute(self, handoff: Handoff) -> None:
        self.handed.append(handoff)

    def regenerate(self, handoff: Handoff) -> bool:
        self.regenerated.append(handoff)
        return self.regeneration(handoff)

    def launch(self, start: Path) -> None:
        trusted_launch(
            start,
            ["harness", "claude"],
            self.ask,
            Console(file=self.output, width=200),
            # lup: ignore[os-environ] — the launcher is handed the environment it
            # runs in, and the test hands it this process's own
            dict(os.environ),
            self.execute,
            self.regenerate,
            self.location,
        )

    def files(self, index: int = -1) -> list[str]:
        """The paths one asked question showed, relative to wherever they were read."""
        return sorted(change.path.name for change in self.shown[index].files)


@pytest.fixture
def launches(tmp_path: Path) -> Launches:
    return Launches(tmp_path / "state")


def test_a_first_launch_asks_to_trust_the_checkout_as_it_stands(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)

    assert len(launches.asked) == 1
    shown = launches.shown[0]
    paths = sorted(
        change.path.relative_to(checkout).as_posix() for change in shown.files
    )
    assert paths == [".gitignore", "pyproject.toml", "src/app.py", "uv.lock"]
    assert all(change.before is None for change in shown.files)
    assert "complete host zone" in shown.notice
    assert "Nothing from this repository has been approved" in launches.asked[0].reason
    assert "Free zones declared: studio/, tmp/" in launches.asked[0].reason
    assert launches.asked[0].operation.tool == TRUST_TOOL
    assert len(launches.handed) == 1


def test_the_handoff_runs_an_export_of_exactly_the_approved_zone(
    checkout: Path, launches: Launches
) -> None:
    write(checkout, "src/untracked_module.py", "print('never reviewed')\n")
    launches.launch(checkout)

    handed = launches.handed[0]
    export = Path(handed.environment[APPROVED_TREE_ENV])
    assert handed.argv[:3] == ["uv", "run", "--directory"]
    assert handed.argv[3] == str(checkout.resolve())
    assert handed.argv[4:6] == ["--project", str(export)]
    assert handed.argv[6:] == ["--frozen", "lup-devtools", "harness", "claude"]
    assert (export / "src" / "app.py").read_text() == "print('approved')\n"
    assert not (export / "src" / "untracked_module.py").exists()
    assert not (export / "studio").exists()
    environment = Path(handed.environment["UV_PROJECT_ENVIRONMENT"])
    assert checkout not in environment.parents
    assert checkout not in Path(handed.environment["PYTHONPYCACHEPREFIX"]).parents


def test_an_unchanged_zone_launches_without_a_question(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    launches.launch(checkout)

    assert len(launches.asked) == 1
    assert len(launches.handed) == 2
    assert launches.handed[0].argv == launches.handed[1].argv


def test_an_edited_host_zone_file_is_asked_about_with_its_diff(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    write(checkout, "src/app.py", "print('changed by a session')\n")
    launches.launch(checkout)

    assert len(launches.asked) == 2
    [change] = launches.shown[1].files
    assert change.path == checkout.resolve() / "src" / "app.py"
    assert change.before == "print('approved')\n"
    assert change.after == "print('changed by a session')\n"
    assert "1 changed" in launches.asked[1].reason
    export = Path(launches.handed[-1].environment[APPROVED_TREE_ENV])
    assert (export / "src" / "app.py").read_text() == "print('changed by a session')\n"


def test_a_committed_change_later_checked_out_is_asked_about(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    run_git(checkout, "switch", "-q", "-c", "session-work")
    write(checkout, "src/app.py", "print('committed by a session')\n")
    run_git(checkout, "commit", "-q", "-am", "a session's commit")
    run_git(checkout, "switch", "-q", "main")
    launches.launch(checkout)
    assert len(launches.asked) == 1

    run_git(checkout, "merge", "-q", "--ff-only", "session-work")
    launches.launch(checkout)

    assert len(launches.asked) == 2
    assert launches.files(1) == ["app.py"]
    assert launches.shown[1].files[0].after == "print('committed by a session')\n"


def test_a_change_arriving_in_a_sibling_worktree_is_asked_about(
    checkout: Path, launches: Launches, tmp_path: Path
) -> None:
    launches.launch(checkout)
    sibling = tmp_path / "sibling"
    run_git(checkout, "worktree", "add", "-q", str(sibling), "-b", "sibling")
    launches.launch(sibling)
    assert len(launches.asked) == 1

    write(sibling, "src/app.py", "print('written in the sibling')\n")
    launches.launch(sibling)

    assert len(launches.asked) == 2
    assert launches.files(1) == ["app.py"]
    main = LiveCheckout.at(checkout, {"PATH": os.defpath})
    other = LiveCheckout.at(sibling, {"PATH": os.defpath})
    assert main.identity() == other.identity()


def test_a_free_zone_edit_launches_without_a_question(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    write(checkout, "studio/tool.py", "print('reworked freely')\n")
    write(checkout, "studio/new_kit.py", "print('added freely')\n")
    write(checkout, "tmp/scratch.txt", "notes\n")
    run_git(checkout, "add", "studio")
    launches.launch(checkout)

    assert len(launches.asked) == 1
    assert len(launches.handed) == 2


def test_a_changed_free_zone_declaration_is_asked_about_once(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    write(checkout, "pyproject.toml", PYPROJECT.replace('"tmp/"]', '"tmp/", "src/"]'))
    launches.launch(checkout)

    assert len(launches.asked) == 2
    assert "Free zones would change: + src/" in launches.asked[1].reason
    assert launches.files(1) == ["pyproject.toml"]

    launches.launch(checkout)
    write(checkout, "src/app.py", "print('now in a free zone')\n")
    launches.launch(checkout)

    assert len(launches.asked) == 2
    export = Path(launches.handed[-1].environment[APPROVED_TREE_ENV])
    assert not (export / "src").exists()


def test_missing_snapshot_objects_fall_back_to_the_complete_listing(
    checkout: Path, launches: Launches, tmp_path: Path
) -> None:
    launches.launch(checkout)
    identity = LiveCheckout.at(checkout, {"PATH": os.defpath}).identity()
    store = TrustState.of(identity, checkout, launches.location).store()
    approved = launches.asked[0].operation.payload["current"]
    assert isinstance(approved, str)
    store.location(approved).unlink()
    write(checkout, "src/app.py", "print('changed while the snapshot was lost')\n")
    launches.launch(checkout)

    assert len(launches.asked) == 2
    shown = launches.shown[1]
    assert "could not be read" in shown.notice
    assert f"object {approved} is missing" in shown.notice
    assert all(change.before is None for change in shown.files)
    assert "complete host zone" in launches.asked[1].reason


def test_a_corrupt_snapshot_object_falls_back_to_the_complete_listing(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    identity = LiveCheckout.at(checkout, {"PATH": os.defpath}).identity()
    store = TrustState.of(identity, checkout, launches.location).store()
    blob = store.write("blob", b"print('approved')\n")
    store.location(blob).chmod(0o644)
    store.location(blob).write_bytes(
        store.location(store.write("blob", b"x")).read_bytes()
    )
    write(checkout, "src/app.py", "print('changed after the store was damaged')\n")
    launches.launch(checkout)

    assert "does not hash to its own id" in launches.shown[1].notice
    assert all(change.before is None for change in launches.shown[1].files)


def test_a_rejected_launch_runs_nothing(checkout: Path, tmp_path: Path) -> None:
    rejecting = Launches(tmp_path / "state", approve=False)

    with pytest.raises(typer.Exit) as stopped:
        rejecting.launch(checkout)

    assert stopped.value.exit_code == 1
    assert rejecting.handed == []
    assert rejecting.regenerated == []
    identity = LiveCheckout.at(checkout, {"PATH": os.defpath}).identity()
    state = TrustState.of(identity, checkout, rejecting.location)
    assert not (state.root / "exports").exists()
    assert state.read().approvals == []
    assert "nothing from" in rejecting.output.getvalue()


def test_a_rewritten_machine_registry_is_asked_about(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    write(
        checkout,
        "sync.json.local",
        json.dumps({"projects": [{"name": "home", "path": "/", "mount": "rw"}]}),
    )
    launches.launch(checkout)

    assert len(launches.asked) == 2
    assert launches.files(1) == ["sync.json.local"]
    export = Path(launches.handed[-1].environment[APPROVED_TREE_ENV])
    assert (export / "sync.json.local").is_file()


def test_the_answer_is_never_read_from_the_checkouts_own_queue(
    checkout: Path, tmp_path: Path
) -> None:
    rejecting = Launches(tmp_path / "state", approve=False)
    with pytest.raises(typer.Exit):
        rejecting.launch(checkout)
    [question] = rejecting.asked
    forged = question.model_copy(update={"id": "forged", "state": "pending"})
    session_queue = QuestionRelay(checkout / ".lup" / "questions.jsonl")
    session_queue.record(forged)
    session_queue.answer("forged", OPERATOR, True, "a session answering itself")

    with pytest.raises(typer.Exit):
        rejecting.launch(checkout)

    assert rejecting.handed == []
    assert all(checkout not in relay.path.parents for relay in rejecting.relays)
    assert all((tmp_path / "state") in relay.path.parents for relay in rejecting.relays)


def test_an_interrupted_question_is_asked_again_rather_than_twice(
    checkout: Path, launches: Launches
) -> None:
    identity = LiveCheckout.at(checkout, {"PATH": os.defpath}).identity()
    relay = TrustState.of(identity, checkout, launches.location).relay()
    waiting: list[PersistentQuestion] = []

    def interrupted(
        question: PersistentQuestion,
        _relay: QuestionRelay,
        _preview: Preview,
        _root: Path,
    ) -> PersistentQuestion:
        waiting.append(question)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        trusted_launch(
            checkout,
            ["harness", "claude"],
            interrupted,
            Console(file=io.StringIO()),
            # lup: ignore[os-environ] — the launcher's own inherited environment
            dict(os.environ),
            launches.execute,
            launches.regenerate,
            launches.location,
        )
    launches.launch(checkout)

    assert [question.id for question in launches.asked] == [waiting[0].id]
    assert len(relay.questions()) == 1


def proof(files: dict[str, str]) -> str:
    """An ownership proof vouching for these generated files and their content."""
    return json.dumps(
        {
            "schema_version": 1,
            "generator_version": "0.0.0",
            "source_digest": "0" * 64,
            "target_requirements": [],
            "files": [
                {
                    "path": path,
                    "category": "generated",
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "semantic_id": f"test.{path}",
                    "executable": False,
                }
                for path, content in files.items()
            ],
        },
        indent=2,
    )


def test_regeneration_the_proof_vouches_for_is_not_asked_about_again(
    checkout: Path, launches: Launches
) -> None:
    write(checkout, "generated/settings.json", "{}\n")
    write(
        checkout,
        "generated/.lup-ownership.json",
        proof({"generated/settings.json": "{}\n"}),
    )
    run_git(checkout, "add", "-A")
    run_git(checkout, "commit", "-q", "-m", "generated tree")

    def regenerated(_handoff: Handoff) -> bool:
        write(checkout, "generated/settings.json", '{"new": true}\n')
        write(
            checkout,
            "generated/.lup-ownership.json",
            proof({"generated/settings.json": '{"new": true}\n'}),
        )
        return True

    launches.regeneration = regenerated
    launches.launch(checkout)
    launches.launch(checkout)

    assert len(launches.asked) == 1
    assert len(launches.regenerated) == 1
    assert launches.regenerated[0].argv[-3:] == ["harness", "generate", "all"]


def test_regeneration_leaving_unvouched_changes_is_asked_about_next_time(
    checkout: Path, launches: Launches
) -> None:
    write(checkout, "generated/.lup-ownership.json", proof({}))
    run_git(checkout, "add", "-A")
    run_git(checkout, "commit", "-q", "-m", "an empty proof")

    def raced(_handoff: Handoff) -> bool:
        write(checkout, "src/app.py", "print('written while generation ran')\n")
        return True

    launches.regeneration = raced
    launches.launch(checkout)
    launches.regeneration = unchanged
    launches.launch(checkout)

    assert len(launches.asked) == 2
    assert launches.files(1) == ["app.py"]


def test_free_zone_paths_never_reach_the_zone(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    identity = LiveCheckout.at(checkout, {"PATH": os.defpath}).identity()
    record = TrustState.of(identity, checkout, launches.location).read()

    assert record.free == [PurePosixPath("studio"), PurePosixPath("tmp")]


def test_the_command_hands_everything_after_the_runtime_to_the_launch(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[Path] = []
    commands: list[list[str]] = []

    def recorded(
        start: Path,
        command: list[str],
        ask: Asker,
        console: Console,
        # lup: ignore[dict-str-payload] — the environment map
        inherited: dict[str, str],
    ) -> None:
        starts.append(start)
        commands.append(command)

    monkeypatch.setattr(launcher, "trusted_launch", recorded)

    result = CliRunner().invoke(
        launcher.app,
        [
            "--root",
            str(checkout),
            "--no-open",
            "claude",
            "--network",
            "host",
            "--root",
            "x",
        ],
    )

    assert result.exit_code == 0, result.output
    assert starts == [checkout]
    assert commands == [["harness", "claude", "--network", "host", "--root", "x"]]


def test_a_host_shim_naming_a_mode_reaches_the_launch_intact(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``exec lup-launch "$runtime" --mode <name> "$@"`` — the mode is the project's word."""
    commands: list[list[str]] = []

    def recorded(
        start: Path,
        command: list[str],
        ask: Asker,
        console: Console,
        # lup: ignore[dict-str-payload] — the environment map
        inherited: dict[str, str],
    ) -> None:
        commands.append(command)

    monkeypatch.setattr(launcher, "trusted_launch", recorded)
    monkeypatch.chdir(checkout)

    result = CliRunner().invoke(
        launcher.app, ["codex", "--mode", "free", "--continue", "--memory", "12g"]
    )

    assert result.exit_code == 0, result.output
    assert commands == [
        ["harness", "codex", "--mode", "free", "--continue", "--memory", "12g"]
    ]


def test_status_says_what_this_machine_approved(
    checkout: Path, launches: Launches, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches.launch(checkout)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    result = CliRunner().invoke(launcher.app, ["--status", "--root", str(checkout)])

    assert result.exit_code == 0, result.output
    assert "free zones   studio/, tmp/" in result.output
    approved = launches.asked[0].operation.payload["current"]
    assert isinstance(approved, str)
    assert f"approved     {approved}" in result.output
