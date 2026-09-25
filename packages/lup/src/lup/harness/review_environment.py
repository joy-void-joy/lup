"""Credential-free review inbox discovery shared by launchers and tools."""

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings

# lup: ignore[constant-declaration] — this relay name is shared by host launchers and native-session readers.
REVIEW_INBOX_URL_ENV: Final = "LUP_REVIEW_INBOX_URL"


class ReviewInboxEnvironment(BaseSettings):
    """Only the nonsecret endpoint is inherited by a launched agent."""

    endpoint: str = Field(default="", validation_alias=REVIEW_INBOX_URL_ENV)
