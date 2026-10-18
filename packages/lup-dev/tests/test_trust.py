"""Trust on launch: the host zone, its fingerprint, the question, and the answer.

Every repository is a temporary git repository; the operator's answers, the
installer and the host service's client are stubbed, so nothing reaches uv, the
network or a real service, and the clock is the test kit's.
"""

import asyncio
import os
import select
import socket
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from rich.text import Text
from typer.testing import CliRunner

from lup.types import Model
from lup_dev import cli
from lup_dev.approval import Approval, ReleaseTool, Tool, WorkspaceTool
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import resolve
from lup_dev.host.client import Detached, HostClient, Starter
from lup_dev.host.protocol import Stop
from lup_dev.host.service import HostService
from lup_dev.inbox import store
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.protocol import AskApproval
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import Approval as StoredApproval
from lup_dev.inbox.store import Decided, Inbox, InboxError, Superseded, Waiting
from lup_dev.launch.trust import (
    WHOLE,
    WHY,
    Approvals,
    Asker,
    Elsewhere,
    Given,
    InboxApprovals,
    Kept,
    Lock,
    Outcome,
    SupersededError,
    Terminal,
    Toolchain,
    Trust,
    Trusted,
    TrustError,
    Unchanged,
    UvToolchain,
    building,
)
from lup_dev.layout import JudgeLayout, Layout
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Generator

    from conftest import FakeClock, Kit, Shell

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


@pytest.fixture(autouse=True)
def uvs_own_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave uv's tool directories to uv, whatever the operator set them to."""
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.delenv("UV_TOOL_BIN_DIR", raising=False)


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


PATIENCE = 60
"""Seconds a test waits on another thread before failing, so a broken one ends
rather than hangs; nothing passes for having waited."""


def answered_elsewhere(elsewhere: Elsewhere) -> None:
    """Wait until an answer given elsewhere reaches this terminal."""
    while elsewhere.given() is None:
        readable, _, _ = select.select([elsewhere], [], [], PATIENCE)
        assert readable, "no answer came from elsewhere"


class Then(Model, arbitrary_types_allowed=True):
    """Something done while the terminal asks, then its answer given here."""

    act: Callable[[], object]
    answer: bool


class Meanwhile(Model, arbitrary_types_allowed=True):
    """Something done at another terminal while this one asks, after which this one waits for the answer given there."""

    act: Callable[[], object]


type Reply = bool | Then | Meanwhile


class Answering(Asker):
    """Answers whether to approve as told, and whether to show the whole diff; keeps what it printed, paged and asked, its colour off."""

    def __init__(self, answers: list[Reply], *, whole: Reply = False) -> None:
        self.answers = answers
        self.whole = whole
        self.said: list[str] = []
        self.shown: list[str] = []
        self.asked: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(Text.from_ansi(text).plain)

    def show(self, text: str) -> None:
        self.shown.append(Text.from_ansi(text).plain)

    def ask(self, question: str, elsewhere: Elsewhere) -> bool | None:
        self.asked.append(question)
        reply = self.whole if question == WHOLE else self.answers.pop(0)
        match reply:
            case Then(act=act, answer=answer):
                act()
                return answer
            case Meanwhile(act=act):
                act()
                answered_elsewhere(elsewhere)
                return None
            case bool():
                return reply


class Never(Elsewhere):
    """An approval nothing answers elsewhere."""

    def fileno(self) -> int:
        message = "a stub terminal waits on nothing"
        raise AssertionError(message)

    def given(self) -> bool | None:
        return None


class Here(Approvals):
    """The inbox, standing in: each approval item 1, answered at this terminal alone."""

    def __init__(self) -> None:
        self.asking: list[AskApproval] = []
        self.answers: list[bool] = []

    def asked(self, asking: AskApproval) -> int:
        self.asking.append(asking)
        return 1

    @contextmanager
    def waited(self, number: int) -> Generator[Elsewhere]:
        yield Never()

    def answer(self, number: int, *, approved: bool) -> Given:
        self.answers.append(approved)
        return Given(approved=approved, here=True)


def yes(*, whole: bool = False) -> Answering:
    return Answering([True], whole=whole)


def no() -> Answering:
    return Answering([False])


def unasked() -> Answering:
    return Answering([])


class Installed(Model):
    """One install: what, from where and which commit, into which copy, and whether the user's too."""

    tool: Tool
    root: Path
    commit: str
    into: JudgeLayout
    users: bool


class Recording(Toolchain):
    """Records each install, leaving the copy's command in place, and names the user's as uv would, under `/tools`."""

    def __init__(self) -> None:
        self.installed: list[Installed] = []

    def install(
        self, tool: Tool, root: Path, commit: str, copy: JudgeLayout, *, users: bool
    ) -> None:
        self.installed.append(
            Installed(tool=tool, root=root, commit=commit, into=copy, users=users)
        )
        command = copy.command(tool.name)
        command.parent.mkdir(parents=True, exist_ok=True)
        command.write_text(f"#!/bin/sh\n# {commit}\n")

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
    approvals: Approvals | None = None,
    layout: Layout | None = None,
) -> Trust:
    placed = layout or kit.layout
    return Trust(
        root=root,
        layout=placed,
        integration="dev",
        asker=asker,
        approvals=approvals or Here(),
        toolchain=Recording(),
        host=Service(
            layout=placed.host,
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


INBOXED = (
    "It's item 1 in your inbox too: `lup-dev inbox answer 1` answers it from any "
    "terminal."
)
"""What the launching terminal says after the summary, of the approval's item."""


def summarised(trust: Trust) -> list[str]:
    """The summary the terminal printed first, by its lines, without the line naming the approval's item."""
    said = answering(trust).said[0].splitlines()
    assert said[-2:] == ["", INBOXED]
    return said[:-2]


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
    assert zone.unread == []


def test_a_projects_zone_is_its_declaration_its_conditions_and_its_release(
    audiobook: Path, kit: Kit
) -> None:
    zone = trusting(audiobook, kit, unasked()).check().zone
    assert zone.paths == [
        Path("lup_project.py"),
        Path("lup_project"),
        Path("audiobook/__init__.py"),
        Path("audiobook/conditions.py"),
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
    lines = summarised(trust)
    said = "\n".join(lines)
    assert lines[:5] == [
        WHY,
        "",
        "Approved before: nothing, so the zone is shown whole.",
        f"The tip: {head}.",
        "",
    ]
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
    counted = [line.split("|")[0].strip() for line in lines[5:-1]]
    assert sorted(counted) == sorted(f"{path} (new)" for path in carried)
    assert lines[-1].startswith(" 8 files changed")
    assert "docs/note.md" not in said
    assert "tests/test_" not in said
    assert answering(trust).asked == [
        WHOLE,
        (
            f"Approve the host zone at {head}, and install its `lup-dev` as the one "
            "the host runs?"
        ),
    ]
    assert answering(trust).shown == []
    zone = trust.check().zone
    common = Path(shell.git(lup, "rev-parse", "--absolute-git-dir"))
    assert isinstance(trust.approvals, Here)
    [asking] = trust.approvals.asking
    assert Text.from_ansi(asking.summary).plain == said
    assert asking.question == answering(trust).asked[-1]
    assert asking.repository == common
    assert asking.fingerprint == trust.check().fingerprint
    assert asking.worktree == lup
    assert "+++ b/lup_project.py" in Text.from_ansi(asking.diff).plain
    assert trust.approvals.answers == [True]
    assert recording(trust).installed == [
        Installed(
            tool=zone.tool,
            root=lup,
            commit=head,
            into=kit.layout.judge(common),
            users=True,
        )
    ]
    assert kit.layout.judge(common).home.is_relative_to(kit.layout.data)
    assert service(trust).calls == ["stop", "/tools/lup-dev host"]
    assert outcome.restarted
    assert approved(lup, kit, shell) == outcome.approval
    assert outcome.approval.commit == head
    assert outcome.approval.paths == zone.paths
    assert outcome.approval.time == kit.clock.now()
    assert outcome.report() == (
        f"Approved: `lup-dev` from {head} judges this repository's sessions, and is "
        "the `lup-dev` you run; the host service restarted on it."
    )


def test_a_projects_release_is_its_own_copy_alone_and_restarts_nothing(
    audiobook: Path, kit: Kit, shell: Shell
) -> None:
    trust = trusting(audiobook, kit, yes())
    outcome = trust.ensure()
    head = shell.git(audiobook, "rev-parse", "dev")
    assert isinstance(outcome, Trusted)
    [install] = recording(trust).installed
    assert install.commit == head
    assert not install.users
    assert service(trust).calls == []
    assert not outcome.restarted
    assert outcome.report() == (
        f"Approved: `lup-dev` from {head} judges this repository's sessions, from "
        "their next hook."
    )


def test_two_repositories_keep_their_own_copies(
    lup: Path, audiobook: Path, kit: Kit
) -> None:
    ours = trusting(lup, kit, yes())
    theirs = trusting(audiobook, kit, yes())
    ours.ensure()
    theirs.ensure()
    [mine] = recording(ours).installed
    [other] = recording(theirs).installed
    assert mine.into != other.into
    assert mine.into.command("lup-dev").is_file()
    assert other.into.command("lup-dev").is_file()


def test_a_missing_copy_is_installed_again_from_the_approved_zone(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    common = Path(shell.git(lup, "rev-parse", "--absolute-git-dir"))
    copy = kit.layout.judge(common)
    copy.command("lup-dev").unlink()
    head = changed(lup, {"docs/note.md": "# Note, changed\n"}, shell)
    trust = trusting(lup, kit, unasked(), inside=["first"])
    outcome = trust.ensure()
    assert outcome == Unchanged(commit=head, approval=first.approval, again=True)
    assert recording(trust).installed == [
        Installed(
            tool=first.approval.tool, root=lup, commit=head, into=copy, users=False
        )
    ]
    assert service(trust).calls == []
    assert outcome.report().endswith(
        f"This repository's copy of `lup-dev` from {first.approval.commit} was "
        "missing, and is installed again."
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
    assert answering(trust).said == []
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
    trust = trusting(lup, kit, yes(whole=True))
    outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    assert summarised(trust)[2:] == [
        f"Approved before: {first.approval.commit}.",
        f"The tip: {head}.",
        "",
        " packages/lup-dev/src/environment/__init__.py | 2 +-",
        " 1 file changed, 1 insertion(+), 1 deletion(-)",
    ]
    [shown] = answering(trust).shown
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


def test_no_installs_the_copy_approved_before_where_its_missing(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    copy = kit.layout.judge(Path(shell.git(lup, "rev-parse", "--absolute-git-dir")))
    copy.command("lup-dev").unlink()
    head = changed(lup, {"lup_project.py": DECLARED + "# changed\n"}, shell)
    trust = trusting(lup, kit, no())
    outcome = trust.ensure()
    assert outcome == Kept(commit=head, approval=first.approval, again=True)
    assert recording(trust).installed == [
        Installed(
            tool=first.approval.tool,
            root=lup,
            commit=first.approval.commit,
            into=copy,
            users=False,
        )
    ]
    assert service(trust).calls == []


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


# Approving from the inbox, with nobody waiting


def test_a_zone_proposed_puts_its_approval_in_the_inbox_and_asks_nothing_here(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    trust = trusting(lup, kit, unasked())
    number = trust.proposed()
    assert number == 1
    assert isinstance(trust.approvals, Here)
    [asking] = trust.approvals.asking
    assert asking.fingerprint == trust.check().fingerprint
    assert answering(trust).asked == []
    assert recording(trust).installed == []
    assert approved(lup, kit, shell) is None


def test_a_zone_approved_already_proposes_nothing(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    trusting(lup, kit, yes()).ensure()
    trust = trusting(lup, kit, unasked())
    assert trust.proposed() is None
    assert isinstance(trust.approvals, Here)
    assert trust.approvals.asking == []


def test_an_answer_given_in_the_inbox_installs_and_records_once(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    proposing = trusting(lup, kit, unasked())
    proposing.proposed()
    fingerprint = proposing.check().fingerprint
    trust = trusting(lup, kit, unasked())

    outcome = trust.settle(fingerprint, Given(approved=True, here=True))
    again = trusting(lup, kit, unasked()).settle(
        fingerprint, Given(approved=True, here=False)
    )

    head = shell.git(lup, "rev-parse", "dev")
    assert isinstance(outcome, Trusted)
    assert outcome.approval.commit == head
    assert len(recording(trust).installed) == 1
    assert service(trust).calls == ["stop", "/tools/lup-dev host"]
    assert approved(lup, kit, shell) == outcome.approval
    assert isinstance(again, Unchanged)
    assert answering(trust).asked == []


def test_an_answer_about_a_tip_that_moved_since_installs_nothing(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    proposing = trusting(lup, kit, unasked())
    proposing.proposed()
    fingerprint = proposing.check().fingerprint
    changed(lup, {"lup_project.py": DECLARED + "# changed since\n"}, shell)
    trust = trusting(lup, kit, unasked())

    outcome = trust.settle(fingerprint, Given(approved=True, here=True))

    assert outcome is None
    assert recording(trust).installed == []
    assert approved(lup, kit, shell) is None


LAYER = '''"""The person's own layer: a made-up neighbour."""

from pathlib import Path

from lup_dev import Module, Modules, Project, Repositories, Repository


class Mine(Module):
    """The repositories beside the project, as this person has them."""

    name = "mine"

    repositories: Repositories = Repositories.of(
        Repository(name="atlas", path=Path("atlas.git"), about="a made-up neighbour")
    )


project = Project(modules=Modules().add(Mine()))
'''
"""The person's own layer, naming a made-up repository."""


def layered(root: Path, text: str | None) -> None:
    """Write the person's own layer at `root`, or remove it where `text` is none; git ignores it, as a project's `.gitignore` says."""
    layer = root / "lup_project.local.py"
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("/lup_project.local.py\n")
    if text is None:
        layer.unlink()
    else:
        layer.write_text(text)


def test_the_person_s_layer_is_approved_by_its_content_shown_first_whole(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    layered(lup, LAYER)
    trust = trusting(lup, kit, yes())
    outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    assert outcome.approval.local == LAYER
    summary = summarised(trust)
    heading = summary.index(
        "Your own layer, which git doesn't hold, changed since approved:"
    )
    assert summary[heading + 1 :][:4] == [
        "diff --git worktree/lup_project.local.py worktree/lup_project.local.py",
        "new file mode 100644",
        f"index 0000000..{shell.git(lup, 'hash-object', 'lup_project.local.py')[:7]}",
        "--- /dev/null",
    ]
    assert '+        Repository(name="atlas", path=Path("atlas.git"), ' in "\n".join(
        summary
    )
    assert approved(lup, kit, shell) == outcome.approval


def test_an_unchanged_layer_asks_nothing(lup: Path, kit: Kit, shell: Shell) -> None:
    layered(lup, LAYER)
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    trust = trusting(lup, kit, unasked())
    assert trust.ensure() == Unchanged(
        commit=first.approval.commit, approval=first.approval
    )
    assert answering(trust).said == []


def test_a_changed_layer_shows_its_diff_in_the_summary_and_asks(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    layered(lup, LAYER)
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    edited = LAYER.replace('"atlas.git"', '"elsewhere/atlas.git"')
    layered(lup, edited)
    trust = trusting(lup, kit, yes(whole=True))
    outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    summary = summarised(trust)
    assert summary[2:6] == [
        f"Approved before: {first.approval.commit}.",
        f"The tip: {first.approval.commit}.",
        "",
        "No file of the zone changed.",
    ]
    assert summary[6:10] == [
        "Your own layer, which git doesn't hold, changed since approved:",
        "diff --git approved/lup_project.local.py worktree/lup_project.local.py",
        summary[8],
        "--- approved/lup_project.local.py",
    ]
    said = "\n".join(summary)
    assert '-        Repository(name="atlas", path=Path("atlas.git"), ' in said
    assert (
        '+        Repository(name="atlas", path=Path("elsewhere/atlas.git"), ' in said
    )
    [shown] = answering(trust).shown
    assert 'path=Path("elsewhere/atlas.git")' in shown
    assert outcome.approval.local == edited
    assert approved(lup, kit, shell) == outcome.approval
    assert recording(trust).installed == []
    assert service(trust).calls == []
    assert outcome.report() == (
        "Approved: your own layer, which judges this repository's sessions from "
        f"their next hook, beside `lup-dev` from {first.approval.commit} as before."
    )


def test_a_layer_declined_keeps_the_copy_approved_before(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    layered(lup, LAYER)
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    layered(lup, LAYER + "\nprint('edited in a room')\n")
    outcome = trusting(lup, kit, no()).ensure()
    assert outcome == Kept(commit=first.approval.commit, approval=first.approval)
    assert approved(lup, kit, shell) == first.approval
    assert first.approval.local == LAYER


def test_a_layer_removed_is_shown_and_asked(lup: Path, kit: Kit, shell: Shell) -> None:
    layered(lup, LAYER)
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    layered(lup, None)
    trust = trusting(lup, kit, yes())
    outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    said = "\n".join(summarised(trust))
    assert "deleted file mode 100644" in said
    assert "+++ /dev/null" in said
    assert outcome.approval.local is None


def test_the_layer_is_the_main_worktree_s_whichever_worktree_trust_runs_from(
    lup: Path, kit: Kit, shell: Shell, tmp_path: Path
) -> None:
    layered(lup, LAYER)
    first = trusting(lup, kit, yes()).ensure()
    assert isinstance(first, Trusted)
    linked = tmp_path / "linked"
    shell.git(lup, "worktree", "add", "-q", "-b", "elsewhere", str(linked))
    trust = trusting(linked, kit, unasked())
    assert trust.check().zone.local == LAYER
    assert trust.ensure() == Unchanged(
        commit=first.approval.commit, approval=first.approval
    )


def test_what_the_layer_imports_of_the_commit_joins_the_zone(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    changed(lup, {"neighbours.py": '"""Made-up neighbours."""\n'}, shell)
    trust = trusting(lup, kit, unasked())
    assert Path("neighbours.py") not in trust.check().zone.paths
    layered(lup, f"import neighbours\n{LAYER}")
    zone = trust.check().zone
    assert Path("neighbours.py") in zone.paths
    assert Path("lup_project.local.py") not in zone.paths
    assert zone.local == f"import neighbours\n{LAYER}"


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
    lines = summarised(trust)
    said = "\n".join(lines)
    assert lines[5:] == [
        "No file of the zone changed.",
        f"`lup-dev` 0.4.0 from {PYPI} becomes 0.5.0 from {PYPI}:",
        "  lup 0.4.0 becomes 0.5.0",
    ]
    assert "uv.lock" not in said
    # With no file changed there's no diff to offer.
    assert WHOLE not in answering(trust).asked


def test_the_first_release_says_what_it_needs(audiobook: Path, kit: Kit) -> None:
    trust = trusting(audiobook, kit, yes())
    trust.ensure()
    lines = summarised(trust)
    assert lines[5:9] == [
        " audiobook/__init__.py (new)   | 1 +",
        " audiobook/conditions.py (new) | 3 +++",
        " lup_project.py (new)          | 7 +++++++",
        " 3 files changed, 11 insertions(+)",
    ]
    assert lines[9:] == [
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
    said = "\n".join(summarised(trust))
    assert "audiobook/conditions.py" in said
    assert "audiobook/narration.py" not in said


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
    trust = trusting(audiobook, kit, yes(whole=True))
    trust.ensure()
    assert summarised(trust)[5:] == [
        " lup_project.py | 2 +-",
        " 1 file changed, 1 insertion(+), 1 deletion(-)",
        "Joining the zone, shown whole:",
        " audiobook/ledger.py (new) | 1 +",
        " 1 file changed, 1 insertion(+)",
        f"`lup-dev` 0.4.0 from {PYPI}, as before, needing what it did.",
    ]
    [shown] = answering(trust).shown
    assert '+"""The ledger."""' in shown
    assert "audiobook/conditions.py" not in shown


def test_a_declaration_that_doesnt_parse_is_said_and_still_asked(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    changed(lup, {"lup_project.py": "from lup_dev import (\n"}, shell)
    trust = trusting(lup, kit, yes())
    zone = trust.check().zone
    [said] = zone.unread
    assert said.startswith("`lup_project.py` doesn't parse (")
    trust.ensure()
    assert summarised(trust)[-2:] == [
        "Not followed, so the zone may miss a file the declaration runs:",
        f"  {said}",
    ]


STUDIO = {
    **RELEASE,
    "lup_project.py": (
        '"""The declaration."""\n\n'
        "from audiobook.modules import Studio\n"
        "from lup_dev import Modules, Project\n\n"
        "project = Project(modules=Modules.default().add(Studio()))\n"
    ),
    "audiobook/modules/__init__.py": (
        '"""The project\'s modules."""\n\nfrom .studio import Studio\n'
    ),
    "audiobook/modules/studio.py": (
        '"""The studio."""\n\n'
        "from lup_dev import Module\n\n"
        "from audiobook import ledger\n\n\n"
        "class Studio(Module):\n"
        '    name = "studio"\n'
        '    conditions = "audiobook.conditions"\n'
    ),
    "audiobook/ledger.py": '"""The ledger."""\n\nfrom . import narration\n',
    "audiobook/conditions.py": (
        '"""Its conditions."""\n\nfrom audiobook import release\n\nready = 1\n'
    ),
    "audiobook/release.py": '"""Read by the conditions, never run on the host."""\n',
    "audiobook/cover.py": '"""Imported by nothing the declaration runs."""\n',
}
"""A project whose declaration imports its own modules, which import more and name
its conditions module."""


def test_the_zone_follows_the_declarations_imports_to_the_files_they_resolve_to(
    tmp_path: Path, kit: Kit, shell: Shell
) -> None:
    project = repository(tmp_path / "studio", STUDIO, shell)
    zone = trusting(project, kit, unasked()).check().zone
    assert zone.paths[:2] == [Path("lup_project.py"), Path("lup_project")]
    assert sorted(zone.paths[2:]) == [
        Path("audiobook/__init__.py"),
        Path("audiobook/conditions.py"),
        Path("audiobook/ledger.py"),
        Path("audiobook/modules/__init__.py"),
        Path("audiobook/modules/studio.py"),
        Path("audiobook/narration.py"),
    ]
    assert zone.unread == []


def test_a_package_declarations_relative_imports_are_followed(
    tmp_path: Path, kit: Kit, shell: Shell
) -> None:
    package = {
        **{name: text for name, text in RELEASE.items() if name != "lup_project.py"},
        "lup_project/__init__.py": (
            '"""The declaration."""\n\nfrom .studio import project\n'
        ),
        "lup_project/studio.py": (
            '"""Its module."""\n\n'
            "from lup_dev import Project\n\n"
            "from audiobook import narration\n\n"
            "project = Project()\n"
        ),
        "lup_project/beyond.py": "from ... import nowhere\n",
    }
    project = repository(tmp_path / "packaged", package, shell)
    zone = trusting(project, kit, unasked()).check().zone
    assert zone.paths == [
        Path("lup_project.py"),
        Path("lup_project"),
        Path("audiobook/__init__.py"),
        Path("audiobook/narration.py"),
    ]
    [said] = zone.unread
    assert said.startswith("`lup_project/beyond.py` imports `...`: ")


def test_reading_the_zone_runs_nothing_of_the_project(
    tmp_path: Path, kit: Kit, shell: Shell
) -> None:
    ran = tmp_path / "ran"
    running = {
        **RELEASE,
        "lup_project.py": (
            "import pathlib\n\n"
            "import audiobook.narration\n\n"
            f"pathlib.Path({str(ran)!r}).write_text('the declaration ran')\n"
        ),
        "audiobook/narration.py": (
            f"import pathlib\n\npathlib.Path({str(ran)!r}).write_text('it ran')\n"
        ),
    }
    project = repository(tmp_path / "running", running, shell)
    zone = trusting(project, kit, unasked()).check().zone
    assert Path("audiobook/narration.py") in zone.paths
    assert not ran.exists()


def test_inside_an_agents_session_nothing_is_asked(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    inside = trusting(lup, kit, yes(), inside=["first"])
    with pytest.raises(TrustError, match="inside a first session"):
        inside.ensure()
    assert answering(inside).said == []
    assert answering(inside).asked == []
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
        "the `lup-dev` you run; the next launch starts the host service on it."
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
    lines = summarised(trust)
    assert lines[2:4] == [
        (
            f"Approved before: {'0' * 40}, which the repository no longer holds, so "
            "the zone is shown whole."
        ),
        f"The tip: {zone.commit}.",
    ]
    assert lines[-1].startswith(" 8 files changed")


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


def test_the_engine_and_the_dashboards_page_are_built_with_lups_own_gate_steps() -> (
    None
):
    resolved = resolve(load(LUP_ROOT).project)
    engine, page = building(resolved)
    assert engine.name == "engine"
    assert engine.command == ["python", "packages/lup-dev/checker/build.py"]
    assert page.name == "dashboard"
    assert page.command == ["python", "packages/lup-dashboard/build.py"]
    assert engine.in_environment
    assert page.in_environment
    assert resolved.gate[:2] == [engine, page]


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
        f'echo "${{UV_TOOL_DIR:-uv}} ${{UV_TOOL_BIN_DIR:-uv}} $@" >> "{log}"\n'
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
    copy = JudgeLayout(home=tmp_path / "judges" / "lup")
    UvToolchain(executable=str(fake)).install(tool, lup, head, copy, users=True)
    how, _, source = mark.read_text().partition(": ")
    ran, _, where = how.partition(" in ")
    assert ran == built
    assert Path(where) != lup
    assert not Path(where).exists()
    assert source == '"""The environment."""\n'
    export, own, constraints, users, again = log.read_text().splitlines()
    assert export.startswith(
        "uv uv export --package lup-dev --no-dev --no-emit-workspace --no-hashes "
        "--frozen --format requirements-txt --quiet --output-file "
    )
    assert own.startswith(
        f"{copy.tools} {copy.bin} tool install --force --constraints "
    )
    assert own.endswith(f"{where}/packages/lup-dev")
    assert users.startswith("uv uv tool install --force --constraints ")
    assert users.endswith(f"{where}/packages/lup-dev")
    assert constraints == again == "pydantic==2.12.0"


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
    copy = JudgeLayout(home=tmp_path / "judges" / "audiobook")
    UvToolchain(executable=str(fake)).install(
        release, tmp_path, "unused", copy, users=False
    )
    install, *constraints = log.read_text().splitlines()
    assert install.startswith(
        f"{copy.tools} {copy.bin} tool install --force --constraints "
    )
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
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    state = Layout(state=tmp_path / "xdg" / "lup", data=tmp_path / "xdg-data" / "lup")
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


# The approval in lup's inbox: a host service serving in a thread of its own, on
# sockets under the test's directory, as `test_inbox.py` drives one; the
# launching terminal stubbed, `lup-dev inbox` run as another terminal would.


class Raised(Notices):
    """Records each desktop notice instead of raising it."""

    def __init__(self) -> None:
        self.raised: list[str] = []

    async def notify(self, summary: str, body: str) -> None:
        self.raised.append(f"{summary}\n{body}")


class Background:
    """A host service with lup's inbox, serving in a thread of its own."""

    def __init__(
        self, machine: Layout, clock: FakeClock, *, inboxed: bool = True
    ) -> None:
        known = cli.Adapters(known=cli.adapters())
        couriers = cli.Couriers(adapters=known)
        self.notices = Raised()
        self.said: list[str] = []
        self.delivery = Delivery(
            inbox=Inbox.opened(machine.inbox),
            courier=couriers,
            layout=machine.host,
            notices=self.notices,
            clock=clock,
            say=self.said.append,
        )
        self.service = HostService(
            layout=machine.host,
            answerer=known,
            courier=couriers,
            post=self.delivery,
            routes=inbox_routes(self.delivery) if inboxed else [],
            say=self.said.append,
        )
        self.bound = threading.Event()
        self.failure: BaseException | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        async def serve() -> None:
            async with self.service.serving() as serving:
                self.bound.set()
                await serving.stopped.wait()

        try:
            asyncio.run(serve())
        except BaseException as failure:
            self.failure = failure
        finally:
            self.bound.set()

    def start(self) -> Background:
        self.thread.start()
        self.bound.wait(PATIENCE)
        if self.failure is not None:
            raise self.failure
        return self

    def stop(self) -> None:
        if self.thread.is_alive():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(self.service.layout.control))
                connection.sendall(Stop().model_dump_json().encode())
                connection.shutdown(socket.SHUT_WR)
                connection.recv(4096)
        self.thread.join(PATIENCE)
        assert not self.thread.is_alive()


@contextmanager
def served(machine: Layout, clock: FakeClock) -> Generator[Background]:
    running = Background(machine, clock).start()
    try:
        yield running
    finally:
        running.stop()


class Unstarted(Starter):
    """Starts nothing: the service runs already."""

    def start(self, log: Path) -> None:
        message = f"a test's service runs already; nothing logs to {log}"
        raise AssertionError(message)


class Starting(Starter):
    """Starts the test's service in a thread, as a launch starts `lup-dev host`."""

    def __init__(self, machine: Layout, clock: FakeClock) -> None:
        self.machine = machine
        self.clock = clock
        self.started: list[Background] = []

    def start(self, log: Path) -> None:
        self.started.append(Background(self.machine, self.clock).start())


@pytest.fixture
def machine(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
) -> Layout:
    """lup's state and the host service where the command line places them, outside any session, with the fake clock."""
    xdg = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg / "run"))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg / "state"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setattr(cli, "SystemClock", lambda: clock)
    return Layout(
        state=xdg / "state" / "lup", runtime=xdg / "run" / "lup", data=xdg / "data"
    )


class Acted(Model):
    """One approval `lup-dev inbox answer` acted on, and the answer."""

    fingerprint: str
    approved: bool


@pytest.fixture(autouse=True)
def acting(monkeypatch: pytest.MonkeyPatch) -> list[Acted]:
    """`lup-dev inbox answer` acting on an approval's answer, recorded rather than run: `Trust.settle`, which it runs, is tested on its own."""
    acted: list[Acted] = []

    def recorded(approval: StoredApproval, given: Given) -> str | None:
        acted.append(Acted(fingerprint=approval.fingerprint, approved=given.approved))
        return None

    monkeypatch.setattr(cli, "acted_on", recorded)
    return acted


def inboxed(
    machine: Layout, clock: FakeClock, starter: Starter | None = None
) -> InboxApprovals:
    """lup's inbox through the test's host service, as a launch reaches it."""
    return InboxApprovals(
        host=HostClient(
            layout=machine.host, clock=clock, starter=starter or Unstarted()
        )
    )


def inbox(*arguments: str) -> str:
    """Run `lup-dev inbox` with `arguments`, as at another terminal, and return what it printed."""
    result = CliRunner().invoke(cli.app, ["inbox", *arguments])
    assert result.exit_code == 0, (result.output, result.exception)
    return result.output


def test_the_approval_is_an_inbox_item_the_launching_terminal_answers(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock
) -> None:
    with served(machine, clock) as running:
        trust = trusting(
            audiobook, kit, yes(), approvals=inboxed(machine, clock), layout=machine
        )
        outcome = trust.ensure()
        item = running.delivery.inbox.item(1)
        shown = inbox("show", "1")
        whole = inbox("show", "1", "--diff")
        late = inbox("answer", "1", "--decline")
        listed = inbox()
        raised = running.notices.raised
    assert isinstance(outcome, Trusted)
    assert isinstance(item.reason, store.Approval)
    assert item.state == Decided(at=clock.now(), approved=True)
    summary = "\n".join(summarised(trust))
    assert Text.from_ansi(item.reason.summary).plain == summary
    assert item.reason.text == answering(trust).asked[-1]
    assert item.worktree == audiobook
    assert shown.splitlines()[1:] == [
        *summary.splitlines(),
        "",
        item.reason.text,
        "The whole diff: `lup-dev inbox show 1 --diff`.",
    ]
    assert shown.startswith(f"Item 1, an approval from the operator in {audiobook}")
    assert "approved at" in shown.splitlines()[0]
    assert '+"""Its conditions."""' in whole
    assert (
        late == "Item 1 was approved already, elsewhere: your answer changes nothing.\n"
    )
    assert listed == "Nothing waits for you.\n"
    [notice] = raised
    assert notice.startswith(f"lup: an approval from the operator in {audiobook}")
    assert notice.endswith("lup-dev inbox show 1")


def test_lup_dev_inbox_answer_answers_it_and_the_terminal_stops_asking(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock, acting: list[Acted]
) -> None:
    elsewhere: list[str] = []
    with served(machine, clock):
        asker = Answering(
            [],
            whole=Meanwhile(
                act=lambda: elsewhere.append(inbox("answer", "1", "--approve"))
            ),
        )
        trust = trusting(
            audiobook, kit, asker, approvals=inboxed(machine, clock), layout=machine
        )
        outcome = trust.ensure()
    assert isinstance(outcome, Trusted)
    assert asker.asked == [WHOLE]
    assert asker.said[-1] == "Item 1 was approved elsewhere."
    assert elsewhere == ["Item 1 is approved: each launch waiting on it goes on.\n"]
    assert [each.commit for each in recording(trust).installed] == [
        outcome.approval.commit
    ]
    assert acting == [Acted(fingerprint=trust.check().fingerprint, approved=True)]


def test_declined_from_the_inbox_keeps_the_copy_approved_before(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock, shell: Shell
) -> None:
    with served(machine, clock):
        first = trusting(
            audiobook, kit, yes(), approvals=inboxed(machine, clock), layout=machine
        ).ensure()
        assert isinstance(first, Trusted)
        head = changed(
            audiobook, {"audiobook/conditions.py": '"""Changed."""\n'}, shell
        )
        asker = Answering([Meanwhile(act=lambda: inbox("answer", "2", "--decline"))])
        trust = trusting(
            audiobook, kit, asker, approvals=inboxed(machine, clock), layout=machine
        )
        outcome = trust.ensure()
    assert outcome == Kept(commit=head, approval=first.approval)
    assert asker.said[-1] == "Item 2 was declined elsewhere."
    assert recording(trust).installed == []


def test_declined_with_nothing_approved_before_launches_nothing(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock
) -> None:
    with served(machine, clock) as running:
        trust = trusting(
            audiobook,
            kit,
            Answering([Meanwhile(act=lambda: inbox("answer", "1", "--decline"))]),
            approvals=inboxed(machine, clock),
            layout=machine,
        )
        with pytest.raises(TrustError, match="you declined the host zone"):
            trust.ensure()
        item = running.delivery.inbox.item(1)
    assert item.state == Decided(at=clock.now(), approved=False)
    assert read_model(machine.approved(audiobook / ".git"), Approval) is None


def test_two_launches_wait_on_one_approval_and_one_installs(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock
) -> None:
    joined = threading.Event()
    second = trusting(
        audiobook,
        kit,
        Answering([Meanwhile(act=joined.set)]),
        approvals=inboxed(machine, clock),
        layout=machine,
    )
    first = trusting(
        audiobook,
        kit,
        Answering([Then(act=lambda: joined.wait(PATIENCE), answer=True)]),
        approvals=inboxed(machine, clock),
        layout=machine,
    )
    outcomes: list[Outcome] = []
    with served(machine, clock) as running:
        waiting = threading.Thread(target=lambda: outcomes.append(second.ensure()))
        waiting.start()
        outcomes.append(first.ensure())
        waiting.join(PATIENCE)
        items = list(running.delivery.inbox.items)
    assert not waiting.is_alive()
    assert items == [1]
    assert answering(second).said[-1] == "Item 1 was approved elsewhere."
    # Whichever takes the approval's lock first installs; the other reads it.
    [trusted] = [each for each in outcomes if isinstance(each, Trusted)]
    [unchanged] = [each for each in outcomes if isinstance(each, Unchanged)]
    assert unchanged == Unchanged(
        commit=trusted.approval.commit, approval=trusted.approval
    )
    installed = [*recording(first).installed, *recording(second).installed]
    assert [each.commit for each in installed] == [trusted.approval.commit]


def test_with_no_host_service_the_approval_starts_one(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock
) -> None:
    starting = Starting(machine, clock)
    trust = trusting(
        audiobook,
        kit,
        yes(),
        approvals=inboxed(machine, clock, starting),
        layout=machine,
    )
    try:
        outcome = trust.ensure()
    finally:
        for each in starting.started:
            each.stop()
    assert isinstance(outcome, Trusted)
    [started] = starting.started
    assert started.delivery.inbox.item(1).state == Decided(
        at=clock.now(), approved=True
    )


def test_a_wait_outlives_a_service_restart_and_hears_the_next_ones_answer(
    machine: Layout, clock: FakeClock, tmp_path: Path
) -> None:
    approvals = inboxed(machine, clock)
    asking = AskApproval(
        question="Approve?",
        summary="A summary.",
        diff="A diff.",
        repository=tmp_path / ".git",
        fingerprint="zone",
        worktree=tmp_path,
    )
    with served(machine, clock):
        number = approvals.asked(asking)
        waiting = approvals.waited(number)
        elsewhere = waiting.__enter__()
        assert elsewhere.given() is None
    try:
        with served(machine, clock):
            readable, _, _ = select.select([elsewhere], [], [], PATIENCE)
            assert readable
            assert elsewhere.given() is None
            assert approvals.asked(asking) == number
            assert inbox("answer", str(number), "--approve").startswith(
                f"Item {number} is approved"
            )
            answered_elsewhere(elsewhere)
            assert elsewhere.given() is True
    finally:
        waiting.__exit__(None, None, None)


def test_lup_dev_inbox_answer_asks_an_approval_as_the_launch_does(
    machine: Layout,
    clock: FakeClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acting: list[Acted],
) -> None:
    terminal = Answering([True], whole=True)
    monkeypatch.setattr(cli, "Terminal", lambda: terminal)
    asking = AskApproval(
        question="Approve the host zone?",
        summary="\x1b[32mA summary.\x1b[m",
        diff="+the whole diff\n",
        repository=tmp_path / ".git",
        fingerprint="zone",
        worktree=tmp_path,
    )
    with served(machine, clock) as running:
        number = inboxed(machine, clock).asked(asking)
        said = inbox("answer", str(number))
        item = running.delivery.inbox.item(number)
    assert said == f"Item {number} is approved: each launch waiting on it goes on.\n"
    assert item.state == Decided(at=clock.now(), approved=True)
    assert acting == [Acted(fingerprint="zone", approved=True)]
    [summary] = terminal.said
    assert summary.splitlines()[1:] == ["A summary."]
    assert terminal.shown == ["+the whole diff\n"]
    assert terminal.asked == [WHOLE, "Approve the host zone?"]


def approval_of(tmp_path: Path, fingerprint: str) -> AskApproval:
    """An approval of the repository at `tmp_path`, its zone at `fingerprint`."""
    return AskApproval(
        question=f"Approve the host zone {fingerprint}?",
        summary="A summary.",
        diff="",
        repository=tmp_path / ".git",
        fingerprint=fingerprint,
        worktree=tmp_path,
    )


def test_an_approval_of_a_newer_zone_supersedes_the_one_waiting(
    machine: Layout, clock: FakeClock, tmp_path: Path, acting: list[Acted]
) -> None:
    elsewhere = tmp_path / "elsewhere"
    with served(machine, clock) as running:
        approvals = inboxed(machine, clock)
        older = approvals.asked(approval_of(tmp_path, "older"))
        other = approvals.asked(approval_of(elsewhere, "theirs"))
        again = approvals.asked(approval_of(tmp_path, "older"))
        newer = approvals.asked(approval_of(tmp_path, "newer"))
        listed = inbox()
        replaced = running.delivery.inbox.item(older)
        late = CliRunner().invoke(cli.app, ["inbox", "answer", str(older), "--approve"])
    assert again == older
    assert replaced.state == Superseded(at=clock.now(), by=newer)
    assert isinstance(running.delivery.inbox.item(other).state, Waiting)
    assert f"{older:>4}  " not in listed
    assert f"{newer:>4}  " in listed
    assert (
        f"(`answer {newer}` shows its summary, offers its whole diff, and asks; "
        f"`show {newer} --diff` pages the diff alone)"
    ) in listed
    assert isinstance(late.exception, SupersededError)
    assert str(late.exception) == (
        f"Item {older} was superseded by item {newer}, an approval of the host zone "
        "at the integration branch's tip."
    )
    assert acting == []


class SupersededOnce(Here):
    """The inbox, standing in: the first answer finds its approval superseded."""

    def answer(self, number: int, *, approved: bool) -> Given:
        if not self.answers:
            self.answers.append(approved)
            message = f"Item {number} was superseded by item 2."
            raise SupersededError(message)
        return super().answer(number, approved=approved)


def test_a_launch_whose_approval_is_superseded_asks_about_the_tip_instead(
    lup: Path, kit: Kit, shell: Shell
) -> None:
    asker = Answering([True, True])
    trust = trusting(lup, kit, asker, approvals=SupersededOnce())

    outcome = trust.ensure()

    assert isinstance(outcome, Trusted)
    assert isinstance(trust.approvals, SupersededOnce)
    assert len(trust.approvals.asking) == 2
    assert (
        "Item 1 was superseded by item 2. The tip moved: asking about it instead."
        in (asker.said)
    )
    assert approved(lup, kit, shell) == outcome.approval


def test_answering_an_approval_is_refused_inside_an_agents_session(
    machine: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    result = CliRunner().invoke(cli.app, ["inbox", "answer", "1", "--approve"])
    assert isinstance(result.exception, InboxError)
    assert "inside a" in str(result.exception)


class Silent(Elsewhere):
    """An approval nothing answers elsewhere, on a socket never written."""

    def __init__(self) -> None:
        self.ours, self.theirs = socket.socketpair()

    def fileno(self) -> int:
        return self.ours.fileno()

    def given(self) -> bool | None:
        return None


class Arrived(Silent):
    """An approval answered elsewhere already: its socket readable, its answer yes."""

    def __init__(self) -> None:
        super().__init__()
        self.theirs.send(b"answered")

    def given(self) -> bool | None:
        return True


def test_the_terminal_reads_y_or_n_enter_saying_no_and_asks_again_otherwise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    read, write = os.pipe()
    os.write(write, b"maybe\ny\n\nno\n")
    terminal = Terminal(stdin=read)
    elsewhere = Silent()
    assert terminal.ask("Approve?", elsewhere) is True
    assert terminal.ask("Approve?", elsewhere) is False
    assert terminal.ask("Approve?", elsewhere) is False
    printed = capsys.readouterr().out
    assert printed == (
        "Approve? [y/N]: Answer y or n. Approve? [y/N]: "
        "Approve? [y/N]: Approve? [y/N]: "
    )


def test_the_terminal_stops_asking_where_the_approval_was_answered_elsewhere(
    capsys: pytest.CaptureFixture[str],
) -> None:
    read, _ = os.pipe()
    assert Terminal(stdin=read).ask("Approve?", Arrived()) is None
    assert capsys.readouterr().out == "Approve? [y/N]: \n"


def test_a_service_that_doesnt_know_approvals_is_said_with_what_to_do(
    audiobook: Path, kit: Kit, machine: Layout, clock: FakeClock
) -> None:
    older = Background(machine, clock, inboxed=False).start()
    try:
        trust = trusting(
            audiobook, kit, yes(), approvals=inboxed(machine, clock), layout=machine
        )
        with pytest.raises(TrustError) as refused:
            trust.ensure()
    finally:
        older.stop()
    said = str(refused.value)
    assert said.startswith(
        "the host service didn't take the approval into your inbox: no handler for "
        "`inbox-ask-approval`"
    )
    assert said.endswith("`lup-dev host stop`, then ask again")
    assert answering(trust).said == []
