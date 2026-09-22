"""Move a selected configuration layer without moving a home's installed state."""

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Self

import tomlkit
from pydantic import BaseModel, Field, TypeAdapter
from tomlkit.exceptions import ParseError

from lup.providers.codex.app_server import CodexAppServer
from lup.providers.codex.home import profile_config_filename
from lup.providers.codex.harness_runtime import codex_home_lock
from lup.providers.login import NativeHomeScope
from lup.types import JsonObject, JsonValue


class CodexConfigurationOrigin(BaseModel, extra="ignore"):
    """Native discriminator naming the owner of one configuration layer."""

    type: str


class CodexConfigurationLayer(BaseModel, extra="ignore"):
    """The native user layer after Codex resolves its path-valued settings."""

    name: CodexConfigurationOrigin
    config: JsonObject


class CodexConfigurationRead(BaseModel, extra="ignore"):
    """Only native layers are transported; defaults and project state stay local."""

    layers: list[CodexConfigurationLayer]


class CodexHookSettings(BaseModel, extra="allow"):
    """Hook events are extensible; persisted trust is owned by the destination."""

    state: JsonObject | None = None

    def personal(self) -> JsonObject:
        """Keep event declarations while omitting persisted hook trust."""
        return TypeAdapter[JsonObject](JsonObject).validate_python(
            self.model_dump(exclude={"state"})
        )


class CodexConfigurationState(BaseModel, extra="ignore"):
    """Only the nested owned state needs decoding from an open native config."""

    hooks: CodexHookSettings | None = None


class CodexProfileSettings(BaseModel, frozen=True):
    """A selected profile and the personal settings it inherits, without trust."""

    name: str | None
    source_home: Path
    source_user_home: Path = Field(default_factory=Path.home)
    settings: JsonObject = Field(repr=False)
    as_base: bool = False

    @classmethod
    def capture(cls, home: Path, profile: str | None, as_base: bool = False) -> Self:
        """Snapshot base and selected profile settings without exposing parse values."""

        def overlay(base: JsonObject, values: JsonObject) -> JsonObject:
            merged = dict(base)
            for key, value in values.items():
                previous = merged.get(key)
                merged[key] = (
                    overlay(previous, value)
                    if isinstance(previous, dict) and isinstance(value, dict)
                    else value
                )
            return merged

        def read(path: Path) -> JsonObject:
            document = tomlkit.parse(path.read_text(encoding="utf-8"))
            return TypeAdapter[JsonObject](JsonObject).validate_python(
                document.unwrap()
            )

        try:
            base = home / "config.toml"
            settings = overlay(
                read(base) if base.is_file() else {},
                read(home / profile_config_filename(profile))
                if profile is not None
                else {},
            )
            snapshot = cls(
                name=profile,
                source_home=home.resolve(),
                settings=settings,
                as_base=as_base,
            )
            return snapshot.model_copy(
                update={"settings": snapshot.personal_settings()}
            )
        except (OSError, ValueError, ParseError):
            raise ValueError(
                "Cannot read the selected Codex profile; check its name and TOML settings."
            ) from None

    def personal_settings(self, enforce_policy: bool = False) -> JsonObject:
        """Leave native installation/trust local and retain required policy hooks."""
        settings = self.model_copy(deep=True).settings
        for key in ("marketplaces", "plugins", "projects"):
            settings.pop(key, None)
        state = CodexConfigurationState.model_validate(settings)
        if state.hooks is not None:
            settings["hooks"] = state.hooks.personal()
        if enforce_policy:
            features = settings.setdefault("features", {})
            if not isinstance(features, dict):
                raise ValueError("Codex features must be a settings table")
            features["hooks"] = True
        return settings

    def digest(self) -> str:
        """Configuration identity independent of TOML table ordering."""
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def installed_name(self) -> str:
        """An immutable profile name so simultaneous launches cannot replace it."""
        return f"lup-{self.digest()}"

    def state_scope(self) -> NativeHomeScope:
        """A stable volume for this exact selected base and authentication context."""
        return NativeHomeScope(key=f"codex-{self.digest()}")

    async def normalized(
        self, staging: Path, enforce_policy: bool = False
    ) -> JsonObject:
        """Let the native parser identify paths, then retain their source-home origin."""
        settings = self.personal_settings(enforce_policy)
        # Codex reads these dependencies during configuration loading, before
        # config/read can return the path-normalized user layer.
        for key in (
            "model_instructions_file",
            "model_catalog_json",
            "experimental_compact_prompt_file",
        ):
            value = settings.get(key)
            if isinstance(value, str):
                path = Path(value)
                if path.is_relative_to("~"):
                    path = self.source_user_home / path.relative_to("~")
                settings[key] = str(
                    path if path.is_absolute() else self.source_home / path
                )
        (staging / "config.toml").write_text(tomlkit.dumps(settings), encoding="utf-8")
        server = CodexAppServer(
            Path("codex"),
            environment={
                "CODEX_HOME": str(staging),
                "HOME": str(self.source_user_home),
            },
        )
        try:
            async with asyncio.timeout(20):
                await server.start()
                reported = CodexConfigurationRead.model_validate(
                    await server.request(
                        "config/read", {"includeLayers": True, "cwd": str(staging)}
                    )
                )
        finally:
            await server.close()

        def located(value: JsonValue) -> JsonValue:
            match value:
                case dict():
                    return {key: located(item) for key, item in value.items()}
                case list():
                    return [located(item) for item in value]
                case str() if Path(value).is_relative_to(staging):
                    return str(self.source_home / Path(value).relative_to(staging))
                case _:
                    return value

        for layer in reported.layers:
            if layer.name.type == "user":
                return {key: located(value) for key, value in layer.config.items()}
        raise ValueError("Codex reported no user configuration layer")

    def install(self, home: Path, enforce_policy: bool = False) -> None:
        """Materialize selected settings while preserving native installation/trust.

        Base placement belongs to a home partitioned by :meth:`state_scope`;
        profile placement leaves the destination base settings untouched.
        """
        try:
            if self.name is not None:
                profile_config_filename(self.name)
            home.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".lup-profile-", dir=home
            ) as temporary:
                settings = asyncio.run(self.normalized(Path(temporary), enforce_policy))
                destination = home / (
                    "config.toml"
                    if self.as_base
                    else profile_config_filename(self.installed_name())
                )
                with codex_home_lock(home):
                    existing = (
                        TypeAdapter[JsonObject](JsonObject).validate_python(
                            tomlkit.parse(
                                destination.read_text(encoding="utf-8")
                            ).unwrap()
                        )
                        if destination.exists()
                        else {}
                    )
                    if self.as_base:
                        for key in ("marketplaces", "plugins", "projects"):
                            if key in existing:
                                settings[key] = existing[key]
                        state = CodexConfigurationState.model_validate(existing)
                        if state.hooks is not None and state.hooks.state is not None:
                            selected_hooks = settings.setdefault("hooks", {})
                            if not isinstance(selected_hooks, dict):
                                raise ValueError("Codex hooks must be a settings table")
                            selected_hooks["state"] = state.hooks.state
                    if existing == settings and destination.exists():
                        return
                    if destination.exists() and not self.as_base:
                        raise ValueError(
                            "A prepared Codex profile changed unexpectedly"
                        )
                    prepared = Path(temporary) / "prepared.config.toml"
                    prepared.touch(mode=0o600)
                    prepared.write_text(tomlkit.dumps(settings), encoding="utf-8")
                    prepared.replace(destination)
        except Exception:
            # Native configuration errors can quote arbitrary values, including secrets.
            raise ValueError(
                "Cannot prepare the selected Codex profile; its settings were not logged. "
                "Check its TOML and use absolute, accessible paths for referenced files; "
                "contained launches require those paths to be mounted."
            ) from None
