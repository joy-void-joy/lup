"""Trust on launch: the host zone, its fingerprint, the question, and the answer.

Every repository is a temporary git repository; the operator's answers, the
installer and the host service's client are stubbed, so nothing reaches uv, the
network or a real service, and the clock is the test kit's.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from rich.text import Text
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import resolve
from lup_dev.host.client import Detached, HostClient
from lup_dev.launch.trust import (
    Approval,
    Asker,
    Kept,
    Lock,
    ReleaseTool,
    Toolchain,
    Trust,
    Trusted,
    TrustError,
    Unchanged,
    UvToolchain,
    WorkspaceTool,
    engine,
)
from lup_dev.layout import Layout
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from conftest import Kit, Shell

    from lup_dev.launch.trust import Tool

LUP_LOCK = """\
version = 1
revision = 5
requires-python = ">=3.14"

[manifest]
members = [
    "lup",
    "lup-dev",
]

[[package]]
name = "lup"
version = "0.1.0"
source = { editable = "packages/lup" }
dependencies = [
    { name = "pydantic" },
]

[[package]]
name = "lup-dev"
version = "0.1.0"
source = { editable = "packages/lup-dev" }
dependencies = [
    { name = "lup" },
    { name = "pydantic" },
]

[[package]]
name = "pydantic"
version = "2.12.0"
source = { registry = "https://pypi.org/simple" }
"""
"""A lock resolving `lup-dev` from its own workspace, as lup's does."""

DECLARED = (
    '"""The declaration."""\n\nfrom lup_dev import Project\n\nproject = Project()\n'
)

LUP = {
    "pyproject.toml": '[tool.uv.workspace]\nmembers = ["packages/*"]\n',
    "uv.lock": LUP_LOCK,
    "lup_project.py": DECLARED,
    "packages/lup/pyproject.toml": "[project]\nname = 'lup'\n",
    "packages/lup/src/library/__init__.py": '"""The library."""\n',
    "packages/lup/tests/test_library.py": "def test_it():\n    pass\n",
    "packages/lup-dev/pyproject.toml": "[project]\nname = 'lup-dev'\n",
    "packages/lup-dev/src/environment/__init__.py": '"""The environment."""\n',
    "packages/lup-dev/checker/build.py": "print('built')\n",
    "packages/lup-dev/tests/test_environment.py": "def test_it():\n    pass\n",
    "docs/note.md": "# Note\n",
}
"""A repository laid out as lup's: two workspace packages and an engine."""

RELEASE_LOCK = """\
version = 1
revision = 5
requires-python = ">=3.14"

[[package]]
name = "audiobook"
version = "0.1.0"
source = {{ editable = "." }}

[package.dev-dependencies]
dev = [
    {{ name = "lup-dev" }},
]

[[package]]
name = "claude-agent-sdk"
version = "0.2.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "lup"
version = "{version}"
source = {{ registry = "https://pypi.org/simple" }}
dependencies = [
    {{ name = "pydantic" }},
]

[package.optional-dependencies]
claude = [
    {{ name = "claude-agent-sdk" }},
]

[[package]]
name = "lup-dev"
version = "{version}"
source = {{ registry = "https://pypi.org/simple" }}
dependencies = [
    {{ name = "lup", extra = ["claude"] }},
    {{ name = "pydantic" }},
]

[[package]]
name = "pydantic"
version = "2.12.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "rich"
version = "14.0.0"
source = {{ registry = "https://pypi.org/simple" }}
"""
"""A project's lock pinning `lup-dev`'s release, `{version}` its version."""

CONDITIONED = '''"""The declaration."""

from lup_dev import Core, Modules, Project

project = Project(
    modules=Modules.default().edit(Core(conditions="audiobook.conditions"))
)
'''

RELEASE = {
    "pyproject.toml": "[project]\nname = 'audiobook'\nversion = '0.1.0'\n",
    "uv.lock": RELEASE_LOCK.format(version="0.4.0"),
    "lup_project.py": CONDITIONED,
    "audiobook/__init__.py": '"""The audiobook."""\n',
    "audiobook/conditions.py": '"""Its conditions."""\n\nready = 1\n',
    "audiobook/narration.py": '"""Narration."""\n',
    "README.md": "# Audiobook\n",
}
"""A project pinning `lup-dev`'s release, with a conditions module."""

PYPI = "https://pypi.org/simple"


def written(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def repository(root: Path, files: dict[str, str], shell: Shell) -> Path:
    written(root, files)
    shell.git(root, "init", "-q", "-b", "dev")
    shell.git(root, "config", "user.email", "test@example.com")
    shell.git(root, "config", "user.name", "Test")
    shell.git(root, "config", "commit.gpgsign", "false")
    shell.commit(root, "first")
    return root


@pytest.fixture
def lup(tmp_path: Path, shell: Shell) -> Path:
    return repository(tmp_path / "lup", LUP, shell)


@pytest.fixture
def audiobook(tmp_path: Path, shell: Shell) -> Path:
    return repository(tmp_path / "audiobook", RELEASE, shell)


class Answering(Asker):
    """Answers each question as told, keeping what it was shown, its colour off."""

    def __init__(self, answers: list[bool]) -> None:
        self.answers = answers
        self.shown: list[str] = []
        self.asked: list[str] = []

    def show(self, text: str) -> None:
        self.shown.append(Text.from_ansi(text).plain)

    def ask(self, question: str) -> bool:
        self.asked.append(question)
        return self.answers.pop(0)


def yes() -> Answering:
    return Answering([True])


def no() -> Answering:
    return Answering([False])


def unasked() -> Answering:
    return Answering([])


class Recording(Toolchain):
    """Records each install, and names the copy as uv would, under `/tools`."""

    def __init__(self) -> None:
        self.installed: list[tuple[Tool, Path, str]] = []

    def install(self, tool: Tool, root: Path, commit: str) -> None:
        self.installed.append((tool, root, commit))

    def command(self, name: str) -> list[str]:
        return [f"/tools/{name}"]


class Service(HostClient):
    """The host service's client, recording stops and starts, with no service behind."""

    running: bool = True
    calls: list[str] = []

    def stop(self) -> bool:
        self.calls.append("stop")
        return self.running

    def ensure(self) -> None:
        assert isinstance(self.starter, Detached)
        self.calls.append(" ".join(self.starter.command))


def trusting(
    root: Path,
    kit: Kit,
    asker: Asker,
    *,
    inside: list[str] | None = None,
    running: bool = True,
) -> Trust:
    return Trust(
        root=root,
        layout=kit.layout,
        integration="dev",
        asker=asker,
        toolchain=Recording(),
        host=Service(
            layout=kit.layout.host,
            clock=kit.clock,
            starter=Detached(),
            running=running,
        ),
        clock=kit.clock,
        inside=list(inside or []),
    )


def recording(trust: Trust) -> Recording:
    assert isinstance(trust.toolchain, Recording)
    return trust.toolchain


def service(trust: Trust) -> Service:
    assert isinstance(trust.host, Service)
    return trust.host


def answering(trust: Trust) -> Answering:
    assert isinstance(trust.asker, Answering)
    return trust.asker


def approved(root: Path, kit: Kit, shell: Shell) -> Approval | None:
    common = shell.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return read_model(kit.layout.approved(Path(common)), Approval)


def changed(root: Path, files: dict[str, str], shell: Shell) -> str:
    written(root, files)
    shell.commit(root, "change")
    return shell.git(root, "rev-parse", "HEAD")


def test_lups_zone_is_its_declaration_and_its_workspaces_own_source(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    zone = trusting(lup, kit, unasked()).check().zone
    assert zone.commit == shell.git(lup, "rev-parse", "dev")
    assert zone.paths == [
        Path("lup_project.py"),
        Path("lup_project"),
        Path("pyproject.toml"),
        Path("uv.toml"),
        Path("uv.lock"),
        Path(".python-version"),
        Path("packages/lup-dev/pyproject.toml"),
        Path("packages/lup-dev/src"),
        Path("packages/lup/pyproject.toml"),
        Path("packages/lup/src"),
        Path("packages/lup-dev/checker"),
    ]
    assert zone.tool == WorkspaceTool(
        name="lup-dev",
        package=Path("packages/lup-dev"),
        members=[Path("packages/lup-dev"), Path("packages/lup")],
    )
    assert zone.unloaded == ""


def test_a_projects_zone_is_its_declaration_its_conditions_and_its_release(
    audiobook: Path, kit: Kit
) -> None:
    zone = trusting(audiobook, kit, unasked()).check().zone
    assert zone.paths == [
        Path("lup_project.py"),
        Path("lup_project"),
        Path("audiobook/conditions.py"),
        Path("audiobook/__init__.py"),
    ]
    assert zone.tool == ReleaseTool(
        name="lup-dev",
        version="0.4.0",
        registry=PYPI,
        pins={"lup": "0.4.0", "pydantic": "2.12.0", "claude-agent-sdk": "0.2.0"},
    )


def test_the_first_time_shows_the_zone_whole_then_installs_restarts_and_records(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    trust = trusting(lup, kit, yes())
    outcome = trust.ensure()
    head = shell.git(lup, "rev-parse", "dev")
    assert isinstance(outcome, Trusted)
    [shown] = answering(trust).shown
    assert shown.startswith(
        f"The host zone at {head}, whole, since nothing was approved yet: 8 files "
        "changed"
    )
    carried = [
        "lup_project.py",
        "pyproject.toml",
        "uv.lock",
        "packages/lup/pyproject.toml",
        "packages/lup/src/library/__init__.py",
        "packages/lup-dev/pyproject.toml",
        "packages/lup-dev/src/environment/__init__.py",
        "packages/lup-dev/checker/build.py",
    ]
    assert all(path in shown for path in carried)
    assert "docs/note.md" not in shown
    assert "tests/test_" not in shown
    assert answering(trust).asked == [
        (
            f"Approve the host zone at {head}, and install its `lup-dev` as the one "
            "the host runs?"
        )
    ]
    zone = trust.check().zone
    assert recording(trust).installed == [(zone.tool, lup, head)]
    assert service(trust).calls == ["stop", "/tools/lup-dev host"]
    assert outcome.restarted
    assert approved(lup, kit, shell) == outcome.approval
    assert outcome.approval.commit == head
    assert outcome.approval.paths == zone.paths
    assert outcome.approval.time == kit.clock.now()
    assert outcome.report() == (
        f"Approved: `lup-dev` from {head} is the one the host runs, and the host "
        "service restarted on it."
    )


def test_a_change_outside_the_zone_asks_nothing(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    head = changed(
        lup,
        {
            "docs/note.md": "# Note, changed\n",
            "packages/lup-dev/tests/test_environment.py": "def test_x():\n    pass\n",
        },
        shell,
    )
    trust = trusting(lup, kit, unasked())
    outcome = trust.ensure()
    assert outcome == Unchanged(commit=head, approval=first.approval)
    assert outcome.report() == (
        f"The host zone at {head} is the one you approved at "
        f"{first.approval.commit}: nothing to review."
    )
    assert answering(trust).shown == []
    assert recording(trust).installed == []
    assert service(trust).calls == []


def test_a_change_inside_the_zone_shows_its_diff_since_the_approved_commit(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    head = changed(
        lup,
        {"packages/lup-dev/src/environment/__init__.py": '"""Changed."""\n'},
        shell,
    )
    trust = trusting(lup, kit, yes())
    outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    [shown] = answering(trust).shown
    assert shown.startswith(
        f"The host zone at {head}, since {first.approval.commit}, the commit you "
        "approved last: 1 file changed, 1 insertion(+), 1 deletion(-)."
    )
    assert '+"""Changed."""' in shown
    assert '-"""The environment."""' in shown
    assert "packages/lup/src/library/__init__.py" not in shown
    assert outcome.approval.commit == head
    assert approved(lup, kit, shell) == outcome.approval


def test_a_branchs_own_change_isnt_the_tips_and_asks_nothing(
    lup: Path, kit: Kit, shell: Shell, tmp_path: Path
) -> None:
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    branch = tmp_path / "feat"
    shell.git(lup, "worktree", "add", "-q", "-b", "feat", str(branch))
    changed(branch, {"lup_project.py": DECLARED + "# the branch's own\n"}, shell)
    outcome = trusting(branch, kit, unasked()).ensure()
    assert outcome == Unchanged(commit=first.approval.commit, approval=first.approval)


def test_no_keeps_the_copy_approved_before(lup: Path, kit: Kit, shell: Shell) -> None:
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    head = changed(lup, {"lup_project.py": DECLARED + "# changed\n"}, shell)
    trust = trusting(lup, kit, no())
    outcome = trust.ensure()
    assert outcome == Kept(commit=head, approval=first.approval)
    assert outcome.report() == (
        "Declined: the tip isn't the code judging this session. The host keeps "
        f"running `lup-dev` from {first.approval.commit}, which you approved; the "
        f"host zone at {head} differs from it."
    )
    assert recording(trust).installed == []
    assert service(trust).calls == []
    assert approved(lup, kit, shell) == first.approval


def test_nothing_approved_and_no_refuses_and_records_nothing(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    trust = trusting(lup, kit, no())
    with pytest.raises(TrustError, match="none was approved before"):
        trust.ensure()
    assert recording(trust).installed == []
    assert service(trust).calls == []
    assert approved(lup, kit, shell) is None


def test_a_releases_change_is_said_by_its_versions(
    audiobook: Path, kit: Kit, shell: Shell
) -> None:
    first = trusting(audiobook, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    assert first.approval.tool == ReleaseTool(
        name="lup-dev",
        version="0.4.0",
        registry=PYPI,
        pins={"lup": "0.4.0", "pydantic": "2.12.0", "claude-agent-sdk": "0.2.0"},
    )
    changed(audiobook, {"uv.lock": RELEASE_LOCK.format(version="0.5.0")}, shell)
    trust = trusting(audiobook, kit, yes())
    trust.ensure()
    [shown] = answering(trust).shown
    lines = shown.splitlines()
    assert lines[1:3] == [
        f"`lup-dev` 0.4.0 from {PYPI} becomes 0.5.0 from {PYPI}:",
        "  lup 0.4.0 becomes 0.5.0",
    ]
    assert "no file of it changed" in lines[0]
    assert "uv.lock" not in shown


def test_the_first_release_says_what_it_needs(audiobook: Path, kit: Kit) -> None:
    trust = trusting(audiobook, kit, yes())
    trust.ensure()
    [shown] = answering(trust).shown
    assert shown.splitlines()[1:5] == [
        f"`lup-dev` 0.4.0 from {PYPI}, needing:",
        "  lup 0.4.0",
        "  pydantic 2.12.0",
        "  claude-agent-sdk 0.2.0",
    ]


def test_the_conditions_module_is_in_the_zone_and_a_module_beside_it_isnt(
    audiobook: Path, kit: Kit, shell: Shell
) -> None:
    trusting(audiobook, kit, yes()).ensure()
    changed(audiobook, {"audiobook/narration.py": '"""Changed."""\n'}, shell)
    assert isinstance(trusting(audiobook, kit, unasked()).ensure(), Unchanged)
    changed(audiobook, {"audiobook/conditions.py": '"""Changed."""\n'}, shell)
    trust = trusting(audiobook, kit, yes())
    assert isinstance(trust.ensure(), Trusted)
    [shown] = answering(trust).shown
    assert "audiobook/conditions.py" in shown
    assert "audiobook/narration.py" not in shown


def test_a_file_joining_the_zone_is_shown_whole(
    audiobook: Path, kit: Kit, shell: Shell
) -> None:
    trusting(audiobook, kit, yes()).ensure()
    ledger = CONDITIONED.replace("audiobook.conditions", "audiobook.ledger")
    changed(
        audiobook,
        {"lup_project.py": ledger, "audiobook/ledger.py": '"""The ledger."""\n'},
        shell,
    )
    trust = trusting(audiobook, kit, yes())
    trust.ensure()
    [shown] = answering(trust).shown
    lines = shown.splitlines()
    assert lines[1] == (
        "Joining the zone, shown whole: 1 file changed, 1 insertion(+)."
    )
    assert '+"""The ledger."""' in shown
    assert "audiobook/conditions.py" not in shown


def test_a_declaration_that_doesnt_load_is_said_and_still_asked(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    changed(lup, {"lup_project.py": "from lup_dev import Nowhere\n"}, shell)
    trust = trusting(lup, kit, yes())
    zone = trust.check().zone
    assert "can't be imported" in zone.unloaded
    trust.ensure()
    [shown] = answering(trust).shown
    assert shown.splitlines()[1].startswith(
        "The declaration doesn't load with the `lup-dev` running this, so the files "
        "its modules name aren't known or shown: "
    )


def test_inside_an_agents_session_nothing_is_asked(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    inside = trusting(lup, kit, yes(), inside=["first"])
    with pytest.raises(TrustError, match="inside a first session"):
        inside.ensure()
    assert answering(inside).shown == []
    assert approved(lup, kit, shell) is None
    trusting(lup, kit, yes()).ensure()
    again = trusting(lup, kit, unasked(), inside=["first"])
    assert isinstance(again.ensure(), Unchanged)


def test_with_no_host_service_running_the_next_launch_starts_one(
    lup: Path, kit: Kit
) -> None:
    trust = trusting(lup, kit, yes(), running=False)
    outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    assert not outcome.restarted
    assert service(trust).calls == ["stop"]
    assert outcome.report().endswith(
        "and the next launch starts the host service on it."
    )


def test_an_approved_commit_gone_from_the_repository_shows_everything(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    trust = trusting(lup, kit, yes())
    zone = trust.check().zone
    gone = Approval(
        commit="0" * 40,
        fingerprint="elsewhere",
        paths=zone.paths,
        tool=zone.tool,
        time=kit.clock.now(),
    )
    common = shell.git(lup, "rev-parse", "--path-format=absolute", "--git-common-dir")
    write_model(kit.layout.approved(Path(common)), gone)
    trust.ensure()
    [shown] = answering(trust).shown
    assert shown.startswith(
        f"The host zone at {zone.commit}, whole, since {'0' * 40}, the commit you "
        "approved last, isn't in the repository: 8 files changed"
    )


def test_a_lock_that_doesnt_pin_lup_dev_or_pins_it_from_elsewhere_refuses() -> None:
    with pytest.raises(TrustError, match="doesn't pin `lup-dev`"):
        Lock.parse("version = 1\n").tool("lup-dev")
    git = (
        "[[package]]\n"
        'name = "lup-dev"\n'
        'version = "0.4.0"\n'
        'source = { git = "https://github.com/joy-void-joy/lup?branch=dev#abc" }\n'
    )
    with pytest.raises(
        TrustError,
        match=r"resolves `lup-dev` from git https://github\.com/joy-void-joy/lup",
    ):
        Lock.parse(git).tool("lup-dev")


def test_a_package_lup_dev_needs_pinned_twice_refuses() -> None:
    forked = (
        "[[package]]\n"
        'name = "lup-dev"\n'
        'version = "0.4.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        'dependencies = [{ name = "numpy" }]\n'
        "[[package]]\n"
        'name = "numpy"\n'
        'version = "1.26.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        "[[package]]\n"
        'name = "numpy"\n'
        'version = "2.3.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    )
    with pytest.raises(TrustError, match=r"`numpy` at 1\.26\.0 and 2\.3\.0"):
        Lock.parse(forked).tool("lup-dev")


def test_a_repository_with_no_lock_refuses(
    tmp_path: Path, kit: Kit, shell: Shell
) -> None:
    root = repository(tmp_path / "bare", {"README.md": "# Bare\n"}, shell)
    with pytest.raises(TrustError, match=r"holds no `uv\.lock`"):
        trusting(root, kit, unasked()).check()


LUP_ROOT = Path(__file__).resolve().parents[3]
"""lup's own checkout, whose declaration gives the step building the engine."""


def test_the_engine_is_built_with_lups_own_gate_step() -> None:
    resolved = resolve(load(LUP_ROOT).project)
    step = engine(resolved)
    assert step.name == "engine"
    assert step.command == ["python", "packages/lup-dev/checker/build.py"]
    assert step.in_environment
    assert resolved.gate[0] == step


BUILDING = '''
from pathlib import Path

from lup_dev import Gate, Module, Modules, Project, Python, RoomNeeds, Runner, Step, Tools


class Marking(Runner):
    """Runs each tool with `LUP_RUNNER` set, so a build can tell it ran through it."""

    def command(self, tool: list[str]) -> list[str]:
        return ["env", "LUP_RUNNER=marking", *tool]

    def judging(self, tool: list[str]) -> list[str]:
        return self.command(tool)

    def environment(self) -> list[str]:
        return []

    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        return RoomNeeds()


class Building(Module):
    """Building the engine, as lup's own declaration does."""

    name = "building"

    gate: Gate = Gate.of(
        Step(
            name="engine",
            command={command!r},
            builds="bundle.js",
            in_environment={inside!r},
        ),
        before="rules",
    )


project = Project(
    modules=Modules.default().edit(Python(runner=Marking())).add(Building())
)
'''
"""A declaration building the engine, its tools run through a runner of its own."""

MARKED = """\
import os
from pathlib import Path
source = Path("packages/lup-dev/src/environment/__init__.py").read_text()
mark = os.environ.get("LUP_RUNNER", "as written")
Path(os.environ["LUP_MARK"]).write_text(f"{mark} in {Path.cwd()}: {source}")
"""
"""A build saying whether it ran through the runner, where, and from what source."""


def fake_uv(tmp_path: Path) -> tuple[Path, Path]:
    """Write a stand-in uv logging its arguments and the constraints it's given."""
    log = tmp_path / "uv.log"
    fake = tmp_path / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then echo /home/u/.local/bin; '
        "exit 0; fi\n"
        f'echo "$@" >> "{log}"\n'
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--output-file" ]; then echo "pydantic==2.12.0" > "$2"; fi\n'
        f'  if [ "$1" = "--constraints" ]; then cat "$2" >> "{log}"; fi\n'
        "  shift\n"
        "done\n"
    )
    fake.chmod(0o755)
    return fake, log


@pytest.mark.parametrize(
    ("inside", "built"), [(True, "marking"), (False, "as written")]
)
def test_uv_builds_and_installs_the_commits_copy_held_to_its_lock(
    lup: Path,
    tmp_path: Path,
    shell: Shell,
    monkeypatch: pytest.MonkeyPatch,
    *,
    inside: bool,
    built: str,
) -> None:
    command = [sys.executable, "packages/lup-dev/checker/build.py"]
    head = changed(
        lup,
        {
            "packages/lup-dev/checker/build.py": MARKED,
            "lup_project.py": BUILDING.format(command=command, inside=inside),
            # `git archive` would leave the source out of the copy.
            ".gitattributes": "packages/lup-dev/src/** export-ignore\n",
        },
        shell,
    )
    (lup / "packages/lup-dev/src/environment/__init__.py").write_text("uncommitted\n")
    mark = tmp_path / "mark"
    monkeypatch.setenv("LUP_MARK", str(mark))
    fake, log = fake_uv(tmp_path)
    tool = WorkspaceTool(
        name="lup-dev",
        package=Path("packages/lup-dev"),
        members=[Path("packages/lup-dev"), Path("packages/lup")],
    )
    UvToolchain(executable=str(fake)).install(tool, lup, head)
    how, _, source = mark.read_text().partition(": ")
    ran, _, where = how.partition(" in ")
    assert ran == built
    assert Path(where) != lup
    assert not Path(where).exists()
    assert source == '"""The environment."""\n'
    export, install, constraints = log.read_text().splitlines()
    assert export.startswith(
        "export --package lup-dev --no-dev --no-emit-workspace --no-hashes --frozen "
        "--format requirements-txt --quiet --output-file "
    )
    assert install.startswith("tool install --force --constraints ")
    assert install.endswith(f"{where}/packages/lup-dev")
    assert constraints == "pydantic==2.12.0"


def test_uv_installs_a_release_from_its_index_held_to_its_pins(
    tmp_path: Path,
) -> None:
    fake, log = fake_uv(tmp_path)
    release = ReleaseTool(
        name="lup-dev",
        version="0.4.0",
        registry=PYPI,
        pins={"lup": "0.4.0", "pydantic": "2.12.0"},
    )
    UvToolchain(executable=str(fake)).install(release, tmp_path, "unused")
    install, *constraints = log.read_text().splitlines()
    assert install.startswith("tool install --force --constraints ")
    assert install.endswith(f"--default-index {PYPI} lup-dev==0.4.0")
    assert constraints == ["lup==0.4.0", "pydantic==2.12.0"]


def test_uv_names_the_copy_it_installed(tmp_path: Path) -> None:
    fake, _ = fake_uv(tmp_path)
    assert UvToolchain(executable=str(fake)).command("lup-dev") == [
        "/home/u/.local/bin/lup-dev"
    ]


def test_a_declaration_building_no_engine_refuses(tmp_path: Path) -> None:
    written(tmp_path, {"lup_project.py": DECLARED})
    with pytest.raises(TrustError, match="no step building the engine"):
        UvToolchain().build(tmp_path)


def test_lup_dev_trust_says_so_in_one_line_when_nothing_changed(
    lup: Path,
    tmp_path: Path,
    shell: Shell,
    monkeypatch: pytest.MonkeyPatch,
    kit: Kit,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    state = Layout(state=tmp_path / "xdg" / "lup")
    first = trusting(lup, kit, yes()).model_copy(update={"layout": state})
    outcome = first.ensure()
    assert isinstance(outcome, Trusted)
    monkeypatch.chdir(lup)
    result = CliRunner().invoke(cli.app, ["trust"])
    assert result.exit_code == 0, result.output
    head = shell.git(lup, "rev-parse", "dev")
    assert result.output.splitlines() == [
        f"The host zone at {head} is the one you approved at {head}: nothing to review."
    ]


def test_lup_dev_trust_refuses_inside_a_session(
    lup: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.chdir(lup)
    result = CliRunner().invoke(cli.app, ["trust"])
    assert isinstance(result.exception, TrustError)
    common = lup / ".git"
    assert not Layout(state=tmp_path / "xdg" / "lup").approved(common).exists()


def test_lup_dev_install_is_gone() -> None:
    result = CliRunner().invoke(cli.app, ["install"])
    assert result.exit_code != 0
    assert "No such command 'install'" in result.output
