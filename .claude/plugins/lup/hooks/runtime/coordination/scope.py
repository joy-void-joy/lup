"""Execution identity for native queues whose home and daemon must be reachable."""

import hashlib
import json
import os
from pathlib import Path


def execution_scope() -> str:
    """Prove one Linux host, root, user and namespace scope; unknown is empty."""
    try:
        root = Path("/proc/self/root").stat()
        identity = {
            "root": [root.st_dev, root.st_ino],
            "user": os.geteuid(),
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "namespaces": {
                name: [stat.st_dev, stat.st_ino]
                for name in ("mnt", "net", "user")
                for stat in [Path("/proc/self/ns", name).stat()]
            },
        }
    except OSError:
        # Missing kernel evidence is an unsupported route, not an inferred match.
        return ""
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
