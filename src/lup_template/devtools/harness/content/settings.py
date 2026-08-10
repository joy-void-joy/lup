"""Typed project-owned Claude settings declaration."""

from urllib.parse import urlsplit

from lup.harness.models import HookSet, HookUrlScope, Plugin
from lup.types import JsonObject, JsonValue

OFFICIAL_PLUGINS: dict[str, JsonValue] = {
    "agent-sdk-dev@claude-plugins-official": True,
    "claude-md-management@claude-plugins-official": True,
    "github@claude-plugins-official": True,
}

SETTINGS: JsonObject = {
    "coauthorship": False,
    "enabledPlugins": OFFICIAL_PLUGINS,
    "env": {"ENABLE_TOOL_SEARCH": "false"},
    "fileSuggestion": {
        "command": ".claude/plugins/lup/scripts/file_suggest.sh",
        "type": "command",
    },
}

ALLOWED: list[JsonValue] = [
    "WebSearch",
    "Skill(lup:hooks)",
    # The guidance sends every change through a worktree, so entering and
    # leaving one is the first thing a session does and the last. Asking
    # about the step the workflow mandates is asking whether to follow it.
    # Neither tool writes: `EnterWorktree` moves this session into a tree
    # `dev worktree create` already made, and `ExitWorktree` only removes one
    # when asked to, which is its own question.
    "EnterWorktree",
    "ExitWorktree",
    "Read(./.claude/settings.json.local*)",
    "Read(./sync.json.local)",
    "Read(./downstream.json.local)",
]

DENIED: list[JsonValue] = [
    "Read(./**/.env*.local)",
    "Read(./**/.env.local)",
    "Read(./**/secrets*.local)",
    "Read(./**/*.secret.local)",
]


def served_tool_grants(plugin: Plugin) -> list[JsonValue]:
    """Grant every tool the plugin's own servers serve.

    A declared server is this project's own code, wired in deliberately, so
    asking per call would make the declaration a suggestion. A new group in
    the toolsets registry is granted by being declared, with nothing here to
    extend.

    The scoped name is what a runtime addresses a plugin's server by; the bare
    key it is declared under matches nothing.
    """
    return [f"mcp__plugin_{plugin.name}_{server.name}" for server in plugin.mcp_servers]


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


def project_settings(plugin: Plugin | None) -> JsonObject:
    """Render the settings artifact, deriving both blocks from the declaration.

    The sandbox stays permissive where the semantic policy already judges
    (allowUnsandboxedCommands defaults on, so escapes re-enter the deny
    lattice) and hardens what shell writers could otherwise bypass:
    human-owned files become OS-level write denials and the declared
    credential paths become sandbox read denials.
    """
    settings: JsonObject = dict(SETTINGS)
    if plugin is not None:
        # Marketplace names share one global namespace, so this must be the
        # per-project name the declaration carries. A literal here would
        # register every adopter under one key, and whichever repo installed
        # last would serve its plugin to all of them.
        settings["extraKnownMarketplaces"] = {
            str(plugin.marketplace): {
                "source": {"path": "./.claude/plugins", "source": "directory"}
            }
        }
        settings["enabledPlugins"] = {
            **OFFICIAL_PLUGINS,
            f"{plugin.name}@{plugin.marketplace}": True,
        }
    settings["permissions"] = {
        "allow": [*ALLOWED, *(served_tool_grants(plugin) if plugin else [])],
        "deny": DENIED,
    }
    hooks = plugin.hooks if plugin is not None else None
    if hooks is None or hooks.sandbox is None:
        return settings
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
    settings["sandbox"] = sandbox_block
    return settings
