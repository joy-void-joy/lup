"""Runtime evidence doctor for installed native CLIs and SDKs.

Probes each selected composition's runtime readiness, prints the collected
evidence, and compares supported components against the accepted ledger in
``evidence`` — nonzero on missing capabilities, and on version drift under
``--strict-evidence``.
"""

import shutil
import tempfile
from pathlib import Path

import sh
import typer

from lup.devtools.harness.evidence import (
    SCHEMA_COMMAND,
    DigestDrift,
    EvidenceDrift,
    digest_drift,
    evidence_drift,
    sdk_evidence_drift,
)
from lup.devtools.harness.generate import NativeHarnessComposition


def schema_digest_drift() -> list[DigestDrift]:
    """Regenerate the app-server schemas and compare them to what was accepted.

    A CLI that cannot generate them reports no drift rather than a failure:
    the version probes already say codex is missing, and a second complaint
    about the same absence buries the digest changes this exists to surface.
    """
    with tempfile.TemporaryDirectory() as directory:
        try:
            command = sh.Command(SCHEMA_COMMAND.executable)
            command(*SCHEMA_COMMAND.arguments, directory)
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            return []
        return digest_drift(Path(directory))


def run_doctor(
    compositions: list[NativeHarnessComposition], strict_evidence: bool
) -> None:
    """Report installed native runtime evidence without updating either CLI."""
    failed = False
    drifts: list[EvidenceDrift] = []  # lup: ignore[empty-collection]
    digests: list[DigestDrift] = []  # lup: ignore[empty-collection]
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
        if composition.recipe.label == "codex":
            digests.extend(schema_digest_drift())
        failed = failed or any(not item.supported for item in evidence)
    for drift in [*drifts, *digests]:
        typer.echo(drift.message, err=True)
    if failed or (strict_evidence and (drifts or digests)):
        raise typer.Exit(1)
