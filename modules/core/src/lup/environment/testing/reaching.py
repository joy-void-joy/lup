"""Which check runs which line of the repository's code: recorded with `coverage` as pytest checks the promises, each check its own context, for a landing's mutation to read (`lup/testing/README.md`, *Mutation*).

Under several workers each process records into a file of its own beside the
one asked for, and the run's controller combines them into it once every
worker has ended.
"""

from pathlib import Path

import coverage

from lup.types import MutableModel


class Reach(MutableModel, arbitrary_types_allowed=True):
    """Recording which check runs which line under `root`, into the coverage data file at `path`."""

    path: Path
    root: Path
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
            source=[str(self.root)],
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
