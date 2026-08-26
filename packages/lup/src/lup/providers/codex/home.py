"""Stable per-worktree Codex homes for locally installed harness plugins."""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

import jwt
import tomlkit
from pydantic import BaseModel, ValidationError

from lup.providers.codex.harness_runtime import CodexPluginInstaller, PluginCacheConfig
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.marketplace import CodexMarketplace
from lup.providers.codex.theme import claude_daltonized_theme
from lup.types import EnvVars
from lup.workspace.paths import declared_project_root, project_root


logger = logging.getLogger(__name__)


DEFAULT_ACCOUNT_HOME = Path.home() / ".codex"
SCOPED_HOME_DIR = Path(".lup") / "codex-home"
"""Where a checkout keeps the Codex home its own sessions run under.

Relative, and resolved against the checkout rather than against anything of
the operator's. An absolute path handed here would resolve to itself for
every worktree, which is the shared root this replaced.

The directory holds a copy of the account credential, so a checkout that has
opened a session is credential-bearing. `.lup/` is ignored, so git will not
carry it; anything reading the tree without consulting git — an archive, a
build context, an editor index — reads the credential along with the code.
"""
# lup: ignore[constant-declaration] — the keys Codex writes its own state under
CODEX_CONFIG_STATE_KEYS = ("marketplaces", "plugins")

# lup: ignore[constant-declaration] — Codex's own spelling for where a home
# records which checkouts it will read the configuration of
PROJECTS_KEY = "projects"

# lup: ignore[constant-declaration] — Codex's own word for that decision; a
# caller given it to set would be writing a record the runtime cannot read
TRUSTED_PROJECT = "trusted"
"""How a home records that it will read one checkout's own configuration."""

# lup: ignore[constant-declaration] — Codex's own plugin layout, and the same
# spelling it writes into a trust record; a caller given it to set would be
# naming a file the runtime looks for somewhere else
HOOKS_MANIFEST = Path("hooks/hooks.json")
"""Where a plugin declares its hooks, and how a trust record names that file."""

type CodexHookEvent = Literal["PreToolUse", "PostToolUse", "PermissionRequest"]
"""Every event a hook manifest may declare, as the manifest spells it."""

# lup: ignore[constant-declaration] — each value is Codex's own spelling for the
# event beside it, over a vocabulary the manifest closes
CODEX_HOOK_EVENTS: dict[CodexHookEvent, str] = {
    "PreToolUse": "pre_tool_use",
    "PostToolUse": "post_tool_use",
    "PermissionRequest": "permission_request",
}
"""What Codex calls each declared event where it records trust for one.

The manifest spells an event one way and the trust record another, and the
two have to be matched to ask whether a declared hook is trusted. A table
rather than a transformation, so an event added to the manifest and unknown
here is refused rather than quietly read as needing no trust."""


class CodexHomeSelection(BaseModel, frozen=True):
    """The Codex home selected for one harness launch."""

    path: Path
    isolated: bool


class CodexAccessClaims(BaseModel, extra="ignore"):
    """The one claim this adapter reads out of an access token."""

    exp: datetime | None = None


class CodexTokens(BaseModel, extra="ignore"):
    """The issued tokens, of which only the access token is ever read."""

    access_token: str = ""


class CodexCredential(BaseModel, extra="ignore"):
    """The parts of a Codex auth record this adapter reasons about.

    Extra keys are ignored, and the access token is read for one purpose: the
    issuer states its own expiry inside it, which beats inferring a lifetime
    this project would have to guess at. Nothing here logs or reproduces a
    token, and records move between homes as whole files.
    """

    last_refresh: datetime | None = None
    tokens: CodexTokens = CodexTokens()

    def expires_at(self) -> datetime | None:
        """When the issuer says this access token stops being accepted."""
        if not self.tokens.access_token:
            return None
        try:
            claims = jwt.decode(
                self.tokens.access_token,
                options={"verify_signature": False},
            )
        except jwt.PyJWTError:
            return None
        return CodexAccessClaims.model_validate(claims).exp


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


def read_credential(path: Path) -> CodexCredential | None:
    """Read one auth record, or None when it is absent or unreadable."""
    if not path.is_file():
        return None
    try:
        return CodexCredential.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError:
        logger.warning("Codex credential at %s is unreadable; leaving it alone", path)
        return None


def credential_refreshed_at(path: Path) -> datetime | None:
    """Read when a credential last rotated, or None when that is unknowable."""
    credential = read_credential(path)
    return None if credential is None else credential.last_refresh


def sync_credential(source: Path, target: Path) -> bool:
    """Copy a credential toward the side that is provably out of date.

    A Codex login is one rotating chain, not a file: the runtime refreshes it
    in place under whichever home it runs, and a rotation spends the refresh
    token every other copy still holds. Copying once and diverging therefore
    hands stale homes a credential that cannot even refresh itself, so the
    account home is the record and each launch converges against it.

    Without two readable timestamps there is no proof of which side is
    current, so the target is preserved rather than guessed at.
    """
    if not source.is_file():
        return False
    if not target.exists():
        shutil.copy2(source, target)
        return True
    source_refreshed = credential_refreshed_at(source)
    target_refreshed = credential_refreshed_at(target)
    if source_refreshed is None or target_refreshed is None:
        return False
    if source_refreshed <= target_refreshed:
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


def trust_project(home: Path, worktree: Path) -> bool:
    """Record that a scoped home trusts the checkout it was made for.

    The runtime reads a project's own ``.codex/config.toml`` only for a
    project its home trusts, and says nothing at all when it declines to.
    That file is where a generated tree declares its tool servers, so a first
    session in a fresh home opens with every one of them silently absent —
    the config written, never read, and a session with no instruments looking
    exactly like one that had none to declare. The same shape
    :func:`sanitized_codex_config` keeps hook trust for, and the same reason.

    Nothing is granted that was not already: the launch generated that file
    from this repository's own declaration moments earlier, and trusting what
    we just wrote is not a decision about anybody's code. Only ever in a home
    this project made for this checkout — an operator's own home carries
    their own decisions, and those are not ours to write.
    """
    config = home / "config.toml"
    document = (
        tomlkit.parse(config.read_text(encoding="utf-8"))
        if config.is_file()
        else tomlkit.document()
    )
    projects = document.setdefault(PROJECTS_KEY, tomlkit.table(is_super_table=True))
    named = str(worktree.expanduser().resolve())
    if named in projects:
        return False
    entry = tomlkit.table()
    entry["trust_level"] = TRUSTED_PROJECT
    projects[named] = entry
    config.write_text(tomlkit.dumps(document), encoding="utf-8")
    return True


class CodexLoginState(BaseModel, frozen=True):
    """Whether a home holds a login, and when the issuer stops accepting it."""

    present: bool
    expires_at: datetime | None = None

    def usable_at(self, moment: datetime) -> bool:
        """A login is usable until the issuer's own expiry passes.

        An unreadable record, or one whose token states no expiry, is taken as
        usable: the runtime is the authority on a shape this cannot read, and
        guessing the other way would send someone to a sign-in they may not
        need.
        """
        return self.present and (self.expires_at is None or moment < self.expires_at)


def login_state(home: Path) -> CodexLoginState:
    """Read the login one Codex home would start a session with."""
    credential = read_credential(home / CODEX_LOGIN.credentials_file)
    if credential is None:
        return CodexLoginState(present=False)
    return CodexLoginState(present=True, expires_at=credential.expires_at())


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
        scoped_dir: Path = SCOPED_HOME_DIR,
    ) -> None:
        self.account_home = account_home
        self.scoped_dir = scoped_dir

    def home_for(self, worktree: Path) -> Path:
        """The home belonging to the checkout that encloses one worktree.

        Inside the checkout, because a project's own state is the project's.
        A checkout is already distinct from every other one, which is what
        retires the path digest a root shared across projects needed to tell
        two of them apart — and a worktree named below the root answers with
        the root's home rather than opening a second one beneath itself.

        A worktree enclosed by no declared project answers for itself. There
        is no project to hold the home, and the alternative is reaching back
        outside the tree for somewhere to put it.
        """
        canonical = worktree.expanduser().resolve()
        return (declared_project_root(canonical) or canonical) / self.scoped_dir

    def prepare(self, worktree: Path, profile: str | None = None) -> Path:
        """Refresh Lup-owned files and seed account files into a scoped home."""
        scoped_home = self.home_for(worktree)
        scoped_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        scoped_home.chmod(0o700)
        claude_daltonized_theme().write(scoped_home)
        sync_credential(
            self.account_home / CODEX_LOGIN.credentials_file,
            scoped_home / CODEX_LOGIN.credentials_file,
        )
        seed_config(self.account_home / "config.toml", scoped_home / "config.toml")
        trust_project(scoped_home, worktree)
        if profile is not None:
            filename = profile_config_filename(profile)
            seed_config(self.account_home / filename, scoped_home / filename)
        return scoped_home

    def publish(self, worktree: Path) -> bool:
        """Return a credential the session rotated back to the account home."""
        scoped_home = self.home_for(worktree)
        return sync_credential(
            scoped_home / CODEX_LOGIN.credentials_file,
            self.account_home / CODEX_LOGIN.credentials_file,
        )


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
    if CODEX_LOGIN.config_home_env in environment:
        return CodexHomeSelection(
            path=Path(environment[CODEX_LOGIN.config_home_env]),
            isolated=False,
        )
    active_store = store or CodexWorktreeHomeStore()
    return CodexHomeSelection(
        path=active_store.prepare(worktree, profile),
        isolated=True,
    )


class CodexPolicyUntrusted(RuntimeError):
    """A home carries the policy plugin and would run none of its hooks."""


def declared_hook_records(marketplace: CodexMarketplace) -> list[str]:
    """Every trust record Codex keeps for the hooks this plugin declares.

    A record is named for the plugin, the manifest it was read from, the
    event, and the hook's place within it — so the names can be constructed
    from the manifest rather than read back out of Codex's own state and
    taken apart, which would be reading a spelling this does not own.
    """
    manifest = marketplace.source / HOOKS_MANIFEST
    if not manifest.is_file():
        return []
    declared = json.loads(manifest.read_text(encoding="utf-8"))["hooks"]
    unknown = [event for event in declared if event not in CODEX_HOOK_EVENTS]
    if unknown:
        raise ValueError(
            f"{manifest} declares hook events this cannot ask about: {unknown}. "
            "Add each to CODEX_HOOK_EVENTS with the name Codex records it under"
        )
    return [
        f"{marketplace.selector}:{HOOKS_MANIFEST.as_posix()}:{spelled}:{group}:{index}"
        for event, spelled in CODEX_HOOK_EVENTS.items()
        if event in declared
        for group, matched in enumerate(declared[event])
        for index in range(len(matched["hooks"]))
    ]


def untrusted_hooks(home: Path, marketplace: CodexMarketplace) -> list[str]:
    """Which of this plugin's declared hooks the home would not actually run.

    Codex trusts a hook per event and per hash, and *skips* one it does not
    trust rather than refusing it — so a home carrying the plugin, enabled,
    with trust recorded for one event of three runs every session past the
    two it never granted, and says nothing.

    Presence and enablement are what can be asked here. A recorded hash that
    has since gone stale is not: computing it would mean reimplementing a
    digest this does not own, and getting that wrong refuses every session
    over a hook that is fine. Codex skips a stale hook exactly as it skips an
    absent one, so what is left uncovered is a hook whose trust was granted
    and whose body has since been regenerated.
    """
    config = home / "config.toml"
    if not config.is_file():
        return declared_hook_records(marketplace)
    document = tomlkit.parse(config.read_text(encoding="utf-8"))
    hooks = document["hooks"] if "hooks" in document else {}
    state = hooks["state"] if "state" in hooks else {}
    return [
        record
        for record in declared_hook_records(marketplace)
        if record not in state
        or ("enabled" in state[record] and not state[record]["enabled"])
    ]


def install_declared_policy(
    home: Path, root: Path | None = None
) -> CodexMarketplace | None:
    """Install the project's own plugin into one home, and say which it was.

    The half ``sanitized_codex_config`` promises and nothing performed for a
    session. Stripping account-wide plugin state is right — a scoped home
    should install its own against a verified digest — but a home that then
    installs nothing carries no dispatcher, and every refusal the project
    declares goes unenforced with nothing saying so.

    Failure is raised rather than warned past. A session that opened without
    the policy it was meant to run under is indistinguishable from one running
    under it, which is the property that made this worth finding.

    Installing it is not the whole of carrying it, which is why the trust is
    read here too. Trust is a decision about a hook, and only a person makes
    one: this refuses a session the decision was never made for rather than
    recording it on their behalf, because a trust granted by the thing being
    trusted is not one. The decision is made in an interactive session, which
    is where Codex asks — and which does not come through here, so refusing
    cannot close the door on its own remedy.
    """
    project = root or project_root()
    declared = CodexMarketplace.declared(project)
    if declared is None:
        return None
    installer = CodexPluginInstaller(
        PluginCacheConfig(
            codex_home=home, marketplace=declared.name, plugin=declared.plugin
        )
    )
    installer.ensure(declared.source, project)
    skipped = untrusted_hooks(home, declared)
    if skipped:
        raise CodexPolicyUntrusted(
            f"{home} carries {declared.selector} and would run none of "
            f"{len(skipped)} declared hook(s): {', '.join(skipped)}. Codex skips "
            "a hook it does not trust rather than refusing it, so this session "
            "would run ungoverned and read exactly like one that is governed. "
            "Open an interactive session in this checkout and trust the plugin "
            "there, which is where Codex asks."
        )
    return declared
