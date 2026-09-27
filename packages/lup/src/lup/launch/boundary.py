"""The boundary a launch opens behind, vouched for the same way on every runtime."""

from lup.harness.models import HookSet
from lup.harness.notice import Notice
from lup.harness.requirements import Requirement
from lup.launch.declaration import LaunchSandbox
from lup.types import EnvVars


def apply_sandbox_environment(
    hooks: HookSet | None,
    environment: EnvVars,
    label: str,
    required_tools: list[Requirement],
    sandbox: LaunchSandbox = LaunchSandbox.INNER,
    announce: bool = True,
) -> bool:
    """Export LUP_SANDBOX_ACTIVE when the declared sandbox can actually run.

    The dispatchers defer unjudged shell only under this flag, so it is set
    exactly when the launch verified the OS boundary; without it the deny
    lattice keeps carrying the escalation recipe.

    Verified by exercising each tool rather than by finding it on PATH. The
    two answers differ exactly where it matters: a confinement binary that is
    installed and cannot start a namespace on this kernel is present and
    useless, and a flag set on its presence tells every dispatcher downstream
    to relax into a boundary that will not be there. Absence and breakage
    both leave the lattice standing, which is the safe direction, and the
    message says which of the two was found rather than only that one was.

    Asked only of a launch establishing the inner sandbox. A contained one
    has a boundary already, and the kernel reads it from what the launch
    measured rather than from anything a launcher asserts -- ``boundary =
    sandboxed or contained``, so the flag would change no verdict. Probing
    anyway printed a sandbox verdict about a session that was not going to
    rely on it, and on a failed probe printed ``deny lattice stays active``
    for a session whose lattice was about to stand down behind the container.
    Saying nothing is the honest report, and the container's own line says
    what the boundary is. A launch that chose no sandbox at all is not asked
    either: it wants the lattice standing, so there is nothing to vouch for.

    Each tool carries its own exercise rather than being named here and
    probed with a flag chosen by this function. That is not tidiness: the
    one flag this spelled for every tool was ``--version``, socat has no
    such option and exits 1 on it, and the OS boundary was therefore
    reported unavailable on every host in the world.

    Both runtimes vouch through here, which is the point of it taking the
    tools rather than naming them: Claude's confinement is a pair of programs
    and Codex's is its own envelope, and the asymmetry that mattered was not
    which tools but that one path exercised something and the other asserted
    the flag outright. *announce* is off where the caller has a better
    sentence for the success case -- a posture whose name is worth printing --
    and the failures are said either way, because that is the half a reader
    has to act on.

    Answers whether it vouched, so a caller can say so without re-deriving it
    from the environment it just passed in.
    """
    if sandbox is not LaunchSandbox.INNER or hooks is None or hooks.sandbox is None:
        return False
    findings = [tool.check(environment) for tool in required_tools]
    unusable = [finding for finding in findings if not finding.working]
    if unusable:
        for finding in unusable:
            for notice in finding.alarms():
                notice.say()
        Notice(
            text=f"{label} sandbox could not be verified. Command permission checks remain active.",
            urgency="warning",
        ).say()
        return False
    environment["LUP_SANDBOX_ACTIVE"] = "1"
    if announce:
        Notice(
            text=f"{label} sandbox: verified; it also restricts commands not covered by the policy.",
            urgency="boundary",
        ).say()
    return True
