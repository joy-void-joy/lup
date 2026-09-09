"""Typed native-evidence register backing the doctor's version-drift trigger.

`docs/native-capabilities.md` records the CLI and SDK versions each native
contract was last probed against. This module is the machine-readable row set
behind that prose: `lup-devtools harness doctor` compares the *installed*
versions against these accepted ones and surfaces a drift warning whenever an
installed component is newer — the trigger to re-probe the native contracts
and refresh the register. Locally the drift is a warning; the nightly lane runs
doctor with `--strict-evidence`, turning drift into a nonzero exit so evidence
re-probes have a schedule instead of a habit.
"""

import hashlib
from pathlib import Path

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_package_version

from pydantic import BaseModel, Field


class EvidenceEntry(BaseModel, frozen=True):
    """One accepted contract version, keyed by its probe capability name.

    The date is per row rather than one date over the register. A probe reaches
    one vendor at a time — a Codex contract can be re-read while nothing new
    was asked of Claude — and a single date moved by whichever probe ran last
    claims a reading of the two that did not happen.
    """

    capability: str
    version: str
    refreshed: str
    """When this row's contract was last read from the vendor."""


EVIDENCE_REGISTER = [
    EvidenceEntry(capability="claude-cli", version="2.1.237", refreshed="2026-08-20"),
    EvidenceEntry(
        capability="claude-agent-sdk", version="0.2.89", refreshed="2026-08-20"
    ),
    EvidenceEntry(capability="codex-cli", version="0.153.4", refreshed="2026-09-07"),
]


def accepted(
    capability: str, register: list[EvidenceEntry] | None = None
) -> EvidenceEntry:
    """The row one capability's evidence was last accepted under.

    Prose naming a version or a reading date asks for it here rather than
    spelling it, so the register the doctor compares against and the register the
    page publishes are the same three rows. Raises for a capability no row
    accepts, because a page naming one is a typo rather than a runtime
    condition.
    """
    entries = EVIDENCE_REGISTER if register is None else register
    for entry in entries:
        if entry.capability == capability:
            return entry
    raise KeyError(f"no evidence row accepts a version for {capability!r}")


def cited_fixture(root: Path, path: str) -> str:
    """A fixture path the register cites, refused when it resolves to nothing.

    Naming a file as evidence is a claim about the tree, and prose cannot
    check it: a suite that moves leaves the citation reading exactly as it
    did while pointing at nothing, which is how this page came to cite an
    adapter-runtime fixture after it had moved into the library's own suite.
    Asking here fails generation instead, naming the citation to repoint.
    """
    if not (root / path).exists():
        raise ValueError(
            f"{path!r} is cited as evidence but does not exist beneath {root}: "
            "point the citation at where the fixtures moved, or drop the claim"
        )
    return path


class SchemaDigest(BaseModel, frozen=True):
    """One app-server schema file, and the content this evidence accepted.

    A digest recorded only in prose is a claim nothing can fail, which is how
    all five of these came to describe schemas the CLI had already changed.
    Held here, the same rows the page publishes are the rows a probe compares
    a regenerated schema against.
    """

    path: str
    """Where the file lands under the generator's output directory."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


SCHEMA_DIGESTS = [
    SchemaDigest(
        path="v2/ThreadStartParams.json",
        sha256="25f490368ec6df52a2a3b82a5469d2413307eb93439121b309f415b5648eee7a",
    ),
    SchemaDigest(
        path="v2/TurnStartParams.json",
        sha256="b36fb37326b1cf69f75c8b306f1f886d53a57c4b1b985e08e298e2407ea2ad02",
    ),
    SchemaDigest(
        path="v2/ThreadResumeParams.json",
        sha256="324e96004c49de35935cade3386958431c93a4fd3997a839f9796772ea4c8072",
    ),
    SchemaDigest(
        path="DynamicToolCallParams.json",
        sha256="401bba20cfbd95762bef0467d840430c46be53369093ad9f26425ba757e34efc",
    ),
    SchemaDigest(
        path="DynamicToolCallResponse.json",
        sha256="abb082cad67f11fcc98ba75f2eff75d7d1723af0c657655329b83ff160451a02",
    ),
]
"""The app-server schemas whose shape the typed Codex models were read from.

Dated by the ``codex-cli`` row, which is what regenerates them: a digest here
was read out of the same CLI that row accepts, so a drift message names that
row's reading rather than a date of its own.
"""


class SchemaCommand(BaseModel, frozen=True):
    """What regenerates the files :data:`SCHEMA_DIGESTS` accepts.

    Held as the executable and its arguments rather than as one line, so the
    prose a page prints and the argv a probe runs are the same declaration
    read two ways instead of one being split back out of the other.
    """

    executable: str
    arguments: list[str]

    def spelled(self, target: str) -> str:
        """This command as a reader would type it, writing into ``target``."""
        return " ".join([self.executable, *self.arguments, target])


SCHEMA_COMMAND = SchemaCommand(
    executable="codex",
    arguments=["app-server", "generate-json-schema", "--experimental", "--out"],
)


class EvidenceDrift(BaseModel, frozen=True):
    """One installed component that is newer than its accepted evidence."""

    capability: str
    installed: str
    accepted: str
    refreshed: str

    @property
    def message(self) -> str:
        return (
            f"{self.capability} {self.installed} is newer than the evidence "
            f"register's {self.accepted} (refreshed {self.refreshed}); re-probe "
            "the native contracts and update docs/native-capabilities.md"
        )


def parse_version(text: str) -> list[int] | None:
    """Extract the first dotted-numeric version from a CLI banner or metadata."""
    for token in text.split():
        parts = token.split(".")  # lup: ignore[string-split] — dotted version token
        if len(parts) >= 2 and all(part.isdigit() for part in parts):
            return [int(part) for part in parts]
    return None


def newer_than(installed: list[int], accepted: list[int]) -> bool:
    """Compare versions componentwise, padding the shorter with zeros."""
    width = max(len(installed), len(accepted))
    left = installed + [0] * (width - len(installed))
    right = accepted + [0] * (width - len(accepted))
    return left > right


class DigestDrift(BaseModel, frozen=True):
    """One regenerated schema whose content differs from its accepted digest."""

    path: str
    found: str
    accepted: str
    refreshed: str

    @property
    def message(self) -> str:
        return (
            f"{self.path} hashes to {self.found}, not the accepted "
            f"{self.accepted} (refreshed {self.refreshed}); review the "
            "change against the typed app-server models before accepting it"
        )


def digest_drift(
    generated: Path, digests: list[SchemaDigest] | None = None
) -> list[DigestDrift]:
    """Compare schemas regenerated into ``generated`` against what was accepted.

    A file the generator no longer writes drifts to the empty digest rather
    than being skipped: a schema that disappeared is exactly the change this
    is here to surface, and a silent pass would report it as agreement.
    """
    expected = SCHEMA_DIGESTS if digests is None else digests
    refreshed = accepted("codex-cli").refreshed
    drifts = []  # lup: ignore[empty-collection]
    for digest in expected:
        target = generated / digest.path
        payload = target.read_bytes() if target.is_file() else b""
        found = hashlib.sha256(payload).hexdigest()
        if found != digest.sha256:
            drifts.append(
                DigestDrift(
                    path=digest.path,
                    found=found,
                    accepted=digest.sha256,
                    refreshed=refreshed,
                )
            )
    return drifts


def evidence_drift(
    capability: str,
    version_text: str,
    register: list[EvidenceEntry] | None = None,
) -> EvidenceDrift | None:
    """Report drift when an installed component is newer than its evidence row."""
    entries = EVIDENCE_REGISTER if register is None else register
    row = next((entry for entry in entries if entry.capability == capability), None)
    if row is None:
        return None
    installed = parse_version(version_text)
    expected = parse_version(row.version)
    if installed is None or expected is None:
        return None
    if not newer_than(installed, expected):
        return None
    return EvidenceDrift(
        capability=capability,
        installed=".".join(str(part) for part in installed),
        accepted=row.version,
        refreshed=row.refreshed,
    )


def sdk_evidence_drift(
    register: list[EvidenceEntry] | None = None,
) -> EvidenceDrift | None:
    """Compare the installed Claude Agent SDK package against its evidence row."""
    try:
        installed = installed_package_version("claude-agent-sdk")
    except PackageNotFoundError:
        return None
    return evidence_drift("claude-agent-sdk", installed, register)
