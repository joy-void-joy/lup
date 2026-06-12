"""Behavior tests for the lup_tool decorator and LupMcpTool.

Covers the three response paths of the SDK-facing handler (success,
ToolError, input validation failure) and the direct-call path that
bypasses MCP serialization.
"""

import json
from typing import cast

from pydantic import BaseModel, Field

from lup.mcp import ToolError, ToolResponse, lup_tool


class EchoInput(BaseModel):
    text: str = Field(description="Text to echo")


class EchoOutput(BaseModel):
    text: str


@lup_tool("Echo the input text back.", name="echo")
async def echo(inp: EchoInput) -> EchoOutput:
    if inp.text == "boom":
        raise ToolError("exploded")
    return EchoOutput(text=inp.text)


def response_text(resp: ToolResponse) -> str:
    content = resp.get("content")
    assert content is not None
    return content[0]["text"]


async def test_direct_call_returns_typed_output() -> None:
    result = await echo(EchoInput(text="hi"))
    assert isinstance(result, EchoOutput)
    assert result.text == "hi"


async def test_sdk_handler_serializes_output_as_json() -> None:
    resp = cast(ToolResponse, await echo.handler({"text": "hi"}))
    assert not resp.get("is_error")
    assert json.loads(response_text(resp)) == {"text": "hi"}


async def test_tool_error_becomes_is_error_response() -> None:
    resp = cast(ToolResponse, await echo.handler({"text": "boom"}))
    assert resp.get("is_error") is True
    assert "exploded" in response_text(resp)


async def test_invalid_input_becomes_is_error_with_message() -> None:
    resp = cast(ToolResponse, await echo.handler({"wrong_field": 1}))
    assert resp.get("is_error") is True
    assert "Invalid input" in response_text(resp)


def test_models_inferred_from_annotations() -> None:
    assert echo.input_model is EchoInput
    assert echo.output_model is EchoOutput
    assert echo.name == "echo"
    assert echo.input_schema == EchoInput.model_json_schema()
