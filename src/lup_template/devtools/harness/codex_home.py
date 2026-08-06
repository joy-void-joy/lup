"""Stable per-worktree Codex homes for locally installed harness plugins."""

import hashlib
import shutil
from pathlib import Path

import tomlkit
from pydantic import BaseModel, ConfigDict

from lup.types import EnvVars


DEFAULT_ACCOUNT_HOME = Path.home() / ".codex"
DEFAULT_SCOPED_ROOT = Path.home() / ".lup" / "codex" / "worktrees"
CODEX_CONFIG_STATE_KEYS = ("marketplaces", "plugins")


class CodexHomeSelection(BaseModel):
    """The Codex home selected for one harness launch."""

    model_config = ConfigDict(frozen=True)

    path: Path
    isolated: bool


def sanitized_codex_config(content: str) -> str:
    """Keep personal settings, including hook trust, without installed state.

    ``marketplaces`` and ``plugins`` record what one home has installed, and a
    scoped home installs its own against a verified digest — carrying them
    over would claim an install that never happened here.

    Hook trust is the opposite and is kept. The runtime refuses to run a
    plugin's hooks until they are reviewed, so a scoped home seeded without
    that decision installs the policy plugin and then runs ungoverned: the
    dispatcher is present, never consulted, and nothing says so. Seeding the
    operator's own trust is what makes a session here run under the policy
    they already granted — and only that, since a decision they never made is
    not in the file being copied.
    """
    document = tomlkit.parse(content)
    for key in CODEX_CONFIG_STATE_KEYS:
        if key in document:
            document.remove(key)
    return tomlkit.dumps(document)


def seed_file(source: Path, target: Path) -> bool:
    """Copy one account file only when the scoped home has no local copy."""
    if target.exists() or not source.is_file():
        return False
    shutil.copy2(source, target)
    return True


def seed_config(source: Path, target: Path) -> bool:
    """Seed one TOML settings file without account-wide plugin state."""
    if target.exists() or not source.is_file():
        return False
    target.write_text(
        sanitized_codex_config(source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    shutil.copymode(source, target)
    return True


def profile_config_filename(profile: str) -> str:
    """Render a Codex profile filename without permitting path traversal."""
    filename = Path(f"{profile}.config.toml")
    if filename.parent != Path("."):
        raise ValueError(f"invalid Codex profile name {profile!r}")
    return filename.name


class CodexWorktreeHomeStore:
    """Initialize persistent Lup-owned Codex homes from one personal account."""

    def __init__(
        self,
        account_home: Path = DEFAULT_ACCOUNT_HOME,
        scoped_root: Path = DEFAULT_SCOPED_ROOT,
    ) -> None:
        self.account_home = account_home
        self.scoped_root = scoped_root

    def home_for(self, worktree: Path) -> Path:
        """Derive a stable home from the canonical worktree path."""
        canonical = worktree.expanduser().resolve()
        digest = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()[:12]
        return self.scoped_root / f"{canonical.name}-{digest}"

    def prepare(self, worktree: Path, profile: str | None = None) -> Path:
        """Create a scoped home and seed account files on its first use."""
        scoped_home = self.home_for(worktree)
        scoped_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        scoped_home.chmod(0o700)
        seed_file(self.account_home / "auth.json", scoped_home / "auth.json")
        seed_config(self.account_home / "config.toml", scoped_home / "config.toml")
        if profile is not None:
            filename = profile_config_filename(profile)
            seed_config(self.account_home / filename, scoped_home / filename)
        return scoped_home


def select_codex_home(
    explicit_home: Path | None,
    environment: EnvVars,
    worktree: Path,
    profile: str | None = None,
    store: CodexWorktreeHomeStore | None = None,
) -> CodexHomeSelection:
    """Prefer explicit homes, otherwise prepare the worktree-scoped default."""
    if explicit_home is not None:
        return CodexHomeSelection(path=explicit_home, isolated=False)
    if "CODEX_HOME" in environment:
        return CodexHomeSelection(
            path=Path(environment["CODEX_HOME"]),
            isolated=False,
        )
    active_store = store or CodexWorktreeHomeStore()
    return CodexHomeSelection(
        path=active_store.prepare(worktree, profile),
        isolated=True,
    )
