"""Account readiness through Codex's own credential-refresh boundary."""

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lup.providers.codex.app_server import CodexAppServer
from lup.types import EnvVars


class CodexAccountIdentity(BaseModel, frozen=True):
    """Retain the authentication kind, not account identifiers or credentials."""

    type: Literal["apiKey", "chatgpt", "amazonBedrock"]


class CodexAccountState(BaseModel, frozen=True):
    """Native account/read response, projected onto the readiness decision."""

    account: CodexAccountIdentity | None = None
    requires_openai_auth: bool = Field(alias="requiresOpenaiAuth")

    @property
    def ready(self) -> bool:
        """An account exists, or this endpoint does not require OpenAI auth.

        requiresOpenaiAuth describes the endpoint's authentication requirement,
        not whether the current account is signed out.
        """
        return self.account is not None or not self.requires_openai_auth


async def read_account(
    executable: Path,
    environment: EnvVars,
    *,
    refresh_token: bool = False,
    timeout_seconds: float = 20,
    arguments: list[str] | None = None,
) -> CodexAccountState:
    """Ask the native runtime to read, optionally refreshing its managed login.

    No token is parsed, copied, logged, or refreshed by Lup. A local expiry
    timestamp is not evidence that a remote service accepts the credential;
    refreshToken asks the credential owner to renew it before use. A failed
    refresh remains an error rather than a successful local-file check.
    """
    server = CodexAppServer(executable, arguments=arguments, environment=environment)
    try:
        async with asyncio.timeout(timeout_seconds):
            await server.start()
            payload = await server.request(
                "account/read", {"refreshToken": refresh_token}
            )
            return CodexAccountState.model_validate(payload)
    finally:
        await server.close()
