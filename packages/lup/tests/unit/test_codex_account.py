"""Readiness and refresh remain native, bounded, and free of identity payloads."""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from lup.providers.codex.account import CodexAccountState, read_account
from lup.providers.codex.app_server import AppServerError, CodexAppServer, RpcError
from lup.types import JsonObject, JsonValue


@pytest.mark.parametrize("kind", ["chatgpt", "apiKey", "amazonBedrock"])
def test_authenticated_endpoint_is_ready_even_when_auth_is_required(kind: str) -> None:
    state = CodexAccountState.model_validate(
        {
            "account": {
                "type": kind,
                "email": "private@example.invalid",
                "planType": "private",
            },
            "requiresOpenaiAuth": True,
        }
    )
    assert state.ready
    assert state.account is not None
    assert state.account.model_dump() == {"type": kind}
    assert "private" not in state.model_dump_json()


def test_missing_account_requires_login_only_for_authenticated_endpoint() -> None:
    assert not CodexAccountState.model_validate(
        {"account": None, "requiresOpenaiAuth": True}
    ).ready
    assert CodexAccountState.model_validate(
        {"account": None, "requiresOpenaiAuth": False}
    ).ready
    with pytest.raises(ValidationError):
        CodexAccountState.model_validate({"account": None})


@pytest.mark.parametrize("refresh", [False, True])
async def test_native_account_request_and_process_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    refresh: bool,
) -> None:
    calls: list[tuple[str, JsonObject]] = []

    async def start(_self: CodexAppServer) -> None:
        calls.append(("start", {}))

    async def request(
        _self: CodexAppServer, method: str, params: JsonObject
    ) -> JsonValue:
        calls.append((method, params))
        return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}

    async def close(_self: CodexAppServer) -> None:
        calls.append(("close", {}))

    monkeypatch.setattr(CodexAppServer, "start", start)
    monkeypatch.setattr(CodexAppServer, "request", request)
    monkeypatch.setattr(CodexAppServer, "close", close)
    assert (await read_account(Path("codex"), {}, refresh_token=refresh)).ready
    assert calls == [
        ("start", {}),
        ("account/read", {"refreshToken": refresh}),
        ("close", {}),
    ]


@pytest.mark.parametrize("failure", ["timeout", "remote"])
async def test_failed_read_is_not_readiness_and_still_closes(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    closed: list[bool] = []

    async def start(_self: CodexAppServer) -> None:
        if failure == "remote":
            raise AppServerError(RpcError(code=401, message="token_expired"))
        await asyncio.Event().wait()

    async def close(_self: CodexAppServer) -> None:
        closed.append(True)

    monkeypatch.setattr(CodexAppServer, "start", start)
    monkeypatch.setattr(CodexAppServer, "close", close)
    with pytest.raises(TimeoutError if failure == "timeout" else AppServerError):
        await read_account(Path("codex"), {}, refresh_token=True, timeout_seconds=0.01)
    assert closed == [True]
