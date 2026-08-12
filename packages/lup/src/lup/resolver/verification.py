"""Running one tree through the whole verification set a run was given.

Three phases ask this question of three different trees — a concern's own
worktree before it is reviewed, the tree each join produces, and the
integrated result — and none of them is about the others. Naming the check
itself is what lets each hold the answer without holding the phase that
asked it first.
"""

from pathlib import Path

from lup.harness.process import LaunchRequest, ProcessLauncher
from lup.resolver.models import VerificationCommand, VerificationRecord


class Verifier:
    """The run's verification commands, and one tree at a time to run them on."""

    def __init__(
        self, commands: list[VerificationCommand], launcher: ProcessLauncher
    ) -> None:
        self.commands = commands
        self.launcher = launcher

    def verify(self, root: Path, base: str = "") -> list[VerificationRecord]:
        """Run the whole verification set against one tree, from its own base.

        The full set every time, never a fast subset. Per-join verification
        is the only mechanical detector of a clean merge that is jointly
        wrong — one branch changes a signature, another adds a caller, and
        the type error exists in neither parent alone — and a subset chosen
        for speed is exactly the one that misses it.

        The base is the tree's, not the run's. A gate scoped to what changed
        has to be told where this tree started, and a run whose leases start
        from different commits has no single answer to give it once.
        """
        records: list[VerificationRecord] = []  # lup: ignore[empty-collection]
        for command in self.commands:
            arguments = command.against(base)
            status = self.launcher.launch(LaunchRequest(arguments=arguments, cwd=root))
            records.append(
                VerificationRecord(
                    name=command.name,
                    arguments=arguments,
                    passed=status.code == 0,
                    exit_code=status.code,
                )
            )
        return records
