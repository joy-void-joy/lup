"""Read a hook's payload."""

import json


def tool(payload: str) -> str:
    """Return the tool a hook's payload names."""
    data: dict[str, str] = json.loads(payload)
    return data["tool_name"]
