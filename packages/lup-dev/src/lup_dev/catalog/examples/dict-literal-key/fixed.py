"""Read a hook's payload."""

from lup.types import Model


class Payload(Model):
    """The part of a hook's payload read here."""

    tool_name: str


def tool(payload: str) -> str:
    """Return the tool a hook's payload names."""
    return Payload.model_validate_json(payload).tool_name
