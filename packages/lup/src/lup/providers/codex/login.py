"""Codex's own words for where it keeps a login.

A leaf on purpose: the harness declaration, the account-home sync, and the
profile transform all need these spellings, and none of them should pull the
session runtime in to get them.
"""

from lup.providers.login import ProviderLogin

# lup: ignore[constant-declaration] — the environment variable Codex reads
CODEX_HOME = "CODEX_HOME"

CODEX_LOGIN = ProviderLogin(
    config_home_env=CODEX_HOME,
    credentials_file="auth.json",
    home_subdir="codex-home",
)
"""Where Codex stores a completed login, and how to select one.

No renewal test, because the file states no deadline to read one from: it holds
``auth_mode``, the three tokens, an account id and ``last_refresh``, which
records when a renewal last happened rather than when renewing stops working.
The `id_token` is a JWT and does carry an `exp`, and using it would be worse
than declaring nothing — that claim is the id token's own hour, so every launch
past the first would read a perfectly good login as dead and re-seed over it.

So Codex keeps the behaviour every runtime had before the field existed: a
stored login is replaced only when there is none. The cost is the one this
field exists to remove — a Codex config home whose login has aged out asks for
a sign-in the container cannot finish — and the way out of it is the fallback
the launch prints, until Codex publishes a deadline worth reading.
"""
