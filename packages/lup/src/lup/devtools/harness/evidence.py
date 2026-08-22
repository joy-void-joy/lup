"""Typed native-evidence ledger backing the doctor's version-drift trigger.

`docs/native-capabilities.md` records the CLI and SDK versions each native
contract was last probed against. This module is the machine-readable row set
behind that prose: `lup-devtools harness doctor` compares the *installed*
versions against these accepted ones and surfaces a drift warning whenever an
installed component is newer — the trigger to re-probe the native contracts
and refresh the ledger. Locally the drift is a warning; the nightly lane runs
doctor with `--strict-evidence`, turning drift into a nonzero exit so evidence
re-probes have a schedule instead of a habit.
"""

import hashlib
from pathlib import Path

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_package_version

from pydantic import BaseModel, Field

# lup: ignore[constant-declaration] — the date this evidence was last read from
# the vendors, which is a fact about the reading rather than a value to pick
EVIDENCE_REFRESHED = "2026-08-20"


class EvidenceEntry(BaseModel, frozen=True):
    """One accepted contract version, keyed by its probe capability name."""

    capability: str
    version: str


EVIDENCE_LEDGER = [
    EvidenceEntry(capability="claude-cli", version="2.1.237"),
    EvidenceEntry(capability="claude-agent-sdk", version="0.2.89"),
    EvidenceEntry(capability="codex-cli", version="0.148.0"),
]


def accepted_version(capability: str, ledger: list[EvidenceEntry] | None = None) -> str:
    """The version one capability was last probed against.

    Prose naming a version asks for it here rather than spelling it, so the
    ledger the doctor compares against and the ledger the page publishes are
    the same three rows. Raises for a capability no row accepts, because a
    page naming one is a typo rather than a runtime condition.
    """
    entries = EVIDENCE_LEDGER if ledger is None else ledger
    for entry in entries:
        if entry.capability == capability:
            return entry.version
    raise KeyError(f"no evidence row accepts a version for {capability!r}")


def cited_fixture(root: Path, path: str) -> str:
    """A fixture path the ledger cites, refused when it resolves to nothing.

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
        sha256="18e546303ecfe878b179a50da73e6fb99f634be4bc3f7650d5870f31787079b2",
    ),
    SchemaDigest(
        path="v2/TurnStartParams.json",
        sha256="95f35a9f01beea390cc4e478b4030e46ef37e5d769438d50f40b7aeabbf1ad74",
    ),
    SchemaDigest(
        path="v2/ThreadResumeParams.json",
        sha256="f0ffd32fbe09750f27d1c27d7e815db7389167dba4e4b438c8411095cdff5d92",
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
"""The app-server schemas whose shape the typed Codex models were read from."""


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

    @property
    def message(self) -> str:
        return (
            f"{self.capability} {self.installed} is newer than the evidence "
            f"ledger's {self.accepted} (refreshed {EVIDENCE_REFRESHED}); re-probe "
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

    @property
    def message(self) -> str:
        return (
            f"{self.path} hashes to {self.found}, not the accepted "
            f"{self.accepted} (refreshed {EVIDENCE_REFRESHED}); review the "
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
    accepted = SCHEMA_DIGESTS if digests is None else digests
    drifts = []  # lup: ignore[empty-collection]
    for digest in accepted:
        target = generated / digest.path
        payload = target.read_bytes() if target.is_file() else b""
        found = hashlib.sha256(payload).hexdigest()
        if found != digest.sha256:
            drifts.append(
                DigestDrift(path=digest.path, found=found, accepted=digest.sha256)
            )
    return drifts


def evidence_drift(
    capability: str,
    version_text: str,
    ledger: list[EvidenceEntry] | None = None,
) -> EvidenceDrift | None:
    """Report drift when an installed component is newer than its evidence row."""
    entries = EVIDENCE_LEDGER if ledger is None else ledger
    accepted = next(
        (entry for entry in entries if entry.capability == capability), None
    )
    if accepted is None:
        return None
    installed = parse_version(version_text)
    expected = parse_version(accepted.version)
    if installed is None or expected is None:
        return None
    if not newer_than(installed, expected):
        return None
    return EvidenceDrift(
        capability=capability,
        installed=".".join(str(part) for part in installed),
        accepted=accepted.version,
    )


def sdk_evidence_drift(
    ledger: list[EvidenceEntry] | None = None,
) -> EvidenceDrift | None:
    """Compare the installed Claude Agent SDK package against its evidence row."""
    try:
        installed = installed_package_version("claude-agent-sdk")
    except PackageNotFoundError:
        return None
    return evidence_drift("claude-agent-sdk", installed, ledger)
