"""Setup dashboard behavior over the shared declarative registry."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from lup_template.devtools import setup
from lup_template.devtools.dashboard.app import DashboardState, create_dashboard


@pytest.fixture
def isolated_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the dashboard against an isolated env file."""
    monkeypatch.setattr(setup, "ENV_LOCAL", tmp_path / ".env.local")


async def test_dashboard_serves_packaged_wizard(isolated_dashboard: None) -> None:
    del isolated_dashboard
    async with AsyncClient(
        transport=ASGITransport(app=create_dashboard()), base_url="http://dashboard"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "Project setup" in response.text
    assert "Configured integrations" in response.text


async def test_dashboard_projects_cli_registry_status(
    isolated_dashboard: None,
) -> None:
    del isolated_dashboard
    async with AsyncClient(
        transport=ASGITransport(app=create_dashboard()), base_url="http://dashboard"
    ) as client:
        response = await client.get("/api/setup")
    state = DashboardState.model_validate(response.json())

    assert response.status_code == 200
    assert state.total == len(setup.INTEGRATIONS)
    assert {item.command for item in state.integrations} == {
        item.command for item in setup.INTEGRATIONS
    }
    assert next(
        item for item in state.integrations if item.command == "google"
    ).mode == ("cli")


async def test_dashboard_writes_only_declared_integration_fields(
    isolated_dashboard: None,
) -> None:
    del isolated_dashboard
    async with AsyncClient(
        transport=ASGITransport(app=create_dashboard()), base_url="http://dashboard"
    ) as client:
        response = await client.put(
            "/api/setup/api-key",
            json={"values": {"EXAMPLE_API_KEY": "configured-secret"}},
        )
    state = DashboardState.model_validate(response.json())

    assert response.status_code == 200
    assert setup.read_env_local() == {"EXAMPLE_API_KEY": "configured-secret"}
    assert next(
        item for item in state.integrations if item.command == "api-key"
    ).configured


async def test_dashboard_rejects_cross_integration_and_bespoke_writes(
    isolated_dashboard: None,
) -> None:
    del isolated_dashboard
    async with AsyncClient(
        transport=ASGITransport(app=create_dashboard()), base_url="http://dashboard"
    ) as client:
        cross_integration = await client.put(
            "/api/setup/api-key",
            json={"values": {"NOTION_TOKEN": "wrong-surface"}},
        )
        bespoke = await client.put(
            "/api/setup/google",
            json={"values": {"GMAIL_CREDENTIALS_PATH": "credentials/google.json"}},
        )

    assert cross_integration.status_code == 400
    assert bespoke.status_code == 409
    assert setup.read_env_local() == {}
