# lup: ignore[cast, dict-get, dict-str-payload]
# Test fixtures and assertions construct these shapes deliberately.
"""Backend-adapter fidelity and API-hygiene regressions.

Each test pins a specific fix: Codex item coverage and web-search
mapping, full-model-ID passthrough for subagents, timestamp-ordered
session metadata, the guard that rejects spec fields the target engine
cannot honor, the PostToolUse tool_response relay, and the corrected
Codex custom-provider config keys.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from lup.adapters.clients.codex.compat import (
    OPENAI_COMPAT_API_KEY_ENV,
    OPENAI_COMPAT_PROVIDER_ID,
    build_openai_compat_native,
)
from lup.adapters.options import LupAgentOptions
from lup.mcp import ToolResponse
from lup.subagents import create_run_subagent_tool
from lup.types import (
    JsonValue,
    LupTextBlock,
    LupToolUseBlock,
    SubagentSpec,
)


def response_text(response: ToolResponse) -> str:
    return "".join(item.get("text", "") for item in response.get("content", []))


# ---------------------------------------------------------------------------
# Fix #1 — codex_items_to_lup covers every variant
# ---------------------------------------------------------------------------


class TestCodexItemCoverage:
    def test_unknown_variant_is_not_dropped(self) -> None:
        from openai_codex.generated.v2_all import PlanThreadItem, ThreadItem

        from lup.adapters.clients.codex.messages import codex_items_to_lup

        item = ThreadItem(
            root=PlanThreadItem(id="plan_1", text="step one\nstep two", type="plan")
        )
        blocks = codex_items_to_lup([item])

        assert len(blocks) == 1
        assert isinstance(blocks[0], LupTextBlock)
        assert "plan" in blocks[0].text

    def test_web_search_maps_to_websearch_tool_use(self) -> None:
        from openai_codex.generated.v2_all import (
            SearchWebSearchAction,
            ThreadItem,
            WebSearchAction,
            WebSearchThreadItem,
        )

        from lup.adapters.clients.codex.messages import codex_items_to_lup

        item = ThreadItem(
            root=WebSearchThreadItem(
                id="ws_1",
                query="codex config providers",
                action=WebSearchAction(
                    root=SearchWebSearchAction(
                        query="codex config providers",
                        queries=None,
                        type="search",
                    )
                ),
                type="webSearch",
            )
        )
        blocks = codex_items_to_lup([item])

        assert len(blocks) == 1
        block = blocks[0]
        assert isinstance(block, LupToolUseBlock)
        # Name + query shape are exactly what extract_sources() consumes.
        assert block.name == "WebSearch"
        assert block.input == {"query": "codex config providers"}

    def test_web_search_feeds_extract_sources(self) -> None:
        from openai_codex.generated.v2_all import (
            ThreadItem,
            WebSearchThreadItem,
        )

        from lup.adapters.clients.codex.messages import codex_items_to_lup
        from lup_template.agent.core import extract_sources

        item = ThreadItem(
            root=WebSearchThreadItem(
                id="ws_2", query="quiet sun", action=None, type="webSearch"
            )
        )
        blocks = codex_items_to_lup([item])

        assert extract_sources(blocks) == ["quiet sun"]


# ---------------------------------------------------------------------------
# Fix #4 — spec_to_claude passes full model IDs through
# ---------------------------------------------------------------------------


class TestSpecToClaudeModel:
    def test_full_model_id_passes_through(self) -> None:
        from lup.adapters.clients.claude.translate import spec_to_claude

        spec = SubagentSpec(
            name="deep",
            description="Deep reasoner",
            prompt="Think hard.",
            model="claude-opus-4-6",
        )
        agent_def = spec_to_claude(spec)
        assert agent_def.model == "claude-opus-4-6"

    def test_alias_still_passes_through(self) -> None:
        from lup.adapters.clients.claude.translate import spec_to_claude

        spec = SubagentSpec(
            name="quick",
            description="Quick worker",
            prompt="Be fast.",
            model="haiku",
        )
        assert spec_to_claude(spec).model == "haiku"


# ---------------------------------------------------------------------------
# Fix #5 — PostToolUse tool_response reaches LupHookInput.tool_result
# ---------------------------------------------------------------------------


class TestToolResultRelay:
    async def test_post_tool_use_response_populates_tool_result(self) -> None:
        from claude_agent_sdk.types import HookContext, PostToolUseHookInput

        from lup.adapters.clients.claude.hooks import build_claude_hook_handler
        from lup.hooks import LupHookInput, LupHookMatcher, LupHookOutput

        seen: dict[str, str] = {}

        async def capture(inp: LupHookInput) -> LupHookOutput:
            seen["tool_result"] = inp.tool_result or "<missing>"
            return LupHookOutput()

        handler = build_claude_hook_handler(
            LupHookMatcher(hook=capture), event="PostToolUse"
        )
        hook_input = cast(
            PostToolUseHookInput,
            {
                "session_id": "s",
                "transcript_path": "/t",
                "cwd": "/c",
                "agent_id": "a",
                "agent_type": "main",
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "/x"},
                "tool_response": {"stdout": "file body"},
                "tool_use_id": "tu_1",
            },
        )
        await handler(hook_input, "tu_1", cast(HookContext, object()))

        assert "file body" in seen["tool_result"]


# ---------------------------------------------------------------------------
# Fix #10 — session metadata targets newest-by-timestamp file
# ---------------------------------------------------------------------------


class TestLatestSessionByTimestamp:
    @pytest.fixture
    def isolated_root(self, tmp_path: Path) -> Iterator[Path]:
        from lup.workspace.paths import configure, project_root

        original = project_root()
        configure(root=tmp_path, version="0.10.0")
        yield tmp_path
        configure(root=original)

    def test_metadata_follows_timestamp_not_lexical_path(
        self, isolated_root: Path
    ) -> None:
        import json

        from lup.workspace.history import update_session_metadata

        traces = isolated_root / "notes" / "traces"

        # 0.9.0 sorts lexically AFTER 0.10.0 (the old bug picked it), yet it
        # is the OLDER session. The newest session lives under 0.10.0.
        older = traces / "0.9.0" / "sessions" / "s" / "20240101_000000.json"
        newer = traces / "0.10.0" / "sessions" / "s" / "20240601_000000.json"
        for path, ts in (
            (older, "2024-01-01T00:00:00"),
            (newer, "2024-06-01T00:00:00"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"timestamp": ts}), encoding="utf-8")

        assert update_session_metadata("s", outcome="success") is True

        newer_data = json.loads(newer.read_text(encoding="utf-8"))
        older_data = json.loads(older.read_text(encoding="utf-8"))
        assert newer_data.get("outcome") == "success"
        assert "outcome" not in older_data


# ---------------------------------------------------------------------------
# Fix #11 — guard rejects spec fields the target engine cannot honor
# ---------------------------------------------------------------------------


class TestSubagentMaxTurnsGuard:
    async def test_max_turns_on_non_claude_rejected_loudly(self) -> None:
        spec = SubagentSpec(
            name="gpt-worker",
            description="Runs on GPT",
            prompt="Work.",
            model="gpt-5.5",
            max_turns=4,
        )
        tool = create_run_subagent_tool([spec], default_model="claude-sonnet-4-6")

        result = cast(
            ToolResponse, await tool.handler({"name": "gpt-worker", "task": "go"})
        )
        assert result.get("is_error") is True
        message = response_text(result)
        assert "max_turns" in message

    async def test_claude_spec_with_max_turns_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import lup.subagents
        from lup.types import LupResponse

        captured: dict[str, JsonValue] = {}

        class FakeClient:
            async def query(self, prompt: str, **_kwargs: JsonValue) -> LupResponse:
                return LupResponse(blocks=[LupTextBlock(text="ok")])

        def fake_create_client(**kwargs: JsonValue) -> FakeClient:
            captured.update(kwargs)
            return FakeClient()

        monkeypatch.setattr(lup.subagents, "create_client", fake_create_client)
        spec = SubagentSpec(
            name="claude-worker",
            description="Runs on Claude",
            prompt="Work.",
            model="haiku",
            max_turns=4,
        )
        tool = create_run_subagent_tool([spec], default_model="claude-sonnet-4-6")

        result = cast(
            ToolResponse, await tool.handler({"name": "claude-worker", "task": "go"})
        )
        assert result.get("is_error", False) is False
        assert captured["max_turns"] == 4


# ---------------------------------------------------------------------------
# Fix #8 — Codex custom-provider override format
# ---------------------------------------------------------------------------


class TestOpenAICompatProviderConfig:
    def make_native_options(self) -> LupAgentOptions:
        return LupAgentOptions(
            model="glm-4-7b",
            system_prompt="test",
            base_url="http://localhost:8000/v1",
            api_key="secret-key",
        )

    def test_provider_defined_under_plural_table(self) -> None:
        native = build_openai_compat_native(self.make_native_options())
        overrides = native.config_overrides
        pid = OPENAI_COMPAT_PROVIDER_ID

        # Provider definition lives in the plural model_providers.<id> table.
        assert f'model_providers.{pid}.base_url="http://localhost:8000/v1"' in overrides
        # API key is referenced by env-var NAME via env_key, never inline.
        assert (
            f'model_providers.{pid}.env_key="{OPENAI_COMPAT_API_KEY_ENV}"' in overrides
        )
        # The top-level model_provider string selects the provider.
        assert f'model_provider="{pid}"' in overrides

    def test_no_literal_api_key_and_no_singular_table(self) -> None:
        native = build_openai_compat_native(self.make_native_options())
        joined = "\n".join(native.config_overrides)

        # The old broken format wrote the literal key under a singular,
        # hardcoded-id table. Neither must reappear.
        assert "api_key" not in joined
        assert "model_provider.openai_compat" not in joined
        # And the literal secret never lands in a config override.
        assert "secret-key" not in joined

    def test_api_key_injected_into_subprocess_env(self) -> None:
        native = build_openai_compat_native(self.make_native_options())
        assert native.env == {OPENAI_COMPAT_API_KEY_ENV: "secret-key"}

    def test_explicit_provider_id_names_the_table(self) -> None:
        opts = self.make_native_options().model_copy(
            update={"model_provider": "my_proxy"}
        )
        native = build_openai_compat_native(opts)
        overrides = native.config_overrides

        # A caller-supplied id names both the selector and the definition
        # table; base_url is the signal to define the provider.
        assert 'model_provider="my_proxy"' in overrides
        assert (
            'model_providers.my_proxy.base_url="http://localhost:8000/v1"' in overrides
        )
        assert native.env == {OPENAI_COMPAT_API_KEY_ENV: "secret-key"}

    def test_no_overrides_without_base_url(self) -> None:
        native = build_openai_compat_native(
            LupAgentOptions(model="llama-3.1-8b", system_prompt="test")
        )
        assert not any("model_provider" in o for o in native.config_overrides)

    def test_inherits_mcp_config_from_codex_base(self) -> None:
        native = build_openai_compat_native(
            LupAgentOptions(
                model="glm-4-7b",
                system_prompt="test",
                base_url="http://localhost:8000/v1",
                served_tool_groups=["notes", "sandbox"],
                serve_tools_command=["uv", "run", "lup-devtools"],
            )
        )
        assert any("mcp_servers.notes" in o for o in native.config_overrides)
