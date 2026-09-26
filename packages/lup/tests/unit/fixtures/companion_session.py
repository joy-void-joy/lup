"""One launcher's session beside a checkout's companions, as a process of its own.

Run by ``test_shared_companions``: it joins the companions its spec declares,
writes what it learned, and holds them until the spec's release file appears
-- or until it is killed, which is a launcher that died without letting go.
A process rather than a context in the test's own, because what is pinned is
a companion outliving the launcher that started it, and several launchers
racing for one lock.
"""

import os
import sys
import time
from pathlib import Path

from pydantic import BaseModel

from lup.devtools.envfiles import HostSecrets, SecretsLocation
from lup.devtools.harness.companions import companions_running
from lup.harness.companions import HostCompanion


class SessionSpec(BaseModel, frozen=True):
    """What one stand-in launcher joins, and where it reports and waits."""

    declared: list[HostCompanion]
    root: Path
    home: Path
    config: Path
    learned: Path
    release: Path


def main(spec_path: Path) -> None:
    """Join, report, hold until released, then let go."""
    spec = SessionSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    store = HostSecrets.of("adlib", SecretsLocation(xdg_config_home=spec.config))
    with companions_running(
        spec.declared,
        spec.root,
        spec.home,
        store,
        {"PATH": os.defpath},
        browser=lambda _url: True,
    ) as beside:
        staged = spec.learned.with_name(f"{spec.learned.name}.tmp")
        staged.write_text(beside.model_dump_json(), encoding="utf-8")
        staged.replace(spec.learned)
        for _ in iter(spec.release.exists, True):
            time.sleep(0.02)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
