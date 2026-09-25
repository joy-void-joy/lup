"""Which Claude CLI a session runs, and what its tool results say about failing.

The SDK prefers the CLI it bundles, which lags the installed one — measured,
2.1.259 against an installed 2.1.282 — while the model catalog this library
types against is read from the installed one. A session therefore runs the
`claude` an interactive launch runs, and the bundled CLI only on a machine
with none installed.
"""

from pathlib import Path

from lup.providers.claude import Claude
from lup.providers.claude.runtime import build_claude_options, convert_claude_block
from lup.sessions.events import TurnToolResultBlock


def installed(directory: Path) -> Path:
    """A `claude` program in ``directory``, as an installation leaves one."""
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / "claude"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    return program


def cli_of(config: Claude) -> str | Path | None:
    return build_claude_options(
        config, servers={}, binding=lambda: None, resume=None, session_id=None
    ).cli_path


def test_a_session_runs_the_claude_on_its_path(tmp_path: Path) -> None:
    program = installed(tmp_path / "bin")

    assert cli_of(Claude(environment={"PATH": str(program.parent)})) == program


def test_the_bundled_cli_is_left_for_a_machine_with_none_installed(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "nothing-installed"
    empty.mkdir()

    assert cli_of(Claude(environment={"PATH": str(empty)})) is None


def test_a_program_the_declaration_names_is_the_one_run(tmp_path: Path) -> None:
    installed(tmp_path / "bin")
    wrapper = tmp_path / "container-wrapper"

    named = Claude(cli_path=wrapper, environment={"PATH": str(tmp_path / "bin")})

    assert cli_of(named) == wrapper


def test_a_tool_result_says_it_failed_as_the_transcript_does() -> None:
    """The live block and the history block agree, so a refusal reads as one."""
    import claude_agent_sdk as claude

    refused = convert_claude_block(
        claude.ToolResultBlock(tool_use_id="call-1", content="denied", is_error=True)
    )
    answered = convert_claude_block(
        claude.ToolResultBlock(tool_use_id="call-2", content=None)
    )

    assert refused == TurnToolResultBlock(
        tool_call_id="call-1", content="denied", is_error=True
    )
    assert answered == TurnToolResultBlock(tool_call_id="call-2", content="")
