"""Narrow typed importers for recognized project-native harness changes."""

import difflib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from lup.harness.models import CurrentArtifact, ReconciliationConflict
from lup_template.devtools.harness.native_overrides import (
    COMMAND_FRONTMATTER_OVERRIDES,
    CommandFrontmatterOverride,
)

OVERRIDES_PATH = Path("src/lup_template/devtools/harness/native_overrides.py")


class ImportResult(BaseModel):
    """One optional source patch and every change left as an explicit conflict."""

    model_config = ConfigDict(frozen=True)

    source_patch: str | None = None
    imported_paths: list[Path] = Field(default_factory=list)
    conflicts: list[ReconciliationConflict] = Field(default_factory=list)


class ParsedFrontmatter(BaseModel):
    """Flat, open-key native frontmatter and its uninterpreted body."""

    model_config = ConfigDict(frozen=True)

    fields: dict[str, str]  # lup: ignore[dict-str-payload] — native keys are open
    body: str


def split_frontmatter(content: str) -> ParsedFrontmatter:
    """Parse only flat scalar Markdown frontmatter without interpreting prose."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("native Markdown has no frontmatter")
    fields: dict[str, str] = {}  # lup: ignore[dict-str-payload, empty-collection]
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return ParsedFrontmatter(
                fields=fields,
                body="".join(lines[index + 1 :]),
            )
        trimmed = line.rstrip("\r\n")  # lup: ignore[string-strip]
        key, separator, value = trimmed.partition(":")  # lup: ignore[string-split]
        if not separator or not key or key in fields:
            raise ValueError("native frontmatter is not a flat unique mapping")
        fields[key] = value.lstrip()
    raise ValueError("native Markdown frontmatter is not terminated")


def render_overrides(
    overrides: dict[str, CommandFrontmatterOverride],
) -> str:
    """Render the complete small typed override catalog deterministically."""
    header = '''"""Typed project-owned imports of recognized native frontmatter changes."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommandFrontmatterOverride(BaseModel):
    """Recognized native metadata that has a portable semantic equivalent."""

    model_config = ConfigDict(frozen=True)

    description: str = Field(min_length=1, max_length=1024)

    @field_validator("description")
    @classmethod
    def scalar_description(cls, value: str) -> str:
        if "\\n" in value or "\\r" in value:
            raise ValueError("native frontmatter descriptions must be scalar")
        return value


COMMAND_FRONTMATTER_OVERRIDES: dict[str, CommandFrontmatterOverride] = {\n'''
    rows = [
        f"    {json.dumps(path)}: CommandFrontmatterOverride(\n"
        f"        description={json.dumps(override.description)},\n"
        "    ),\n"
        for path, override in sorted(overrides.items())
    ]
    return header + "".join(rows) + "}\n"


def git_source_patch(path: Path, before: str, after: str) -> str:
    """Create one git-apply-compatible patch for a repository source file."""
    if before == after:
        raise ValueError("source patch has no change")
    relative = path.as_posix()
    body = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )
    return f"diff --git a/{relative} b/{relative}\n{body}"


class ClaudeCommandFrontmatterImporter:
    """Import description-only command edits whose bodies are byte-identical."""

    def import_changes(
        self,
        root: Path,
        current: list[CurrentArtifact],
        desired: dict[Path, str],
    ) -> ImportResult:
        overrides = dict(COMMAND_FRONTMATTER_OVERRIDES)
        imported: list[Path] = []
        conflicts: list[ReconciliationConflict] = []
        for artifact in current:
            if artifact.category != "backpropagation_candidate":
                continue
            expected = desired.get(artifact.path)  # lup: ignore[dict-get]
            if expected is None:
                continue
            try:
                before = split_frontmatter(expected)
                after = split_frontmatter(artifact.content)
            except ValueError:
                conflicts.append(self.conflict(artifact))
                continue
            changed_keys = {
                key
                for key in before.fields.keys() | after.fields.keys()
                if before.fields.get(key)  # lup: ignore[dict-get] — open native keys
                != after.fields.get(key)  # lup: ignore[dict-get] — open native keys
            }
            if before.body != after.body or changed_keys != {"description"}:
                conflicts.append(self.conflict(artifact))
                continue
            description = (
                after.fields["description"] if "description" in after.fields else ""
            )
            override = CommandFrontmatterOverride(description=description)
            overrides[artifact.path.as_posix()] = override
            imported.append(artifact.path)
        if not imported:
            return ImportResult(conflicts=conflicts)
        source_path = root / OVERRIDES_PATH
        source_patch = git_source_patch(
            OVERRIDES_PATH,
            source_path.read_text(encoding="utf-8"),
            render_overrides(overrides),
        )
        return ImportResult(
            source_patch=source_patch,
            imported_paths=imported,
            conflicts=conflicts,
        )

    def conflict(self, artifact: CurrentArtifact) -> ReconciliationConflict:
        return ReconciliationConflict(
            path=artifact.path,
            category=artifact.category,
            message=(
                "only description-only command frontmatter edits with unchanged "
                "prompt bodies are importable"
            ),
        )
