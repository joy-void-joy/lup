"""Engine construction: translation, refusal, dropping, and routing.

The engines are the only seam, and construction never connects — so
everything each engine does with neutral options is pinned offline here:
what it translates (the Claude harness shape), what it refuses
(``UnsupportedOptionsError`` under the session policy), what it drops
(the ``query()`` policy), and how ``create_client`` routes and guards its
two forms.
"""

import pytest

from lup.adapters.claude import HARNESS_THINKING_TOKENS, ClaudeClient, ClaudeEngine
from lup.adapters.claude_compat import ClaudeCompatEngine
from lup.adapters.codex import CodexClient, CodexEngine, per_mtok_usage_cost
from lup.adapters.common import (
    UnsupportedOptionsError,
    create_client,
    engine_for_id,
    engine_id_for_model,
    query,
    resolve_engine,
)
from lup.adapters.openai_compat import OpenAICompatClient, OpenAICompatEngine
from lup.mcp import create_mcp_server
from lup.options import CompatOptions, LupAgentOptions
from lup.types import SubagentSpec
from tests.unit.conftest import RecordingEngine


class TestEngineResolution:
    def test_model_prefixes_route_to_engines(self) -> None:
        assert engine_id_for_model("claude-opus-4-6") == "claude"
        assert engine_id_for_model("opus") == "claude"
        assert engine_id_for_model("gpt-5.5") == "codex"
        assert engine_id_for_model("codex-mini") == "codex"
        assert engine_id_for_model("glm-4") == "openai-compat"
        assert engine_id_for_model("llama-3-70b") == "openai-compat"

    def test_unknown_engine_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown engine"):
            engine_for_id("gemini")

    def test_engine_instance_passes_through(self) -> None:
        engine = RecordingEngine()
        assert resolve_engine(engine) is engine

    def test_every_shipped_id_resolves(self) -> None:
        for engine_id in ("claude", "codex", "openai-compat", "claude-compat"):
            assert resolve_engine(engine_id).id == engine_id


class TestClaudeEngine:
    def test_session_grade_translation(self) -> None:
        """harness_prompt selects the preset and the harness policy defaults."""
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            system_prompt="be good",
            tool_servers={"notes": create_mcp_server("notes", tools=[])},
            subagents=[SubagentSpec(name="r", description="d", prompt="p")],
            allowed_tools=["Read"],
            max_turns=7,
            reasoning_effort="high",
            persist_session=False,
        )
        client = ClaudeEngine().client(opts)
        assert isinstance(client, ClaudeClient)
        native = client.options
        assert native.system_prompt == {
            "type": "preset",
            "preset": "claude_code",
            "append": "be good",
        }
        assert native.max_thinking_tokens == HARNESS_THINKING_TOKENS
        assert native.permission_mode == "bypassPermissions"
        assert native.extra_args == {"no-session-persistence": None}
        assert native.max_turns == 7
        assert native.effort == "high"
        assert native.sandbox is not None
        # The in-process server became an SDK ``sdk`` server, not passed raw.
        assert isinstance(native.mcp_servers, dict)
        assert native.mcp_servers["notes"].get("type") == "sdk"
        assert native.agents is not None and "r" in native.agents

    def test_call_tier_translation(self) -> None:
        """Without the harness: raw prompt, SDK defaults, structured output."""
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            system_prompt="be brief",
            harness_prompt=False,
            sdk_sandbox=False,
            persist_session=False,
            output_schema={"type": "object"},
            tools=["Read"],
            max_budget_usd=2.0,
        )
        client = ClaudeEngine().client(opts)
        assert isinstance(client, ClaudeClient)
        native = client.options
        assert native.system_prompt == "be brief"
        assert native.max_thinking_tokens is None
        assert native.permission_mode is None
        assert native.sandbox is None
        assert native.tools == ["Read"]
        assert native.max_budget_usd == 2.0
        assert native.output_format == {
            "type": "json_schema",
            "schema": {"type": "object"},
        }
        assert native.extra_args == {"no-session-persistence": None}

    def test_empty_raw_prompt_means_sdk_default(self) -> None:
        opts = LupAgentOptions(model="claude-opus-4-6", harness_prompt=False)
        client = ClaudeEngine().client(opts)
        assert isinstance(client, ClaudeClient)
        assert client.options.system_prompt is None

    def test_turn_timeout_refused_on_sessions(self) -> None:
        opts = LupAgentOptions(model="claude-opus-4-6", turn_timeout_seconds=30.0)
        with pytest.raises(UnsupportedOptionsError) as exc:
            ClaudeEngine().client(opts)
        assert exc.value.fields == ["turn_timeout_seconds"]

    def test_turn_timeout_dropped_under_query_policy(self) -> None:
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            turn_timeout_seconds=30.0,
            on_unsupported="drop",
        )
        client = ClaudeEngine().client(opts)
        assert isinstance(client, ClaudeClient)


class TestClaudeCompatEngine:
    def test_env_points_the_sdk_at_the_endpoint(self) -> None:
        opts = LupAgentOptions(
            model="glm-4",
            compat=CompatOptions(base_url="http://local:8000", api_key="k"),
        )
        client = ClaudeCompatEngine().client(opts)
        assert isinstance(client, ClaudeClient)
        assert client.options.env["ANTHROPIC_BASE_URL"] == "http://local:8000"
        assert client.options.env["ANTHROPIC_AUTH_TOKEN"] == "k"
        # The scaffolding shape is inherited from the claude engine.
        assert client.options.permission_mode == "bypassPermissions"

    def test_missing_base_url_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            ClaudeCompatEngine().client(LupAgentOptions(model="glm-4"))


class TestCodexEngine:
    def test_session_translation(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            system_prompt="do it",
            served_tool_groups=("notes", "sandbox"),
            reasoning_effort="high",
            turn_timeout_seconds=120.0,
        )
        client = CodexEngine().client(opts)
        assert isinstance(client, CodexClient)
        assert client.mcp_servers == ("notes", "sandbox")
        assert client.mcp_tools is True
        assert client.effort == "high"
        assert client.turn_timeout_seconds == 120.0
        assert client.mailbox is None

    def test_call_tier_serves_no_tools(self) -> None:
        client = CodexEngine().client(LupAgentOptions(model="gpt-5.5"))
        assert isinstance(client, CodexClient)
        assert client.mcp_tools is False

    def test_intent_knobs_refused_on_sessions(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            max_turns=3,
            max_thinking_tokens=1024,
            permission_mode="plan",
            tools=["Read"],
        )
        with pytest.raises(UnsupportedOptionsError) as exc:
            CodexEngine().client(opts)
        assert exc.value.fields == [
            "max_thinking_tokens",
            "max_turns",
            "permission_mode",
            "tools",
        ]

    def test_budget_without_rates_is_unsupported(self) -> None:
        opts = LupAgentOptions(model="gpt-5.5", max_budget_usd=1.0)
        with pytest.raises(UnsupportedOptionsError) as exc:
            CodexEngine().client(opts)
        assert exc.value.fields == ["max_budget_usd"]

    def test_budget_with_rates_is_kept(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            max_budget_usd=1.0,
            usage_cost=per_mtok_usage_cost(input_usd=1.0, output_usd=2.0),
        )
        client = CodexEngine().client(opts)
        assert isinstance(client, CodexClient)
        assert client.max_budget_usd == 1.0

    def test_drop_policy_clears_and_builds(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            max_turns=3,
            max_budget_usd=1.0,
            on_unsupported="drop",
        )
        client = CodexEngine().client(opts)
        assert isinstance(client, CodexClient)
        assert client.max_budget_usd is None


class TestOpenAICompatEngine:
    def test_provider_comes_from_compat(self) -> None:
        opts = LupAgentOptions(
            model="glm-4",
            compat=CompatOptions(base_url="http://local", model_provider="prov"),
        )
        client = OpenAICompatEngine().client(opts)
        assert isinstance(client, OpenAICompatClient)
        assert client.base_url == "http://local"
        assert client.model_provider == "prov"


class TestCreateClient:
    def test_kwargs_form_is_call_tier(self) -> None:
        engine = RecordingEngine()
        create_client(model="gpt-5.5", engine=engine)
        opts = engine.built[0]
        assert opts.harness_prompt is False
        assert opts.persist_session is False
        assert opts.sdk_sandbox is False

    def test_options_form_passes_through(self) -> None:
        engine = RecordingEngine()
        session_opts = LupAgentOptions(model="gpt-5.5")
        create_client(options=session_opts, engine=engine)
        assert engine.built[0] is session_opts
        assert engine.built[0].harness_prompt is True

    def test_options_and_kwargs_are_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match="max_turns"):
            create_client(
                options=LupAgentOptions(model="gpt-5.5"),
                max_turns=3,
            )

    def test_model_or_options_required(self) -> None:
        with pytest.raises(ValueError, match="model"):
            create_client()


class TestQuerySugar:
    async def test_query_runs_one_shot_with_drop_policy(self) -> None:
        engine = RecordingEngine()
        response = await query("hi", model="gpt-5.5", engine=engine, max_turns=3)

        assert response.text == "ok"
        ran = engine.ran[0]
        assert ran.on_unsupported == "drop"
        assert ran.max_turns == 3
        assert ran.harness_prompt is False
