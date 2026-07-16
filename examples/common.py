"""Shared typed output used by the runtime examples."""

from pydantic import BaseModel, ConfigDict, Field


class Summary(BaseModel):
    """A minimal structured result submitted by an example agent."""

    model_config = ConfigDict(frozen=True)

    summary: str = Field(min_length=1)
