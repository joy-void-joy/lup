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
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest
import sh
import typer
from rich.console import Console
from typer.testing import CliRunner

from lup.devtools.harness.contained import (
    host_only_directories,
    refuse_host_only_mounts,
)
from lup.policy.relay import PersistentQuestion, QuestionRelay
from lup.policy.review import FilePreview
from lup.sandbox.rail import AccessibleRoot, fleet_lease
from lup.trust import launcher
from lup.trust.answer import Preview
from lup.trust.approved import APPROVED_TREE_ENV
from lup.trust.handoff import Executor, Handoff, Runner
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
        self.holder: int | None = None
        self.said_before_asking: list[str] = []
        self.output = io.StringIO()

    def ask(
        self,
        question: PersistentQuestion,
        relay: QuestionRelay,
        preview: Preview,
        root: Path,
    ) -> PersistentQuestion:
        self.asked.append(question)
        self.said_before_asking.append(self.output.getvalue())
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

    def launch(
        self,
        start: Path,
        command: list[str] = ["harness", "claude"],
        named: str = "claude",
    ) -> None:
        trusted_launch(
            start,
            command,
            named,
            self.ask,
            Console(file=self.output, width=200),
            # lup: ignore[os-environ] — the launcher is handed the environment it
            # runs in, and the test hands it this process's own
            dict(os.environ),
            self.execute,
            self.regenerate,
            self.location,
            self.holder,
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
            "claude",
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


class Handed:
    """What the command line hands ``trusted_launch``, recorded instead of launched."""

    def __init__(self) -> None:
        self.starts: list[Path] = []
        self.commands: list[list[str]] = []
        self.named: list[str] = []
        self.handing: list[str] = []

    def __call__(
        self,
        start: Path,
        command: list[str],
        named: str,
        ask: Asker,
        console: Console,
        # lup: ignore[dict-str-payload] — the environment map
        inherited: dict[str, str],
        execute: Executor,
    ) -> None:
        self.starts.append(start)
        self.commands.append(command)
        self.named.append(named)
        self.handing.append(execute.__name__)


def test_the_command_hands_everything_after_the_runtime_to_the_launch(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed = Handed()
    monkeypatch.setattr(launcher, "trusted_launch", handed)

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
    assert handed.starts == [checkout]
    assert handed.commands == [
        ["harness", "claude", "--network", "host", "--root", "x"]
    ]
    assert handed.named == ["claude"]
    assert handed.handing == ["launch"]


def test_a_host_shim_naming_a_mode_reaches_the_launch_intact(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``exec lup-launch "$runtime" --mode <name> "$@"`` — the mode is the project's word."""
    handed = Handed()
    monkeypatch.setattr(launcher, "trusted_launch", handed)
    monkeypatch.chdir(checkout)

    result = CliRunner().invoke(
        launcher.app, ["codex", "--mode", "free", "--continue", "--memory", "12g"]
    )

    assert result.exit_code == 0, result.output
    assert handed.commands == [
        ["harness", "codex", "--mode", "free", "--continue", "--memory", "12g"]
    ]


def test_run_hands_a_devtools_command_over_rather_than_a_launch(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``lup-launch run setup gemini``: the command itself, named as the question says it."""
    handed = Handed()
    monkeypatch.setattr(launcher, "trusted_launch", handed)

    result = CliRunner().invoke(
        launcher.app, ["--root", str(checkout), "run", "setup", "gemini", "--help"]
    )

    assert result.exit_code == 0, result.output
    assert handed.commands == [["setup", "gemini", "--help"]]
    assert handed.named == ["lup-devtools setup gemini --help"]
    assert handed.handing == ["run"]


def test_run_without_a_command_runs_nothing(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed = Handed()
    monkeypatch.setattr(launcher, "trusted_launch", handed)

    result = CliRunner().invoke(launcher.app, ["--root", str(checkout), "run"])

    assert result.exit_code == 2
    assert handed.commands == []


def test_a_run_is_reviewed_and_handed_off_from_the_approved_export(
    checkout: Path, launches: Launches
) -> None:
    """The same question, the same recorded approval, the command from the export."""
    launches.launch(checkout, ["setup", "gemini"], "lup-devtools setup gemini")

    [question] = launches.asked
    assert question.reason.startswith(
        f"Launching lup-devtools setup gemini from {checkout.resolve()}"
    )
    assert question.operation.payload["runtime"] == "lup-devtools setup gemini"
    [handed] = launches.handed
    export = Path(handed.environment[APPROVED_TREE_ENV])
    assert handed.argv[4:6] == ["--project", str(export)]
    assert handed.argv[6:] == ["--frozen", "lup-devtools", "setup", "gemini"]
    assert (export / "src" / "app.py").read_text() == "print('approved')\n"

    launches.launch(checkout)

    assert len(launches.asked) == 1


def test_a_rejected_run_runs_nothing(checkout: Path, tmp_path: Path) -> None:
    rejecting = Launches(tmp_path / "state", approve=False)

    with pytest.raises(typer.Exit) as stopped:
        rejecting.launch(checkout, ["setup", "gemini"], "lup-devtools setup gemini")

    assert stopped.value.exit_code == 1
    assert rejecting.handed == []
    assert rejecting.regenerated == []
    identity = LiveCheckout.at(checkout, {"PATH": os.defpath}).identity()
    state = TrustState.of(identity, checkout, rejecting.location)
    assert state.read().approvals == []


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


def test_a_registration_carrying_the_launchers_state_is_refused(
    checkout: Path, launches: Launches, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session that could write the record could approve its own next launch."""
    launches.launch(checkout)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    whole_state = fleet_lease(checkout, [AccessibleRoot(path=tmp_path / "state")])
    own = fleet_lease(checkout)

    refuse_host_only_mounts(own, host_only_directories())
    with pytest.raises(typer.BadParameter, match="the launcher's approvals"):
        refuse_host_only_mounts(whole_state, host_only_directories())


def ended() -> int:
    """The id of a process that has already ended, as a finished launch's is."""
    finished = sh.Command("true")(_bg=True, _return_cmd=True)
    finished.wait()
    return finished.pid


@pytest.fixture
def running() -> Iterator[sh.RunningCommand]:
    """A process still running, as a live session's launch is."""
    sleeper = sh.Command("sleep")("60", _bg=True, _bg_exc=False, _return_cmd=True)
    yield sleeper
    try:
        sleeper.kill()
    except ProcessLookupError:
        return


def exported_from(handoff: Handoff) -> Path:
    """The export one hand-off runs from."""
    return Path(handoff.environment[APPROVED_TREE_ENV])


def compiled_for(handoff: Handoff) -> Path:
    """Where the bytecode compiled from a hand-off's export is kept, made to exist."""
    export = exported_from(handoff)
    compiled = Path(handoff.environment["PYTHONPYCACHEPREFIX"]) / export.relative_to(
        export.anchor
    )
    compiled.mkdir(parents=True)
    (compiled / "app.cpython-314.pyc").write_bytes(b"bytecode")
    return compiled


def test_a_new_export_removes_the_one_its_worktree_ran_before(
    checkout: Path, launches: Launches
) -> None:
    """With the bytecode compiled from it; the worktree's environment stays."""
    launches.holder = ended()
    launches.launch(checkout)
    before = exported_from(launches.handed[0])
    compiled = compiled_for(launches.handed[0])
    environment = Path(launches.handed[0].environment["UV_PROJECT_ENVIRONMENT"])
    environment.mkdir(parents=True)
    write(checkout, "src/app.py", "print('changed')\n")

    launches.launch(checkout)

    after = exported_from(launches.handed[1])
    assert after != before
    assert (after / "src" / "app.py").read_text() == "print('changed')\n"
    assert not before.exists()
    assert not compiled.exists()
    assert environment.is_dir()
    assert sorted(path.name for path in before.parent.iterdir()) == [after.name]


def test_an_export_a_running_launch_uses_is_kept_until_it_ends(
    checkout: Path, launches: Launches, running: sh.RunningCommand
) -> None:
    launches.holder = running.pid
    launches.launch(checkout)
    before = exported_from(launches.handed[0])
    write(checkout, "src/app.py", "print('changed')\n")
    launches.holder = ended()

    launches.launch(checkout)
    assert before.is_dir()

    running.kill()
    with pytest.raises(sh.SignalException):
        running.wait()
    launches.launch(checkout)
    assert not before.exists()
    assert exported_from(launches.handed[2]).is_dir()


def test_each_worktree_keeps_the_export_it_launched_last(
    checkout: Path, launches: Launches, tmp_path: Path
) -> None:
    launches.holder = ended()
    launches.launch(checkout)
    sibling = tmp_path / "sibling"
    run_git(checkout, "worktree", "add", "-q", str(sibling), "-b", "sibling")
    write(sibling, "src/app.py", "print('the sibling's own')\n")

    launches.launch(sibling)

    main, other = (exported_from(handed) for handed in launches.handed)
    assert main != other
    assert main.is_dir() and other.is_dir()


def test_the_export_generation_ran_from_is_let_go(
    checkout: Path, launches: Launches
) -> None:
    """Generation leases the export it runs from only while it runs."""
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
    launches.holder = ended()
    launches.launch(checkout)

    [ran_from] = launches.regenerated
    launched = exported_from(launches.handed[0])
    assert exported_from(ran_from) != launched
    assert not exported_from(ran_from).exists()
    assert sorted(path.name for path in launched.parent.iterdir()) == [launched.name]


def test_a_first_launch_says_why_it_asks_before_it_asks(
    checkout: Path, launches: Launches
) -> None:
    """Once, in the words a reader needs: whose code, first run, where, and what then."""
    launches.launch(checkout, ["setup", "gemini"], "lup-devtools setup gemini")

    [said] = launches.said_before_asking
    assert said.splitlines() == [
        "studio-under-test's host code has not been approved on this machine yet "
        "(first run, 4 files):",
        "  .gitignore      1 file",
        "  pyproject.toml  1 file",
        "  src/            1 file",
        "  uv.lock         1 file",
        "Free zones declared: studio/, tmp/.",
        "lup-devtools setup gemini runs after you approve.",
    ]


def test_a_change_is_said_by_top_directory_before_it_is_asked_about(
    checkout: Path, launches: Launches
) -> None:
    launches.launch(checkout)
    write(checkout, "src/app.py", "print('changed')\n")
    write(checkout, "src/extra.py", "print('added')\n")
    write(checkout, "docs/guide.md", "# guide\n")
    run_git(checkout, "add", "-A")
    (checkout / "uv.lock").unlink()
    already = len(launches.output.getvalue())

    launches.launch(checkout)

    said = launches.said_before_asking[1][already:]
    assert said.splitlines() == [
        "studio-under-test's host code changed since your last approval on this "
        "machine (4 files):",
        "  docs/    1 added",
        "  src/     1 changed, 1 added",
        "  uv.lock  1 removed",
        "claude runs after you approve.",
    ]


def test_an_export_a_process_still_runs_from_is_kept(
    checkout: Path, launches: Launches
) -> None:
    """As a companion a launch started runs from it, outliving the launch with no lease."""
    launches.holder = ended()
    launches.launch(checkout)
    before = exported_from(launches.handed[0])
    companion = sh.Command("sleep")(
        "60",
        _bg=True,
        _bg_exc=False,
        _return_cmd=True,
        _env={"PATH": os.defpath, APPROVED_TREE_ENV: str(before)},
    )
    write(checkout, "src/app.py", "print('changed')\n")
    try:
        launches.launch(checkout)
        assert before.is_dir()
    finally:
        companion.kill()
        with pytest.raises(sh.SignalException):
            companion.wait()

    launches.launch(checkout)

    assert not before.exists()
