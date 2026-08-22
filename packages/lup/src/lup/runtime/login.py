"""Where a runtime keeps a stored login, and how to point it at one.

An application that spawns a provider CLI under a chosen account needs facts no
other portable contract carries: the environment variable selecting a
configuration home, the file the runtime writes a completed login into, and how
to tell a login that is merely stale from one nothing can renew. Each is a word
only the provider gets to choose, so each adapter declares its own and every
consumer above holds this value instead of spelling any of them.

The value is a transparent carrier — it composes no seam and decides nothing,
so an application stores one the way it stores the runtime's name.
"""

from pathlib import Path

from pydantic import BaseModel

from lup.types import EnvVars


class ProviderLogin(BaseModel, frozen=True):
    """One runtime's stored-login location, in that runtime's own words."""

    config_home_env: str
    """Environment variable pointing this runtime's CLI at a config home."""

    credentials_file: str
    """What this runtime writes a completed login into, inside that home."""

    renewable: str = ""
    """A jq filter answering whether a stored login can still reach an account.

    Not whether its access token is current — that expires hourly and renews
    itself, and a consumer acting on it would churn a working login. What this
    asks is whether renewal is still possible at all, because once it is not,
    the file is inert: no request it makes will be answered, and the only way
    back is a fresh sign-in. That distinction is the whole value of the field,
    and it is why the filter reads the refresh credential's life rather than
    the access token's.

    The word is the runtime's own, like the others here. A runtime whose
    stored login states no such deadline declares nothing here, and an empty
    filter means "cannot be asked" rather than "expired" — every consumer
    treats a login it cannot interrogate as one to leave alone.
    """

    home_subdir: str
    """Subdirectory this runtime's configuration home takes inside a profile.

    A project keeping its accounts as directories gives each one a directory
    and each runtime a place inside it, so one name can hold a login for every
    runtime that name runs. The word is the runtime's own, for the same reason
    the two above are: naming it anywhere else would decide for one provider in
    a module every provider passes through.
    """

    def environment(self, home: Path) -> EnvVars:
        """The environment routing a spawned CLI at that configuration home."""
        return {self.config_home_env: str(home)}

    def credentials_path(self, home: Path) -> Path:
        """Where a completed login sits inside that configuration home."""
        return home / self.credentials_file

    def logged_in(self, home: Path) -> bool:
        """Whether that configuration home already holds a completed login."""
        return self.credentials_path(home).exists()
