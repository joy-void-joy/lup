"""Claude Code's own words for where it keeps a login.

A leaf on purpose: the harness declaration, the usage reader, and the profile
transform all need these spellings, and none of them should pull the session
runtime in to get them.
"""

from lup.providers.login import ProviderLogin

# lup: ignore[constant-declaration] — the environment variable Claude Code reads
CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR"

CLAUDE_LOGIN = ProviderLogin(
    config_home_env=CLAUDE_CONFIG_DIR,
    credentials_file=".credentials.json",
    renewable=(
        '(.claudeAiOauth.refreshToken // "") != ""'
        " and .claudeAiOauth.refreshTokenExpiresAt > (now * 1000)"
    ),
    home_subdir="claude-config",
)
"""Where Claude Code stores a completed login, and how to select one.

The file carries two deadlines and the renewal test reads the second.
``claudeAiOauth.expiresAt`` is the access token's, hours away and renewed
without anyone asking; ``refreshTokenExpiresAt`` is the refresh token's, weeks
away, and once it passes there is nothing left to renew with. `jq` states the
comparison in seconds and the file in milliseconds, which is what the factor of
a thousand reconciles.

The deadline is necessary and not sufficient, so the filter asks for the
credential before it asks how long the credential has. A logout, or a refresh
the server refuses, empties both token strings and leaves every other member
of the object untouched -- a file that is a login by every test reading only
the date, and inert by the one test that decides whether a request is
answered. Read as renewable it suppresses the seed, and the session it
suppresses it for opens demanding the one flow a contained session cannot
finish.
"""
