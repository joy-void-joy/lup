"""Which check runs which line of the repository's code: recorded with `coverage` as pytest checks the promises, each check its own context, for a landing's mutation to read (`lup/testing/README.md`, *Mutation*).

Under several workers each process records into a file of its own beside the
one asked for, and the run's controller combines them into it once every
worker has ended.
"""

import tempfile
from pathlib import Path, PurePosixPath

import coverage
import pytest
from pydantic import TypeAdapter

from lup.types import Model, MutableModel


class Reach(MutableModel, arbitrary_types_allowed=True):
    """Recording which check runs which line under `root`, into the coverage data file at `path`."""

    path: Path
    root: Path
    only: list[Path] = []
    """The files to record, alone; every file under `root` where none are
    named."""
    worker: bool
    """Whether this process is one of several workers, whose controller
    combines what each recorded."""
    recording: coverage.Coverage | None = None

    def started(self) -> None:
        """Start recording, into a file of this process's own beside `path`."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        recording = coverage.Coverage(
            data_file=str(self.path),
            data_suffix=True,
            source=None if self.only else [str(self.root)],
            include=[str(each) for each in self.only] or None,
            config_file=False,
        )
        # Credited line by line to the check running it: coverage's own tracer,
        # since its `sys.monitoring` one keeps no context of what runs.
        recording.set_option("run:core", "ctrace")
        recording.start()
        self.recording = recording

    def checking(self, name: str) -> None:
        """Credit what runs from now on to the check named `name`; none between checks."""
        if self.recording is not None:
            self.recording.switch_context(name)

    def stopped(self) -> None:
        """Stop recording and save it; the controller of the run combines every process's into `path`."""
        if self.recording is not None:
            self.recording.stop()
            self.recording.save()
        if not self.worker:
            combined = coverage.Coverage(data_file=str(self.path), config_file=False)
            combined.combine([str(self.path.parent)])
            combined.save()


def reached(path: Path, file: Path) -> dict[int, list[str]]:
    """Return, for each line of `file` some check ran, the checks that ran it, from the coverage data file at `path`."""
    data = coverage.CoverageData(basename=str(path))
    data.read()
    by_line = data.contexts_by_lineno(str(file.resolve()))
    return {line: [each for each in names if each] for line, names in by_line.items()}


class Located(Model):
    """A check, by pytest's name for it, and the file it's written in, from pytest's root."""

    check: str
    file: PurePosixPath


LOCATED = TypeAdapter(list[Located])
"""Each check collected, as `--lup-reach` writes them beside what each runs."""


def located(path: Path, items: list[pytest.Item]) -> None:
    """Write where each of `items` is written, as `LOCATED`, to `path`, whole, whichever process of the run writes it last."""
    written = LOCATED.dump_json(
        [
            Located(check=each.nodeid, file=PurePosixPath(each.location[0]))
            for each in items
        ]
    )
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as apart:
        apart.write(written)
    Path(apart.name).replace(path)


def locations(path: Path) -> list[Located]:
    """Return each check collected and where it's written, as `located` wrote them to `path`."""
    return LOCATED.validate_json(path.read_bytes())
