"""What a gate step finds without failing: a flaky check, a slow one, a line no promise notices, each told to the gate to file.

The gate gives each step a file of its own, named in the environment variable
`FindingsFile` reads, and a step writes one JSON line to it for each finding
(`tell`). The gate reads them once the step has run, keeps them with the run it
records, and shows them where the branch is reviewed; landing the branch files
each as a friction under its subject (`README.md` here, *Findings*).
"""

from pathlib import Path

from lup.types import Model, Settings


class Finding(Model):
    """Something a step found without failing, to be filed rather than failing anyone: what it's about, a few words naming it, and what it found.

    >>> Finding(about="hosting", title="a slow check", text="18 s").title
    'a slow check'
    """

    about: str
    """What it's about, by name: a module, or `harness` for the harness's own."""
    title: str
    text: str


class FindingsFile(Settings):
    """The environment variable the gate names a step's findings file in, which a step reads."""

    lup_gate_findings: Path | None = None
    """The file a step writes its findings to, one JSON line each; none outside
    the gate, where a step's findings go nowhere."""


def variable() -> str:
    """Return the name of the environment variable naming a step's findings file, as `FindingsFile` reads it.

    >>> variable()
    'LUP_GATE_FINDINGS'
    """
    [field] = FindingsFile.model_fields
    return field.upper()


def tell(finding: Finding) -> None:
    """Write `finding` to the findings file the gate gave the step running this, a line of JSON; nothing outside the gate."""
    file = FindingsFile().lup_gate_findings
    if file is not None:
        with file.open("a") as written:
            written.write(finding.model_dump_json() + "\n")


def read(file: Path) -> list[Finding]:
    """Return each finding written to `file`, in the order written; none where nothing was."""
    if not file.is_file():
        return []
    return [
        Finding.model_validate_json(line)
        for line in file.read_text().splitlines()
        if line.strip()
    ]
