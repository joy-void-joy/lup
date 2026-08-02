"""Typed project-owned Claude settings declaration."""

from urllib.parse import urlsplit

from lup.harness.models import HookSet, HookUrlScope
from lup.types import JsonObject, JsonValue

SETTINGS: JsonObject = {
    "coauthorship": False,
    "enabledPlugins": {
        "agent-sdk-dev@claude-plugins-official": True,
        "claude-md-management@claude-plugins-official": True,
        "github@claude-plugins-official": True,
        "lup@lup-template": True,
        "pyright-lsp@claude-plugins-official": True,
    },
    "env": {"ENABLE_TOOL_SEARCH": "false"},
    "extraKnownMarketplaces": {
        "lup-template": {"source": {"path": "./.claude/plugins", "source": "directory"}}
    },
    "fileSuggestion": {
        "command": ".claude/plugins/lup/scripts/file_suggest.sh",
        "type": "command",
    },
    "permissions": {
        "allow": [
            "WebSearch",
            "Skill(lup:hooks)",
            "Read(./.claude/settings.json.local*)",
            "Read(./sync.json.local)",
            "Read(./downstream.json.local)",
        ],
        "deny": [
            "Read(./**/.env*.local)",
            "Read(./**/.env.local)",
            "Read(./**/secrets*.local)",
            "Read(./**/*.secret.local)",
        ],
    },
}


def allowed_network_domains(hooks: HookSet) -> list[str]:
    """Collect fetch-scope hostnames and declared extras, first-seen order.

    A scope that includes subdomains contributes both its apex host and the
    ``*.host`` wildcard, so the OS boundary admits exactly what the semantic
    fetch policy already allows.
    """
    if hooks.sandbox is None:
        return []

    def sandbox_domains(scope: HookUrlScope) -> list[str]:
        host = urlsplit(str(scope.origin)).hostname
        if host is None:
            return []
        return [host, f"*.{host}"] if scope.include_subdomains else [host]

    merged = [
        domain for scope in hooks.allowed_fetch for domain in sandbox_domains(scope)
    ]
    merged.extend(hooks.sandbox.extra_domains)
    return list(dict.fromkeys(merged))


def project_settings(hooks: HookSet | None) -> JsonObject:
    """Render the settings artifact, deriving the sandbox block from hooks.

    The sandbox stays permissive where the semantic policy already judges
    (allowUnsandboxedCommands defaults on, so escapes re-enter the deny
    lattice) and hardens what shell writers could otherwise bypass:
    human-owned files become OS-level write denials and the declared
    credential paths become sandbox read denials.
    """
    if hooks is None or hooks.sandbox is None:
        return dict(SETTINGS)
    domains: list[JsonValue] = list(allowed_network_domains(hooks))
    sandbox_block: JsonObject = {
        "enabled": True,
        "network": {"allowedDomains": domains},
        "filesystem": {
            "denyWrite": [path.as_posix() for path in hooks.human_owned_files],
            "allowWrite": list(hooks.sandbox.writable_paths),
        },
        "credentials": {
            "files": [
                {"path": path, "mode": "deny"}
                for path in hooks.sandbox.credential_paths
            ]
        },
    }
    settings: JsonObject = dict(SETTINGS)
    settings["sandbox"] = sandbox_block
    return settings
