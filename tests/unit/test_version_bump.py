"""What `version bump` records, checked through the option wiring itself.

`test_changelog.py` pins the document model. These go through Typer, because
the published regression was not in the rendering — it was in the option
being a scalar that kept only the last `--detail`, and in that one string
being split on its own commas afterwards. Both faults live between the
command line and the model, which is where a test has to stand to see them.

Every case runs `--dry-run`: the entry is rendered and shown without a file
being written, a commit made, or a tag created.
"""

from typer.testing import CliRunner

from lup.devtools.version import app

runner = CliRunner()


def bullets(output: str) -> list[str]:
    """The detail lines of a rendered entry, as a reader would count them."""
    return [line for line in output.splitlines() if line.startswith("- ")]


def dry_bump(*arguments: str) -> str:
    """A bump that shows what it would record and writes nothing."""
    result = runner.invoke(app, ["bump", "patch", *arguments, "--dry-run"])
    assert result.exit_code == 0, result.output
    return result.output


def test_every_detail_reaches_the_entry() -> None:
    """A scalar option kept only the last of these three."""
    output = dry_bump("A summary", "-d", "first", "-d", "second", "-d", "third")

    assert bullets(output) == ["- first", "- second", "- third"]


def test_a_detail_holding_commas_stays_one_bullet() -> None:
    """The published damage: one sentence became four bullets on its commas."""
    prose = "the settings — the sandbox, the roots, the ceiling — ride a transform"
    output = dry_bump("A summary", "--detail", prose)

    assert bullets(output) == [f"- {prose}"]


def test_the_summary_is_recorded_above_its_details() -> None:
    """A bullet list with no sentence over it is not an entry."""
    output = dry_bump("Govern each session by the fields that bound it", "-d", "one")

    assert "Govern each session by the fields that bound it" in output


def test_a_detail_without_a_summary_is_refused() -> None:
    """Silently dropping it would be the same class of fault being fixed."""
    result = runner.invoke(app, ["bump", "patch", "--detail", "orphan", "--dry-run"])

    assert result.exit_code == 1
    assert "summary" in result.output


def test_a_bump_naming_no_summary_records_nothing() -> None:
    """The version alone is a fact the manifest already carries."""
    output = dry_bump()

    assert bullets(output) == []


def test_no_tag_is_reported_rather_than_assumed() -> None:
    """A dry run has to say which of the two it would do."""
    assert "Would not tag" in dry_bump("A summary", "--no-tag")
    assert "Would tag" in dry_bump("A summary")
