"""Runtime evidence doctor for installed native CLIs and SDKs.

Probes each selected composition's runtime readiness, prints the collected
evidence, and compares supported components against the accepted ledger in
``evidence`` — nonzero on missing capabilities, and on version drift under
``--strict-evidence``.
"""

import os

import typer

from lup.devtools.harness.evidence import (
    EvidenceDrift,
    evidence_drift,
    sdk_evidence_drift,
)
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.harness.toolchain import bubblewrap_requirement, socat_requirement
from lup.types import EnvVars


def run_doctor(
    compositions: list[NativeHarnessComposition], strict_evidence: bool
) -> None:
    """Report installed native runtime evidence without updating either CLI."""
    failed = False
    environ: EnvVars = dict(os.environ)  # lup: ignore[os-environ]
    drifts: list[EvidenceDrift] = []  # lup: ignore[empty-collection]
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
            # Exercised, and through the same constructors the launcher uses.
            # Asked separately they disagreed: `shutil.which` called socat
            # ready on every host that carried it, while the launcher probed
            # it with a flag socat does not have and called it broken on
            # every host in the world. One declaration cannot say both.
            for requirement in (bubblewrap_requirement(), socat_requirement()):
                finding = requirement.check(environ)
                state = "ready" if finding.working else f"missing — {finding.detail}"
                typer.echo(
                    f"claude sandbox dependency {finding.requirement.capability}: {state}"
                )
        failed = failed or any(not item.supported for item in evidence)
    for drift in drifts:
        typer.echo(drift.message, err=True)
    if failed or (strict_evidence and drifts):
        raise typer.Exit(1)
