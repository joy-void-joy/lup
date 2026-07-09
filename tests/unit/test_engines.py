"""Engine construction: translation, refusal, dropping, and routing.

The engines are the only seam, and construction never connects — so
everything each engine does with neutral options is pinned offline here:
what it translates (the Claude harness shape), what it refuses
(``UnsupportedOptionsError`` under the session policy), what it drops
(the ``query()`` policy), and how ``create_client`` routes and guards its
two forms.
"""

import claude_agent_sdk as claude
import pytest

from lup.adapters.clients.claude.create import create_claude
from lup.adapters.clients.claude.translate import SESSION_THINKING_TOKENS
from lup.adapters.clients.claude.sessions import ClaudeSessions
from lup.adapters.clients.claude.compat import create_claude_compat
from lup.adapters.clients.Client import Client
from lup.adapters.clients.codex.create import create_codex
from lup.adapters.clients.codex.sessions import CodexSessions
from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.clients.codex.usage import per_mtok_usage_cost
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.codex.compat import create_openai_compat
from lup.adapters.clients.sessions.budget import BudgetedSessions
from lup.adapters.clients.sessions.timeout import TimeoutSessions
from lup.adapters.errors import UnsupportedOptionsError
from lup.adapters.options import LupAgentOptions
from lup.adapters.tools.names import WEB_SEARCH
from lup.adapters.tools.codex import COMMAND_EXECUTION, FILE_CHANGE
from lup.adapters.wiring import (
    ENGINES,
    create_client,
    engine_for_model,
    query,
    resolve_engine,
)
from lup.mcp import create_mcp_server
from lup.types import SubagentSpec
from tests.unit.conftest import RecordingEngine


def engine_for(model: str) -> str:
    """The engine id a model name routes to — through the model router."""
    return engine_for_model(model).id


def claude_native(client: Client) -> claude.ClaudeAgentOptions:
    """The translated SDK options a composed Claude client carries."""
    assert isinstance(client, ComposedClient)
    sessions = client.sessions
    assert isinstance(sessions, ClaudeSessions)
    return sessions.options


def codex_native(client: Client) -> CodexNativeConfig:
    """The translated native config a composed Codex client carries.

    Unwraps the governance the recipe may have composed on (budget,
    timeout) down to the engine's own sessions.
    """
    assert isinstance(client, ComposedClient)
    sessions = client.sessions
    while isinstance(sessions, BudgetedSessions | TimeoutSessions):
        sessions = sessions.inner
    assert isinstance(sessions, CodexSessions)
    return sessions.native


class TestEngineResolution:
    def test_model_prefixes_route_to_engines(self) -> None:
        assert engine_for("claude-opus-4-6") == "claude"
        assert engine_for("opus") == "claude"
        assert engine_for("gpt-5.5") == "codex"
        assert engine_for("codex-mini") == "codex"
        assert engine_for("glm-4") == "openai-compat"
        assert engine_for("llama-3-70b") == "openai-compat"

    def test_unknown_engine_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown engine"):
            resolve_engine("gemini")

    def test_engine_instance_passes_through(self) -> None:
        engine = RecordingEngine()
        assert resolve_engine(engine) is engine

    def test_every_shipped_id_resolves(self) -> None:
        for engine_id in ("claude", "codex", "openai-compat", "claude-compat"):
            assert resolve_engine(engine_id).id == engine_id


class TestClaudeEngine:
    def test_session_grade_translation(self) -> None:
        """A persisting session takes the preset and the engine policy defaults."""
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            system_prompt="be good",
            coding_harness_preset=True,
            tool_servers={"notes": create_mcp_server("notes", tools=[])},
            subagents=[SubagentSpec(name="r", description="d", prompt="p")],
            allowed_tools=["Read"],
            max_turns=7,
            reasoning_effort="high",
        )
        native = claude_native(create_claude(opts))
        assert native.system_prompt == {
            "type": "preset",
            "preset": "claude_code",
            "append": "be good",
        }
        assert native.max_thinking_tokens == SESSION_THINKING_TOKENS
        assert native.permission_mode == "bypassPermissions"
        assert native.extra_args == {}
        assert native.max_turns == 7
        assert native.effort == "high"
        assert native.sandbox is not None
        # The in-process server became an SDK ``sdk`` server, not passed raw.
        assert isinstance(native.mcp_servers, dict)
        assert native.mcp_servers["notes"].get("type") == "sdk"
        assert native.agents is not None and "r" in native.agents

    def test_call_tier_translation(self) -> None:
        """A nested one-shot: raw prompt, SDK defaults, structured output."""
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            system_prompt="be brief",
            coding_harness_preset=False,
            sdk_sandbox=False,
            persist_session=False,
            session_defaults=False,
            output_schema={"type": "object"},
            tools=["Read"],
            max_budget_usd=2.0,
        )
        native = claude_native(create_claude(opts))
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
        opts = LupAgentOptions(model="claude-opus-4-6", coding_harness_preset=False)
        assert claude_native(create_claude(opts)).system_prompt is None

    def test_preset_and_session_defaults_are_independent(self) -> None:
        """The preset wraps the prompt; the policy defaults follow session_defaults.

        ``coding_harness_preset`` controls only the prompt shape, so a run can
        wrap the prompt without taking the session defaults (``session_defaults``
        off), and take the defaults without the preset — the two are orthogonal.
        """
        preset_only = claude_native(
            create_claude(
                LupAgentOptions(
                    model="claude-opus-4-6",
                    system_prompt="hi",
                    coding_harness_preset=True,
                    session_defaults=False,
                )
            )
        )
        assert preset_only.system_prompt == {
            "type": "preset",
            "preset": "claude_code",
            "append": "hi",
        }
        assert preset_only.max_thinking_tokens is None
        assert preset_only.permission_mode is None

        session_only = claude_native(
            create_claude(
                LupAgentOptions(
                    model="claude-opus-4-6",
                    system_prompt="hi",
                    coding_harness_preset=False,
                    session_defaults=True,
                )
            )
        )
        assert session_only.system_prompt == "hi"
        assert session_only.max_thinking_tokens == SESSION_THINKING_TOKENS
        assert session_only.permission_mode == "bypassPermissions"

    def test_explicit_intent_knobs_win_over_session_defaults(self) -> None:
        """A session honors explicit thinking/permission over the engine default."""
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            session_defaults=True,
            max_thinking_tokens=4096,
            permission_mode="plan",
        )
        native = claude_native(create_claude(opts))
        assert native.max_thinking_tokens == 4096
        assert native.permission_mode == "plan"

    def test_persistence_and_session_defaults_are_independent(self) -> None:
        """persist_session (SDK persistence) and session_defaults (engine
        behavior defaults) are orthogonal knobs, not one bundled bool."""
        # Persist the SDK session but decline the session-grade defaults.
        persist_no_defaults = claude_native(
            create_claude(
                LupAgentOptions(
                    model="claude-opus-4-6",
                    persist_session=True,
                    session_defaults=False,
                )
            )
        )
        assert persist_no_defaults.max_thinking_tokens is None
        assert persist_no_defaults.permission_mode is None
        assert "no-session-persistence" not in persist_no_defaults.extra_args

        # Take the session-grade defaults on a non-persisting call.
        defaults_no_persist = claude_native(
            create_claude(
                LupAgentOptions(
                    model="claude-opus-4-6",
                    persist_session=False,
                    session_defaults=True,
                )
            )
        )
        assert defaults_no_persist.max_thinking_tokens == SESSION_THINKING_TOKENS
        assert defaults_no_persist.permission_mode == "bypassPermissions"
        assert defaults_no_persist.extra_args == {"no-session-persistence": None}

    def test_turn_timeout_refused_on_sessions(self) -> None:
        opts = LupAgentOptions(model="claude-opus-4-6", turn_timeout_seconds=30.0)
        with pytest.raises(UnsupportedOptionsError) as exc:
            create_claude(opts)
        assert exc.value.fields == ["turn_timeout_seconds"]

    def test_turn_timeout_dropped_under_query_policy(self) -> None:
        opts = LupAgentOptions(
            model="claude-opus-4-6",
            turn_timeout_seconds=30.0,
            on_unsupported="drop",
        )
        assert isinstance(create_claude(opts), ComposedClient)


def compat_env(opts: LupAgentOptions) -> dict[str, str]:
    """The SDK subprocess environment the claude-compat engine builds."""
    return claude_native(create_claude_compat(opts)).env


class TestClaudeCompatEngine:
    def test_env_points_the_sdk_at_the_endpoint(self) -> None:
        opts = LupAgentOptions(
            model="glm-4",
            coding_harness_preset=True,
            base_url="http://local:8000",
            api_key="k",
        )
        native = claude_native(create_claude_compat(opts))
        env = native.env
        assert env["ANTHROPIC_BASE_URL"] == "http://local:8000"
        # Default auth_style is bearer; the x-api-key header is blanked so an
        # ambient Anthropic key can't leak to the endpoint.
        assert env["ANTHROPIC_AUTH_TOKEN"] == "k"
        assert env["ANTHROPIC_API_KEY"] == ""
        # The scaffolding shape is inherited from the claude engine.
        assert native.permission_mode == "bypassPermissions"

    def test_api_key_auth_style_uses_the_native_header(self) -> None:
        opts = LupAgentOptions(
            model="glm-4",
            base_url="http://local:8000",
            api_key="k",
            auth_style="api_key",
        )
        env = compat_env(opts)
        assert env["ANTHROPIC_API_KEY"] == "k"
        assert env["ANTHROPIC_AUTH_TOKEN"] == ""

    def test_missing_key_still_supplies_a_placeholder_credential(self) -> None:
        opts = LupAgentOptions(model="glm-4", base_url="http://local:8000")
        env = compat_env(opts)
        assert env["ANTHROPIC_AUTH_TOKEN"]
        assert env["ANTHROPIC_API_KEY"] == ""

    def test_single_model_endpoint_maps_every_claude_alias(self) -> None:
        opts = LupAgentOptions(model="glm-4", base_url="http://local:8000")
        env = compat_env(opts)
        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-4"
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "glm-4"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "glm-4"

    def test_multi_model_gateway_leaves_aliases_untouched(self) -> None:
        opts = LupAgentOptions(
            model="glm-4",
            base_url="http://gateway:8000",
            map_model_aliases=False,
        )
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in compat_env(opts)

    def test_nonessential_traffic_is_silenced(self) -> None:
        opts = LupAgentOptions(model="glm-4", base_url="http://local:8000")
        env = compat_env(opts)
        assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
        assert env["DISABLE_TELEMETRY"] == "1"
        assert env["DISABLE_ERROR_REPORTING"] == "1"
        assert env["DISABLE_BUG_COMMAND"] == "1"

    def test_missing_base_url_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            create_claude_compat(LupAgentOptions(model="glm-4"))


class TestCodexEngine:
    def test_session_translation(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            system_prompt="do it",
            served_tool_groups=["notes", "sandbox"],
            reasoning_effort="high",
            turn_timeout_seconds=120.0,
        )
        client = create_codex(opts)
        native = codex_native(client)
        overrides = native.config_overrides
        assert any(o.startswith("mcp_servers.notes.") for o in overrides)
        assert any(o.startswith("mcp_servers.sandbox.") for o in overrides)
        assert native.effort == "high"
        assert native.turn_timeout_seconds == 120.0
        assert client.mailbox is None
        # The recipe composed the wall clock the runtime lacks.
        assert isinstance(client, ComposedClient)
        assert isinstance(client.sessions, TimeoutSessions)

    def test_call_tier_serves_no_tools(self) -> None:
        native = codex_native(create_codex(LupAgentOptions(model="gpt-5.5")))
        assert not any(o.startswith("mcp_servers.") for o in native.config_overrides)

    def test_intent_knobs_refused_on_sessions(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            max_turns=3,
            max_thinking_tokens=1024,
            permission_mode="plan",
            tools=["Read"],
        )
        with pytest.raises(UnsupportedOptionsError) as exc:
            create_codex(opts)
        assert exc.value.fields == [
            "max_thinking_tokens",
            "max_turns",
            "permission_mode",
            "tools",
        ]

    def test_builtin_table_names_activity_while_tools_knob_stays_refused(
        self,
    ) -> None:
        """Naming and selectability are separate facts: the engine names what
        its builtin activity surfaces as, while the translation still refuses
        the ``tools`` knob that would restrict the set — even for a name
        straight from the table."""
        table = ENGINES["codex"].builtin_tools()
        assert {COMMAND_EXECUTION, FILE_CHANGE, WEB_SEARCH} <= table
        assert ENGINES["openai-compat"].builtin_tools() == table
        opts = LupAgentOptions(model="gpt-5.5", tools=[COMMAND_EXECUTION])
        with pytest.raises(UnsupportedOptionsError) as exc:
            create_codex(opts)
        assert exc.value.fields == ["tools"]

    def test_budget_without_rates_is_unsupported(self) -> None:
        opts = LupAgentOptions(model="gpt-5.5", max_budget_usd=1.0)
        with pytest.raises(UnsupportedOptionsError) as exc:
            create_codex(opts)
        assert exc.value.fields == ["max_budget_usd"]

    def test_budget_with_rates_is_kept(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            max_budget_usd=1.0,
            usage_cost=per_mtok_usage_cost(input_usd=1.0, output_usd=2.0),
        )
        client = create_codex(opts)
        assert codex_native(client).max_budget_usd == 1.0
        # The recipe composed cost metering — cumulative: Codex reports totals.
        assert isinstance(client, ComposedClient)
        assert isinstance(client.sessions, BudgetedSessions)
        assert client.sessions.cumulative

    def test_drop_policy_clears_and_builds(self) -> None:
        opts = LupAgentOptions(
            model="gpt-5.5",
            max_turns=3,
            max_budget_usd=1.0,
            on_unsupported="drop",
        )
        assert codex_native(create_codex(opts)).max_budget_usd is None


class TestOpenAICompatEngine:
    def test_provider_comes_from_compat(self) -> None:
        opts = LupAgentOptions(
            model="glm-4",
            base_url="http://local",
            model_provider="prov",
        )
        native = codex_native(create_openai_compat(opts))
        assert 'model_providers.prov.base_url="http://local"' in native.config_overrides
        assert native.model_provider == "prov"


class TestCreateClient:
    def test_kwargs_form_is_call_tier(self) -> None:
        engine = RecordingEngine()
        create_client(model="gpt-5.5", engine=engine)
        opts = engine.built[0]
        assert opts.coding_harness_preset is False
        assert opts.persist_session is False
        assert opts.sdk_sandbox is False

    def test_options_form_passes_through(self) -> None:
        engine = RecordingEngine()
        session_opts = LupAgentOptions(model="gpt-5.5")
        create_client(options=session_opts, engine=engine)
        assert engine.built[0] is session_opts

    def test_options_and_kwargs_are_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match="max_turns"):
            create_client(
                options=LupAgentOptions(model="gpt-5.5"),
                max_turns=3,
            )

    def test_model_or_options_required(self) -> None:
        with pytest.raises(ValueError, match="model"):
            create_client()

    def test_id_and_model_route_through_engines(self) -> None:
        """An engine id looks up ENGINES; ``None`` infers from the model."""
        engine = RecordingEngine()
        assert resolve_engine("codex") is ENGINES["codex"]
        assert resolve_engine(None, model="gpt-5.5") is ENGINES["codex"]
        assert resolve_engine(engine) is engine


class TestQuerySugar:
    async def test_query_runs_one_shot_with_drop_policy(self) -> None:
        engine = RecordingEngine()
        response = await query("hi", model="gpt-5.5", engine=engine, max_turns=3)

        assert response.text == "ok"
        ran = engine.ran[0]
        assert ran.on_unsupported == "drop"
        assert ran.max_turns == 3
        assert ran.coding_harness_preset is False
