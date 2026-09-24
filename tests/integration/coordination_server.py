"""An isolated native stdio fixture serving the production coordination group.

Its accelerated heartbeat exercises an expired roster pulse without waiting
for the production interval. Codex owns and stops this subprocess.
"""

from pathlib import Path

from lup.coordination.identity import session_member_id
from lup.coordination.peer_tools import RosterPulse
from lup.coordination.pulse import Pulse
from lup.coordination.wake import WakePath
from lup.orchestration.reflection import ReviewGate
from lup.tools.toolsets import (
    SessionNeeds,
    assembled,
    coordination_group,
    serve_toolset,
)


root = Path.cwd()
groups = [coordination_group()]
toolset = assembled(
    groups,
    SessionNeeds(
        root=root,
        session_dir=root / "session",
        gate=ReviewGate(),
        member=session_member_id(),
        wake=WakePath(runtime="codex"),
    ),
)
for companions in toolset.companions.values():
    for index, companion in enumerate(companions):
        if isinstance(companion, RosterPulse):
            companions[index] = companion.model_copy(
                update={"pulse": Pulse(interval_seconds=0.02)}
            )
serve_toolset(toolset, groups, "coordination", "coordination")
