"""Runtime evidence doctor for installed native CLIs and SDKs.

Probes each selected composition's runtime readiness, prints the collected
evidence, and compares supported components against the accepted register in
``evidence`` — nonzero on missing capabilities, and on version drift under
``--strict-evidence``.
"""

import shutil
import tempfile
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.harness.evidence import (
    SCHEMA_COMMAND,
    ContractDrift,
    DigestDrift,
    EvidenceDrift,
    WireContract,
    contract_drift,
    digest_drift,
    evidence_drift,
    sdk_evidence_drift,
)
from lup.devtools.harness.generate import NativeHarnessComposition


class SchemaReading(BaseModel, frozen=True):
    """What one regeneration of the app-server schemas found, both checks.

    Both from one generation rather than two, because a second would be a
    second CLI invocation whose answer could differ — and a digest and a
    contract reported against different readings are two claims about no
    single version.
    """

    digests: list[DigestDrift] = []
    contracts: list[ContractDrift] = []

    def findings(self) -> list[str]:
        """Every finding in one order, as the doctor prints them."""
        return [drift.message for drift in [*self.digests, *self.contracts]]

    def drifted(self) -> bool:
        """Whether this reading found anything at all."""
        return bool(self.digests or self.contracts)


def schema_reading(contracts: list[WireContract]) -> SchemaReading:
    """Regenerate the app-server schemas and compare them to what was accepted.

    A CLI that cannot generate them reports nothing rather than a failure: the
    version probes already say codex is missing, and a second complaint about
    the same absence buries the changes this exists to surface.

    Two questions of one generation. The digests ask whether the shapes the
    typed models were read from have moved, which is a prompt to re-read them.
    The contract asks something narrower and worse: whether the reply Lup
    seeds hook trust from still carries the fields it reads. That one fails
    *open* — a renamed field leaves every hook resolving untrusted and the
    session running with its dispatcher present and never consulted — so it is
    asked here rather than discovered in a session that looked governed.
    """
    with tempfile.TemporaryDirectory() as directory:
        try:
            command = sh.Command(SCHEMA_COMMAND.executable)
            command(*SCHEMA_COMMAND.arguments, directory)
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            return SchemaReading()
        generated = Path(directory)
        return SchemaReading(
            digests=digest_drift(generated),
            contracts=contract_drift(generated, contracts),
        )


def run_doctor(
    compositions: list[NativeHarnessComposition], strict_evidence: bool
) -> None:
    """Report installed native runtime evidence without updating either CLI."""
    failed = False
    drifts: list[EvidenceDrift] = []  # lup: ignore[empty-collection]
    readings: list[SchemaReading] = []  # lup: ignore[empty-collection] — the loop
    # below folds three things at once and only one of them collects here
    for composition in compositions:
        evidence = composition.readiness()
        for item in evidence:
            typer.echo(item.model_dump_json(indent=2))
            if item.supported:
                drift = evidence_drift(item.capability, item.version)
                if drift is not None:
                    drifts.append(drift)
        if composition.recipe.label == "claude":
            sdk_drift = sdk_evidence_drift()
            if sdk_drift is not None:
                drifts.append(sdk_drift)
            for tool in ("bwrap", "socat"):
                state = "ready" if shutil.which(tool) is not None else "missing"
                typer.echo(f"claude sandbox dependency {tool}: {state}")
        # `SCHEMA_COMMAND` is Codex's own generator, so the label still says
        # whose schemas these are. What the composition supplies is the
        # narrower half: which reply shapes its adapter reads by name.
        if composition.recipe.label == "codex":
            readings.append(schema_reading(composition.wire_contracts))
        failed = failed or any(not item.supported for item in evidence)
    for message in [
        *[drift.message for drift in drifts],
        *[finding for reading in readings for finding in reading.findings()],
    ]:
        typer.echo(message, err=True)
    moved = drifts or any(reading.drifted() for reading in readings)
    if failed or (strict_evidence and moved):
        raise typer.Exit(1)
