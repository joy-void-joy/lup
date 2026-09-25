"""Selecting a runtime is one assignment, and both runtimes answer it.

The autonomy roster is read out of the type rather than restated, so a degree
added to :data:`~lup.providers.selection.SessionAutonomy` fails here until every
runtime has spelled it — which is the whole point of the request being a
declaration each runtime renders.
"""

import json
import tomllib
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import get_args

import pytest
import tomlkit
from pydantic import BaseModel, ValidationError

from lup.providers.claude.config_home import (
    CLAUDE_HOME_DIR,
    CLAUDE_HOME_DOCUMENT,
    CLAUDE_OAUTH_URL_ENV,
    load_document,
    save_document,
)
from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.claude.runtime import ClaudeSessionConfig
from lup.providers.claude.selection import (
    CLAUDE_AUTONOMY,
    CLAUDE_CONTAINMENT,
    CLAUDE_RUNTIME,
    claude_config,
)
from lup.providers.codex.home import CodexWorktreeHomeStore
from lup.providers.codex.login import CODEX_HOME, CODEX_LOGIN
from lup.providers.codex.runtime import CODEX_PROGRAM, CodexSessionConfig
from lup.providers.codex.selection import (
    CODEX_AUTONOMY,
    CODEX_CONTAINMENT,
    CODEX_SANDBOX_WIDTH,
    CODEX_RUNTIME,
    codex_config,
    codex_mcp_server,
)
from lup.policy.hooks import LupHooksConfig
from lup.tools.mcp import create_mcp_server
from lup.sessions.client import Client
from lup.providers.selection import (
    Runtime,
    SessionAutonomy,
    SessionContainment,
    SessionRequest,
)
from lup.sessions.composition import submission_gate_resolver
from lup.sessions.events import SubmissionDecision

AUTONOMY_DEGREES = get_args(SessionAutonomy.__value__)
CONTAINMENT_WALLS = get_args(SessionContainment.__value__)


@pytest.fixture(autouse=True)
def empty_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Measure the runtimes, not the account this suite was launched as.

    A session's home is selected from the environment it runs with, which
    begins as this process's own — so a test leaving that alone derives
    under whichever account launched the suite, and reads its document.
    Every test here starts from an empty user directory with no runtime's
    home named, and names one where that is its subject.

    Codex's worktree store fixes the operator's account home when it is
    imported — :data:`~lup.providers.codex.home.DEFAULT_ACCOUNT_HOME` says
    why — so it is bound to the empty directory here, which stands for the
    operator's, rather than following ``HOME``.
    """
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    for name in (CLAUDE_CONFIG_DIR, CLAUDE_OAUTH_URL_ENV, CODEX_HOME):
        monkeypatch.delenv(name, raising=False)
    account = user / CODEX_LOGIN.ambient_home.name
    store = partial(CodexWorktreeHomeStore, account)
    monkeypatch.setattr("lup.providers.codex.home.CodexWorktreeHomeStore", store)
    return user


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_runtime_carries_its_own_login(runtime: Runtime) -> None:
    assert runtime.name
    assert runtime.login.config_home_env
    assert runtime.login.credentials_file


@pytest.mark.parametrize("degree", AUTONOMY_DEGREES)
def test_every_runtime_spells_every_degree_of_autonomy(degree: str) -> None:
    assert degree in CLAUDE_AUTONOMY
    assert degree in CODEX_AUTONOMY


def test_claude_renders_the_whole_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rendered: list[ClaudeSessionConfig] = []

    def record(config: ClaudeSessionConfig) -> Client:
        rendered.append(config)
        return Client(lambda resume=None: None)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr("lup.providers.claude.selection.create_claude", record)
    CLAUDE_RUNTIME.session_factory(
        SessionRequest(
            model="a-model",
            instructions="be brief",
            cwd=tmp_path,
            autonomy="unattended",
            allowed_tools=["Read"],
            native_tools=["Read"],
            max_turns=3,
            environment={"KEEP": "1"},
            hooks=LupHooksConfig(),
        )
    )

    config = rendered[0]
    assert config.model == "a-model"
    assert config.system_prompt == "be brief"
    assert config.cwd == tmp_path
    assert config.permission_mode == "bypassPermissions"
    assert config.allowed_tools == ["Read"]
    assert config.max_turns == 3
    assert config.environment["KEEP"] == "1"
    assert CLAUDE_RUNTIME.login.config_home_env in config.environment
    assert config.hooks is not None


def test_codex_renders_what_it_can_spell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rendered: list[CodexSessionConfig] = []

    def record(config: CodexSessionConfig) -> Client:
        rendered.append(config)
        return Client(lambda resume=None: None)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr("lup.providers.codex.selection.create_codex", record)
    CODEX_RUNTIME.session_factory(
        SessionRequest(
            model="a-model",
            instructions="be brief",
            cwd=tmp_path,
            autonomy="accept_edits",
            native_tools=["Bash"],
            tool_servers={"group": {"command": "uv", "args": ["run", "tools"]}},
        )
    )

    config = rendered[0]
    assert config.model == "a-model"
    assert config.developer_instructions == "be brief"
    assert config.sandbox == "workspace-write"
    assert config.writable_roots == [tmp_path]
    assert config.mcp_servers["group"].command == "uv"
    assert config.mcp_servers["group"].args == ["run", "tools"]


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"allowed_tools": ["Read"]},
    ],
    ids=["allowed_tools"],
)
def test_codex_refuses_what_it_cannot_govern(
    request_kwargs: dict[str, object], tmp_path: Path
) -> None:
    """A field Codex has no words for is an error, never a silent drop."""
    with pytest.raises(ValueError, match="no session-level"):
        CODEX_RUNTIME.session_factory(
            SessionRequest(cwd=tmp_path, **request_kwargs)  # pyright: ignore[reportArgumentType]
        )


def test_codex_will_not_infer_the_directory_it_sandboxes_against() -> None:
    with pytest.raises(ValueError, match="cwd"):
        CODEX_RUNTIME.session_factory(SessionRequest(model="a-model"))


def test_codex_rejects_a_tool_group_it_cannot_launch() -> None:
    with pytest.raises(ValueError, match="subprocess"):
        codex_mcp_server("group", {"type": "sse", "url": "https://example.test"})


def test_codex_will_not_relaunch_a_hosted_tool_group_as_a_subprocess() -> None:
    """The refusal that stops a session's own state being answered around.

    A hosted server reads the process hosting it — the context variables
    scoping the session it answers inside, its clients, its caches. Relaunched
    as a subprocess it would not fail: it would answer every call from
    defaults, confidently, and nothing downstream could tell the difference.
    So the refusal has to say why, or the transport change it looks like is
    the repair somebody reaches for.
    """
    with pytest.raises(ValueError, match="answer from defaults"):
        codex_mcp_server("group", create_mcp_server("group"))


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_workspace_home_is_named_in_the_runtime_that_opens_it(
    runtime: Runtime, tmp_path: Path
) -> None:
    """Where a workspace's sessions write is a per-runtime fact, so the whole
    selection has to carry it. An application deriving one runtime's home for
    every session points the other at a directory its CLI never reads, while
    dropping the home its profile selected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    environment = runtime.workspace_environment(
        {runtime.login.config_home_env: str(tmp_path / "account")}, workspace
    )

    assert runtime.login.config_home_env in environment


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_request_costs_nothing_to_state_and_is_contained_when_opened(
    runtime: Runtime, tmp_path: Path
) -> None:
    """Stating a request touches no filesystem, so building one cannot fail on
    a home it has no reason to need yet. The home appears when the runtime
    opens the session, which is the only moment both the workspace and the
    runtime are known."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = SessionRequest(cwd=workspace)

    assert runtime.login.config_home_env not in request.environment
    assert runtime.login.config_home_env in runtime.homed(request).environment


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_request_naming_no_workspace_has_no_home_to_be_given(
    runtime: Runtime,
) -> None:
    request = SessionRequest()

    assert runtime.homed(request) == request


def claude_account(home: Path, document: Path, name: str) -> None:
    """Give one Claude account a login in its home, and a document where Claude reads it."""
    home.mkdir(parents=True, exist_ok=True)
    login = json.dumps({"account": name})
    CLAUDE_LOGIN.credentials_path(home).write_text(login, encoding="utf-8")
    save_document(document, {"account": name})


def codex_account(home: Path, name: str) -> None:
    """Give one Codex account a login, and the settings it keeps beside it."""
    home.mkdir(parents=True, exist_ok=True)
    login = json.dumps({"account": name})
    CODEX_LOGIN.credentials_path(home).write_text(login, encoding="utf-8")
    settings = tomlkit.dumps({"account": name})
    (home / "config.toml").write_text(settings, encoding="utf-8")


def test_claude_homes_a_session_under_the_account_it_was_launched_as(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The process names the account and the request names nothing, as one
    built with defaults does. The session inherits the process's variable,
    so the home it is routed at is derived from that account — its login
    linked in, its document carried — and the request gains that routing
    alone, never a copy of the process's variables."""
    launched = tmp_path / "launched"
    claude_account(launched, launched / CLAUDE_HOME_DOCUMENT, "launched")
    monkeypatch.setenv(CLAUDE_CONFIG_DIR, str(launched))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    homed = CLAUDE_RUNTIME.homed(SessionRequest(cwd=workspace))
    home = Path(homed.environment[CLAUDE_CONFIG_DIR])

    assert list(homed.environment) == [CLAUDE_CONFIG_DIR]
    login = CLAUDE_LOGIN.credentials_path(home).resolve()
    assert login == CLAUDE_LOGIN.credentials_path(launched).resolve()
    assert load_document(home / CLAUDE_HOME_DOCUMENT) == {"account": "launched"}


def test_claude_prefers_the_account_a_request_names_to_the_one_it_was_launched_as(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A request's variables are layered over the process's in the session,
    and so in the selection: the account the request names wins."""
    launched = tmp_path / "launched"
    requested = tmp_path / "requested"
    for account in (launched, requested):
        claude_account(account, account / CLAUDE_HOME_DOCUMENT, account.name)
    monkeypatch.setenv(CLAUDE_CONFIG_DIR, str(launched))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = SessionRequest(
        cwd=workspace, environment={CLAUDE_CONFIG_DIR: str(requested)}
    )

    home = Path(CLAUDE_RUNTIME.homed(request).environment[CLAUDE_CONFIG_DIR])

    login = CLAUDE_LOGIN.credentials_path(home).resolve()
    assert login == CLAUDE_LOGIN.credentials_path(requested).resolve()
    assert load_document(home / CLAUDE_HOME_DOCUMENT) == {"account": "requested"}


def test_claude_falls_back_to_its_default_account_when_nothing_names_one(
    empty_user_home: Path, tmp_path: Path
) -> None:
    """Neither names a home, so Claude's own default decides: ``.claude`` in
    the user's home directory, with its document beside that, not inside."""
    default = empty_user_home / CLAUDE_HOME_DIR
    claude_account(default, empty_user_home / CLAUDE_HOME_DOCUMENT, "default")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    homed = CLAUDE_RUNTIME.homed(SessionRequest(cwd=workspace))
    home = Path(homed.environment[CLAUDE_CONFIG_DIR])

    login = CLAUDE_LOGIN.credentials_path(home).resolve()
    assert login == CLAUDE_LOGIN.credentials_path(default).resolve()
    assert load_document(home / CLAUDE_HOME_DOCUMENT) == {"account": "default"}


def test_claude_derives_from_the_operator_s_account_whatever_home_a_request_names(
    empty_user_home: Path, tmp_path: Path
) -> None:
    """A request's own ``HOME`` is for the tools its session runs, and the
    session still authenticates as the operator: with no home named, the
    default it derives from is the operator's, though Claude Code left to
    choose would join the request's. The request keeps its ``HOME``."""
    operator = empty_user_home / CLAUDE_HOME_DIR
    claude_account(operator, empty_user_home / CLAUDE_HOME_DOCUMENT, "operator")
    elsewhere = tmp_path / "elsewhere"
    claude_account(
        elsewhere / CLAUDE_HOME_DIR, elsewhere / CLAUDE_HOME_DOCUMENT, "elsewhere"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = SessionRequest(cwd=workspace, environment={"HOME": str(elsewhere)})

    homed = CLAUDE_RUNTIME.homed(request)
    home = Path(homed.environment[CLAUDE_CONFIG_DIR])

    assert homed.environment["HOME"] == str(elsewhere)
    login = CLAUDE_LOGIN.credentials_path(home).resolve()
    assert login == CLAUDE_LOGIN.credentials_path(operator).resolve()
    assert load_document(home / CLAUDE_HOME_DOCUMENT) == {"account": "operator"}


def test_codex_opens_a_session_in_the_home_it_was_launched_under(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The process names the home and the request names nothing. Codex
    honours a named home as it stands, so the session is routed at that home
    itself — its login and its settings, left as they were — and no worktree
    copy of the account is prepared in its place."""
    launched = tmp_path / "launched"
    codex_account(launched, "launched")
    monkeypatch.setenv(CODEX_HOME, str(launched))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    homed = CODEX_RUNTIME.homed(SessionRequest(cwd=workspace))

    assert homed.environment == {CODEX_HOME: str(launched)}
    settings = (launched / "config.toml").read_text(encoding="utf-8")
    assert settings == tomlkit.dumps({"account": "launched"})
    assert not CodexWorktreeHomeStore().home_for(workspace).exists()


def test_codex_prefers_the_home_a_request_names_to_the_one_it_was_launched_under(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A request's variables are layered over the process's in the session,
    and so in the selection: the home the request names wins."""
    launched = tmp_path / "launched"
    requested = tmp_path / "requested"
    for account in (launched, requested):
        codex_account(account, account.name)
    monkeypatch.setenv(CODEX_HOME, str(launched))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = SessionRequest(cwd=workspace, environment={CODEX_HOME: str(requested)})

    assert CODEX_RUNTIME.homed(request).environment == {CODEX_HOME: str(requested)}


def test_codex_falls_back_to_the_worktree_home_when_nothing_names_one(
    empty_user_home: Path, tmp_path: Path
) -> None:
    """Neither names a home, so the checkout's own is prepared, seeded from
    the account Codex keeps by default: its login copied in, its settings
    carried over."""
    codex_account(empty_user_home / CODEX_LOGIN.ambient_home.name, "default")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    homed = CODEX_RUNTIME.homed(SessionRequest(cwd=workspace))
    home = Path(homed.environment[CODEX_HOME])

    assert home == CodexWorktreeHomeStore().home_for(workspace)
    login = CODEX_LOGIN.credentials_path(home).read_text(encoding="utf-8")
    assert login == json.dumps({"account": "default"})
    settings = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert settings["account"] == "default"


def test_codex_seeds_from_the_operator_s_account_whatever_home_a_request_names(
    empty_user_home: Path, tmp_path: Path
) -> None:
    """The same for Codex: the worktree home copies in the operator's login,
    though Codex left to choose would read ``.codex`` in the request's
    ``HOME``. The request keeps its ``HOME``."""
    codex_account(empty_user_home / CODEX_LOGIN.ambient_home.name, "operator")
    elsewhere = tmp_path / "elsewhere"
    codex_account(elsewhere / CODEX_LOGIN.ambient_home.name, "elsewhere")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = SessionRequest(cwd=workspace, environment={"HOME": str(elsewhere)})

    homed = CODEX_RUNTIME.homed(request)
    home = Path(homed.environment[CODEX_HOME])

    assert homed.environment["HOME"] == str(elsewhere)
    assert home == CodexWorktreeHomeStore().home_for(workspace)
    login = CODEX_LOGIN.credentials_path(home).read_text(encoding="utf-8")
    assert login == json.dumps({"account": "operator"})


class GatedOutput(BaseModel):
    """The shape one gated turn submits."""

    verdict: str


CONFIG_RENDERERS: list[
    Callable[[SessionRequest], ClaudeSessionConfig | CodexSessionConfig]
] = [
    claude_config,
    codex_config,
]


@pytest.mark.parametrize("render", CONFIG_RENDERERS)
def test_a_submission_gate_reaches_every_runtime(
    render: Callable[[SessionRequest], ClaudeSessionConfig | CodexSessionConfig],
    tmp_path: Path,
) -> None:
    """A gate stated once is rendered by both, or it gates whichever it names.

    Every backend spells the submission tool its own way, so a caller that
    reached an adapter's configuration to gate a session would name a provider
    to say something true of both — and the arm running under the other
    provider would submit ungated. Stating it on the request is what makes
    the gate a property of the session rather than of the spelling.
    """

    async def gate(_output: GatedOutput) -> SubmissionDecision:
        return SubmissionDecision(accepted=False, message="review first")

    resolver = submission_gate_resolver(GatedOutput, gate)
    config = render(SessionRequest(cwd=tmp_path, submission_gate=resolver))

    assert config.submission_gate_resolver is resolver


@pytest.mark.parametrize("render", CONFIG_RENDERERS)
def test_an_ungated_request_renders_no_gate(
    render: Callable[[SessionRequest], ClaudeSessionConfig | CodexSessionConfig],
    tmp_path: Path,
) -> None:
    config = render(SessionRequest(cwd=tmp_path))

    assert config.submission_gate_resolver is None


def test_a_request_is_uncontained_until_it_says_otherwise() -> None:
    """The default is what every request meant before the field existed."""
    request = SessionRequest()

    assert request.containment == "none"
    assert request.contained_program is None


def test_an_outer_request_names_the_program_that_enters_its_container() -> None:
    """Asking for the container without one would open on the host."""
    with pytest.raises(ValidationError, match="contained_program"):
        SessionRequest(containment="outer")


@pytest.mark.parametrize("wall", ["inner", "none"])
def test_a_program_nothing_would_start_is_refused(wall: SessionContainment) -> None:
    """A wrapper named by a request that opens no container never runs.

    Refused rather than ignored: the request reads as contained, and the
    session it opens is not, which is the one failure a boundary cannot
    afford to state wrongly.
    """
    with pytest.raises(ValidationError, match="containment='outer'"):
        SessionRequest(containment=wall, contained_program=Path("enter.sh"))


def test_claude_opens_an_inner_session_in_its_own_sandbox(tmp_path: Path) -> None:
    config = claude_config(SessionRequest(cwd=tmp_path, containment="inner"))

    assert config.sandbox is not None
    assert config.sandbox.enabled
    assert config.sandbox.posture().active
    assert config.cli_path is None


def test_claude_stands_its_sandbox_down_inside_the_container(tmp_path: Path) -> None:
    """The container is the wall, and the session is told so in both fields.

    Told rather than left unsaid: a spawned session reads none of the
    settings files a launched one does, so an unstated sandbox is decided by
    whatever the runtime falls back to — and the policy judging the session
    would be reading a posture nobody set.
    """
    program = tmp_path / "enter.sh"
    config = claude_config(
        SessionRequest(cwd=tmp_path, containment="outer", contained_program=program)
    )

    assert config.cli_path == program
    assert config.sandbox is not None
    assert not config.sandbox.enabled
    assert not config.sandbox.posture().active


def test_claude_says_nothing_about_a_wall_nobody_asked_for(tmp_path: Path) -> None:
    config = claude_config(SessionRequest(cwd=tmp_path))

    assert config.sandbox is None
    assert config.cli_path is None


@pytest.mark.parametrize("degree", AUTONOMY_DEGREES)
def test_claude_decides_autonomy_and_containment_apart(degree: SessionAutonomy) -> None:
    """Every degree of autonomy keeps the sandbox the request asked for.

    The property Codex cannot state this simply, and the reason the two
    adapters are tested differently rather than through one parametrization.
    """
    config = claude_config(SessionRequest(autonomy=degree, containment="inner"))

    assert config.permission_mode == CLAUDE_AUTONOMY[degree]
    assert config.sandbox == CLAUDE_CONTAINMENT["inner"]


@pytest.mark.parametrize("wall", CONTAINMENT_WALLS)
def test_every_runtime_spells_every_wall(wall: SessionContainment) -> None:
    """A wall added to the axis fails here until both runtimes answer it."""
    assert wall in CLAUDE_CONTAINMENT
    assert wall in CODEX_CONTAINMENT


def test_codex_opens_an_inner_session_in_its_own_sandbox(tmp_path: Path) -> None:
    config = codex_config(SessionRequest(cwd=tmp_path, containment="inner"))

    assert config.sandbox == "workspace-write"
    assert config.executable == CODEX_PROGRAM


def test_codex_stands_its_sandbox_down_inside_the_container(tmp_path: Path) -> None:
    """Codex confines with kernel facilities a container will not nest.

    So the container takes the field outright rather than being narrowed
    into a second boundary that cannot start where it was asked for.
    """
    program = tmp_path / "enter.sh"
    config = codex_config(
        SessionRequest(cwd=tmp_path, containment="outer", contained_program=program)
    )

    assert config.sandbox == "danger-full-access"
    assert config.executable == program


@pytest.mark.parametrize("degree", AUTONOMY_DEGREES)
def test_codex_leaves_an_unwalled_session_to_its_autonomy(
    degree: SessionAutonomy, tmp_path: Path
) -> None:
    """Asking for no wall renders what the request rendered before the axis."""
    config = codex_config(SessionRequest(cwd=tmp_path, autonomy=degree))

    assert config.sandbox == CODEX_AUTONOMY[degree]


@pytest.mark.parametrize("degree", AUTONOMY_DEGREES)
def test_neither_axis_widens_what_the_other_narrowed(
    degree: SessionAutonomy, tmp_path: Path
) -> None:
    """The inner wall and every autonomy settle on the narrower of the two.

    Stated over every degree rather than over the interesting one, because
    the property is that no degree escapes the wall — an unattended session
    reaches `workspace-write` and no further, and a planning one is not
    widened to it.
    """
    config = codex_config(
        SessionRequest(cwd=tmp_path, autonomy=degree, containment="inner")
    )

    assert config.sandbox is not None
    ordering = CODEX_SANDBOX_WIDTH.index
    assert ordering(config.sandbox) == min(
        ordering("workspace-write"), ordering(CODEX_AUTONOMY[degree])
    )


def test_an_outer_codex_session_keeps_its_wall_whatever_it_may_do(
    tmp_path: Path,
) -> None:
    """The one place the narrower reading is deliberately not taken."""
    program = tmp_path / "enter.sh"
    config = codex_config(
        SessionRequest(
            cwd=tmp_path,
            autonomy="plan",
            containment="outer",
            contained_program=program,
        )
    )

    assert config.sandbox == "danger-full-access"
