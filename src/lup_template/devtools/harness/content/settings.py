"""Typed project-owned Claude settings declaration."""

from lup.types import JsonObject

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
