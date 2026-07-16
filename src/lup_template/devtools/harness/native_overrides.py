"""Typed project-owned imports of recognized native frontmatter changes."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommandFrontmatterOverride(BaseModel):
    """Recognized native metadata that has a portable semantic equivalent."""

    model_config = ConfigDict(frozen=True)

    description: str = Field(min_length=1, max_length=1024)

    @field_validator("description")
    @classmethod
    def scalar_description(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("native frontmatter descriptions must be scalar")
        return value


COMMAND_FRONTMATTER_OVERRIDES: dict[
    str, CommandFrontmatterOverride
] = {}  # lup: ignore[empty-collection]
