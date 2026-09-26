"""A companion runs on the host for exactly as long as the session beside it.

Real processes, because what is pinned is process lifetime: started when the
launch is cleared to open, still running while the session runs, and gone —
with whatever it started — once the session ends. A program this machine
does not have is said and skipped rather than failing the launch.

And real environments, because what is pinned about secrets is who holds
one: the companion that names a key gets it from the host store, a companion
that does not never does, and the session — on the host or in the container —
never does either, even where the operator's shell exported it. Nor does any
mount: none a launch makes carries the store's directory, and a registration
that would is refused.
"""

import os
import time
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

import pytest
import sh
import typer

import lup.devtools.harness.launch as launch
from lup.devtools.envfiles import HostSecrets, SecretsLocation
from lup.devtools.harness.companions import companions_running
from lup.devtools.harness.contained import (
    host_only_directories,
    refuse_host_only_mounts,
)
from lup.harness.companions import HostCompanion
from lup.harness.image import Docker, Image
from lup.harness.notice import Notice
from lup.harness.requirements import Manifest
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.login import ProviderLogin
from lup.sandbox.rail import AccessibleRoot, fleet_lease
from lup.trust.approved import APPROVED_TREE_ENV
from lup.types import EnvVars

KEY = "GEMINI_API_KEY"
"""The key a listener companion needs and no session may hold."""

SECRET = "AIza-host-only-value"
"""What the host store holds for the key, recognisable wherever it lands."""

EXPORTED = "AIza-exported-in-the-shell"
"""What the operator's shell exported under the same name."""

PLAIN: EnvVars = {"PATH": os.defpath}
"""An inherited environment carrying nothing but where programs are."""


@pytest.fixture
def store(tmp_path: Path) -> HostSecrets:
    """A host store under a throwaway configuration home."""
    return HostSecrets.of("adlib", SecretsLocation(xdg_config_home=tmp_path / "config"))


def alive(pid: int) -> bool:
    """Whether a process with this id still exists and has not been reaped as a zombie."""
    status = Path(f"/proc/{pid}/stat")
    if not status.exists():
        return False
    return status.read_text(encoding="utf-8").split()[2] != "Z"


def eventually(condition: object, seconds: float = 5.0) -> bool:
    """Whether a condition becomes true within a few seconds, polling briefly."""
    assert callable(condition)
    deadline = time.monotonic() + seconds
    for _ in iter(lambda: time.monotonic() < deadline, False):
        if condition():
            return True
        time.sleep(0.05)
    return bool(condition())


def printing(name: str, written: Path, secrets: list[str] = []) -> HostCompanion:
    """A companion writing what it holds under the key, or ``unset``, to a file."""
    return HostCompanion(
        name=name,
        command=["sh", "-c", f'printf %s "${{{KEY}-unset}}" > {written}; sleep 60'],
        secrets=secrets,
    )


def test_a_companion_runs_while_the_session_does_and_stops_after(
    tmp_path: Path, store: HostSecrets
) -> None:
    """What it started stops with it: the signal reaches its whole group."""
    pidfile = tmp_path / "child.pid"
    serving = HostCompanion(
        name="preview",
        command=["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"],
        url="http://127.0.0.1:8080",
    )

    with companions_running(
        [serving], tmp_path, tmp_path / "logs", store, PLAIN
    ) as said:
        assert eventually(pidfile.exists)
        child = int(pidfile.read_text(encoding="utf-8"))
        assert alive(child)
        assert said[0].text.startswith(
            "Companion preview: http://127.0.0.1:8080 (log: "
        )

    assert eventually(lambda: not alive(child))


def test_a_companion_runs_where_it_is_declared_and_logs_beside_the_launch(
    tmp_path: Path, store: HostSecrets
) -> None:
    (tmp_path / "studio").mkdir()
    printing_where = HostCompanion(
        name="where", command=["pwd"], directory=PurePosixPath("studio")
    )

    with companions_running(
        [printing_where], tmp_path, tmp_path / "logs", store, PLAIN
    ):
        log = tmp_path / "logs" / "where.log"
        assert eventually(
            lambda: log.exists() and log.read_text(encoding="utf-8") != ""
        )

    assert log.read_text(encoding="utf-8").strip() == str(tmp_path / "studio")


def test_a_program_this_machine_lacks_is_said_and_skipped(
    tmp_path: Path, store: HostSecrets
) -> None:
    missing = HostCompanion(name="missing", command=["no-such-program-anywhere"])
    present = HostCompanion(name="present", command=["sleep", "60"])

    with companions_running(
        [missing, present], tmp_path, tmp_path / "logs", store, PLAIN
    ) as said:
        texts = [notice.text for notice in said]

    assert texts[0] == (
        "Companion missing: no-such-program-anywhere is not installed here, "
        "so it was not started"
    )
    assert texts[1].startswith("Companion present: (log: ")


def test_a_companion_directory_stays_inside_the_checkout() -> None:
    with pytest.raises(ValueError, match="inside the checkout"):
        HostCompanion(name="away", command=["true"], directory=PurePosixPath("../x"))


def test_a_companion_is_handed_the_secrets_it_names_and_no_other_is(
    tmp_path: Path, store: HostSecrets
) -> None:
    """From the store alone: the shell's export of the same name reaches neither."""
    store.write({KEY: SECRET})
    named = tmp_path / "named.out"
    unnamed = tmp_path / "unnamed.out"
    inherited = {**PLAIN, KEY: EXPORTED}

    with companions_running(
        [printing("listener", named, [KEY]), printing("preview", unnamed)],
        tmp_path,
        tmp_path / "logs",
        store,
        inherited,
    ):
        assert eventually(lambda: named.exists() and unnamed.exists())
        assert eventually(lambda: named.read_text(encoding="utf-8") != "")

    assert named.read_text(encoding="utf-8") == SECRET
    assert unnamed.read_text(encoding="utf-8") == "unset"


def test_a_secret_the_store_lacks_is_said_and_the_companion_starts_anyway(
    tmp_path: Path, store: HostSecrets
) -> None:
    written = tmp_path / "listener.out"

    with companions_running(
        [printing("listener", written, [KEY])],
        tmp_path,
        tmp_path / "logs",
        store,
        {**PLAIN, KEY: EXPORTED},
    ) as said:
        assert eventually(
            lambda: written.exists() and written.read_text(encoding="utf-8") != ""
        )

    assert said[0] == Notice(
        text=(
            f"Companion listener: {KEY} not in the host store ({store.path}), so it "
            f"starts without; `lup-launch run setup secret {KEY}` sets it"
        ),
        urgency="boundary",
    )
    assert written.read_text(encoding="utf-8") == "unset"


def test_a_companion_secret_is_named_as_an_environment_variable() -> None:
    with pytest.raises(ValueError, match="pattern"):
        HostCompanion(name="listener", command=["true"], secrets=["not a name"])


class Launching:
    """One Claude launch with everything but its environment handling stood in for.

    Records what the session was handed — the environment its argv was built
    against and the one its process started with — and what the companions'
    runner was handed, so a test can read who held what.
    """

    def __init__(
        self,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
        companions: list[HostCompanion],
    ) -> None:
        self.events: list[str] = []
        self.argv_environments: list[EnvVars] = []
        self.session_environments: list[EnvVars] = []
        self.runner_arguments: list[tuple[object, ...]] = []
        self.composition = Mock()
        plugin = Mock()
        plugin.name = "lup"
        self.composition.recipe.source.plugins = [plugin]
        self.composition.recipe.source.image = Image()
        self.composition.recipe.source.companions = companions
        events = self.events
        runner_arguments = self.runner_arguments

        class Recording:
            """Stands in for the runner, recording when it starts and stops."""

            def __init__(self, *args: object) -> None:
                runner_arguments.append(args)
                events.append("companions started")

            def __enter__(self) -> list[object]:
                return []

            def __exit__(self, *args: object) -> None:
                events.append("companions stopped")

        def cleared(*args: object, **kwargs: object) -> launch.LaunchOpening:
            events.append("cleared")
            return launch.LaunchOpening()

        def argv(name: str, *args: object, **kwargs: object) -> list[str]:
            environment = args[6]
            assert isinstance(environment, dict)
            self.argv_environments.append(dict(environment))
            return [name]

        def session(_name: str) -> object:
            def started(*args: object, **kwargs: object) -> None:
                environment = kwargs["_env"]
                assert isinstance(environment, dict)
                self.session_environments.append(dict(environment))
                events.append("session")

            return started

        monkeypatch.setattr(launch, "ready_to_open", cleared)
        monkeypatch.setattr(launch, "companions_running", Recording)
        monkeypatch.setattr(launch, "project_root", lambda: root)
        monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: root)
        monkeypatch.setattr(launch, "session_argv", argv)
        monkeypatch.setattr(launch, "session_defaults", lambda: {})
        monkeypatch.setattr(launch, "accessible_roots", lambda: [])
        monkeypatch.setattr(launch, "apply_sandbox_environment", lambda *a, **k: None)
        monkeypatch.setattr(launch, "start_harness_transcript", lambda *a, **k: Mock())
        monkeypatch.setattr(launch, "ClaudeTranscripts", lambda _home: Mock())
        monkeypatch.setattr(sh, "Command", session)

    def launch(self) -> None:
        profiles = Mock()
        profiles.launch_home.return_value = None
        launch.launch_claude(self.composition, [], profiles, None, None, False)


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project named adlib, whose host store sits under a throwaway config home."""
    root = tmp_path / "adlib"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "adlib"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(APPROVED_TREE_ENV, raising=False)
    return root


def test_the_launch_starts_companions_once_cleared_and_stops_them_after_the_session(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleared to open, then the companion, then the session, then the stop."""
    launching = Launching(
        checkout, monkeypatch, [HostCompanion(name="preview", command=["sleep", "60"])]
    )

    launching.launch()

    assert launching.events == [
        "cleared",
        "companions started",
        "session",
        "companions stopped",
    ]


def test_a_host_only_key_the_shell_exported_never_reaches_the_session(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither the argv's environment, the session process's, nor the companions' base.

    The companions' runner is handed the store the key is read from; what
    it hands a companion is the test above.
    """
    HostSecrets.of("adlib", SecretsLocation(xdg_config_home=tmp_path / "config")).write(
        {KEY: SECRET, "OTHER_HOST_ONLY": "kept on the host"}
    )
    monkeypatch.setenv(KEY, EXPORTED)
    monkeypatch.setenv("OTHER_HOST_ONLY", EXPORTED)
    launching = Launching(
        checkout,
        monkeypatch,
        [HostCompanion(name="listener", command=["sleep", "60"], secrets=[KEY])],
    )

    launching.launch()

    [argv_environment] = launching.argv_environments
    [session_environment] = launching.session_environments
    [(_declared, _root, _logs, store, inherited)] = launching.runner_arguments
    for environment in (argv_environment, session_environment, inherited):
        assert isinstance(environment, dict)
        assert KEY not in environment
        assert "OTHER_HOST_ONLY" not in environment
        assert SECRET not in environment.values()
        assert EXPORTED not in environment.values()
    assert isinstance(store, HostSecrets)
    assert store.path == tmp_path / "config" / "lup" / "secrets" / "adlib.env"


def test_only_named_variables_cross_into_the_container(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The contained argv hands variables by name, and a host-only name is never one.

    The real ``session_argv`` and the real argv the image assembles, with only
    the engine-facing half of ``contained_argv`` stood in for. Every ``-e``
    naming a variable without a value takes it from the engine's own
    environment -- so the proof is both halves: no such name is the key, and
    the engine's environment does not hold it either.
    """
    monkeypatch.setenv(KEY, EXPORTED)
    forwarded: list[list[str]] = []

    def contained(
        image: Image,
        manifest: Manifest,
        root: Path,
        rendezvous: Path | None,
        credential: Path | None,
        login: ProviderLogin,
        **kwargs: object,
    ) -> list[str]:
        names = kwargs["inherited_environment"]
        assert isinstance(names, list)
        forwarded.append([str(name) for name in names])
        return image.session_arguments(
            tag="lup-agent:test",
            checkout=root,
            uid=1000,
            gid=1000,
            writable={root: str(root)},
            read_only={},
            state_volume="lup-cfg-test",
            config_home_env=login.config_home_env,
            engine=Docker(),
            inherited_environment=forwarded[-1],
        )

    monkeypatch.setattr(launch, "project_root", lambda: checkout)
    monkeypatch.setattr(launch, "accessible_roots", lambda *args: [])
    monkeypatch.setattr(launch, "settle_boundary", Mock())
    monkeypatch.setattr(launch, "say_opening", Mock())
    monkeypatch.setattr(launch, "verify_inside", Mock(return_value=[]))
    monkeypatch.setattr(launch, "contained_argv", contained)
    composition = Mock()
    composition.recipe.source.image = Image()
    composition.recipe.source.companions = [
        HostCompanion(name="listener", command=["true"], secrets=[KEY])
    ]
    composition.clipboard_transport = "commands"
    environment = launch.session_environment([KEY])

    argv = launch.session_argv(
        "claude",
        [],
        composition,
        Mock(hooks=None),
        tmp_path,
        CLAUDE_LOGIN,
        launch.LaunchSandbox.OUTER,
        environment,
    )

    assert not any(KEY in word or EXPORTED in word for word in argv)
    by_name = [
        word
        for flag, word in zip(argv, argv[1:], strict=False)
        if flag == "-e" and "=" not in word
    ]
    assert by_name and set(by_name) <= {*forwarded[0], *Image().forge.inherited(False)}
    assert KEY not in environment


@pytest.fixture
def repository(checkout: Path) -> Path:
    """The same checkout, committed, as a contained launch leases one."""
    for arguments in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["commit", "-q", "-m", "base"],
    ):
        sh.Command("git")("-C", str(checkout), *arguments)
    return checkout


def test_a_launch_never_mounts_the_store(repository: Path, tmp_path: Path) -> None:
    HostSecrets.for_checkout(repository).write({KEY: SECRET})
    lease = fleet_lease(repository)

    refuse_host_only_mounts(lease, host_only_directories())
    argv = Image().session_arguments(
        tag="lup-agent:test",
        checkout=repository,
        uid=1000,
        gid=1000,
        writable=lease.mounted_writable(),
        read_only=lease.read_only,
        state_volume="lup-cfg-test",
        config_home_env="CLAUDE_CONFIG_DIR",
        engine=Docker(),
    )

    assert not any(str(tmp_path / "config") in word for word in argv)


def test_a_registration_enclosing_the_store_is_refused(
    repository: Path, tmp_path: Path
) -> None:
    HostSecrets.for_checkout(repository).write({KEY: SECRET})
    lease = fleet_lease(repository, [AccessibleRoot(path=tmp_path, writable=False)])

    with pytest.raises(typer.BadParameter, match="host-only secrets"):
        refuse_host_only_mounts(lease, host_only_directories())


def test_a_registration_inside_the_store_is_refused(
    repository: Path, tmp_path: Path
) -> None:
    inside = tmp_path / "config" / "lup" / "secrets" / "nested"
    inside.mkdir(parents=True)
    lease = fleet_lease(repository, [AccessibleRoot(path=inside)])

    with pytest.raises(typer.BadParameter, match="host-only secrets"):
        refuse_host_only_mounts(lease, host_only_directories())


def test_a_checkout_holding_the_store_is_refused_naming_what_moves_it(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(repository / ".config"))

    with pytest.raises(typer.BadParameter, match="XDG_CONFIG_HOME"):
        refuse_host_only_mounts(fleet_lease(repository), host_only_directories())


def test_the_store_directory_is_the_one_held_from_every_container(
    checkout: Path, tmp_path: Path
) -> None:
    [secrets] = [
        held for held in host_only_directories() if held.holds == "host-only secrets"
    ]
    assert secrets.path == SecretsLocation().directory()
    assert secrets.path == HostSecrets.for_checkout(checkout).path.parent
    assert secrets.path == tmp_path / "config" / "lup" / "secrets"
