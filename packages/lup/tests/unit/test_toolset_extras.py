"""The toolset module serves every group without the extras one group needs.

Every tool server a generated plugin starts imports :mod:`lup.tools.toolsets`,
whichever group it serves. Naming the sandbox's container class there made the
`docker` extra a requirement of importing it at all, so a project that declined
the sandbox — and so installed no `lup[docker]` — could start none of its tool
servers. The group reads one verb off a session's container, and that verb is
all the module names.
"""

import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from lup.orchestration.reflection import ReviewGate
from lup.tools.mcp import LupMcpTool, lup_tool
from lup.tools.toolsets import SessionNeeds, sandbox_group


class Code(BaseModel):
    source: str


@lup_tool("Run the supplied source.")
async def execute_code(params: Code) -> Code:
    return params


class StandInContainer:
    """A container as the sandbox group reads one: something with its verbs."""

    def create_tools(self) -> list[LupMcpTool]:
        return [execute_code]


def test_importing_the_toolsets_needs_no_docker_extra() -> None:
    """Asked in a fresh interpreter, with `docker` made unimportable.

    In this one the extra is installed and every earlier test may have
    imported the container already, so the assertion would measure the run.
    """
    reported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['docker'] = None; "
            "import lup.tools.toolsets; "
            "print('lup.sandbox.container' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert reported == "False"


def test_the_sandbox_group_serves_the_container_the_session_was_given(
    tmp_path: Path,
) -> None:
    given = SessionNeeds(
        session_dir=tmp_path,
        root=tmp_path,
        gate=ReviewGate(),
        sandbox=StandInContainer(),
    )

    assert sandbox_group().tools(given) == [execute_code]
    assert sandbox_group().tools(given.model_copy(update={"sandbox": None})) == []
