"""The package root stays a deliberately small runtime front door.

Small, and no longer only nouns. The root once exported eight carrier types and
nothing that made one, so `import lup` reached no constructor at all and every
non-trivial example had to open a session by importing an adapter — the tier
`seam-boundary` fails the build over everywhere else in the library. The
constructors below are what that cost, asserted here so the root cannot quietly
become a vocabulary again.
"""

import subprocess
import sys

import lup

CONSTRUCTORS = {"create_claude", "create_client", "create_codex"}


def in_a_fresh_interpreter(source: str) -> str:
    """Run one program in its own interpreter and hand back what it printed.

    Import-time properties can only be asserted where nothing has imported
    anything yet. In-process, `sys.modules` carries whatever every earlier test
    in the session pulled in — this suite loads the Claude SDK elsewhere — so
    an in-process version of the assertions below would be measuring the test
    run rather than the package.
    """
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_every_export_resolves() -> None:
    missing = [name for name in lup.__all__ if getattr(lup, name, None) is None]
    assert missing == []


def test_root_exports_only_portable_runtime_conveniences() -> None:
    assert set(lup.__all__) == {  # lup: ignore[set-shape] — exact export comparison
        "Client",
        "Provider",
        "SessionHandle",
        "SessionId",
        "TurnHandle",
        "TurnId",
        "TurnInput",
        "TurnRequest",
        "TurnResult",
        "create_claude",
        "create_client",
        "create_codex",
        "turn_request",
    }


def test_the_root_exports_something_that_builds_a_client() -> None:
    """The property the export list above is only one spelling of.

    A reader who has found `import lup` must be able to get a client from it.
    Stated separately because the set comparison passes for any set — including
    one that has lost every constructor and kept the nouns, which is exactly
    the state this whole surface was rebuilt out of.
    """
    assert CONSTRUCTORS <= set(lup.__all__)
    assert all(callable(getattr(lup, name)) for name in CONSTRUCTORS)


def test_importing_lup_loads_no_provider_sdk_and_stays_small() -> None:
    """The promise the module docstring makes, measured where it is meaningful.

    Eagerly re-exporting the constructors pulled 811 modules and roughly 1.3
    seconds — an ASGI server and a CLI framework among them — on behalf of a
    caller who may have wanted a type annotation. Deferring them is what makes
    the root cheap enough to be the thing everybody imports.
    """
    reported = in_a_fresh_interpreter(
        "import sys, lup; print(len(sys.modules), 'claude_agent_sdk' in sys.modules)"
    )
    count, sdk_loaded = reported.split()

    assert sdk_loaded == "False"
    assert int(count) < 400, f"`import lup` pulled {count} modules"


def test_naming_a_constructor_loads_its_adapter_but_no_provider_sdk() -> None:
    """Reaching a constructor imports its adapter, which is unavoidable.

    The vendor's own SDK is not, and is loaded by opening a session instead —
    so `import lup` works, and keeps working, on a machine with only one
    provider's SDK installed, or neither.
    """
    reported = in_a_fresh_interpreter(
        "import sys; "
        "from lup import create_claude, create_codex; "
        "print(callable(create_claude), callable(create_codex), "
        "'claude_agent_sdk' in sys.modules)"
    )

    assert reported == "True True False"
