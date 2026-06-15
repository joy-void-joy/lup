"""Display Claude Code usage from the live API.

Calls the /api/oauth/usage endpoint for real-time utilization data
and supplements with stats-cache.json for daily detail.

Anthropic-only by nature: it reads Claude Code OAuth credentials and an
Anthropic endpoint. There is no Codex/OpenAI equivalent (the Codex
runtime exposes no usage API) — for per-session cost and token usage on
any backend, read the session JSON (``trace list`` shows the backend;
Codex cost needs ``CODEX_USD_PER_MTOK_*`` rates).

Examples::

    $ uv run lup-devtools claude usage
    $ uv run lup-devtools claude usage --no-watch
    $ uv run lup-devtools claude usage --no-detail
    $ uv run lup-devtools claude usage --watch --interval 300
"""
