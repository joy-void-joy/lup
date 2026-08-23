"""What the per-section guidance report attributes, and to which heading."""

from lup.devtools.dev.guidance import guidance_sections
from lup.harness.models import document_byte_size


def test_every_byte_lands_under_exactly_one_heading() -> None:
    """The rows have to sum to the document, or the report misdirects a cut.

    A section report whose parts do not add up sends somebody to condense the
    wrong heading, which is worse than no report: the number looked measured.
    """
    document = "top\n\n# One\n\nalpha\n\n## Two\n\nbeta\n\n# Three\n\ngamma\n"

    sections = guidance_sections(document)

    assert sum(section.used for section in sections) == document_byte_size(document)
    assert [section.heading for section in sections] == [
        "(banner)",
        "One",
        "Two",
        "Three",
    ]


def test_a_shell_comment_in_a_fence_is_not_a_heading() -> None:
    """Guidance carries fenced shell blocks, and `# cd` spells a heading's shape.

    Scanning lines for a leading `#` would split a section in the middle of a
    code block and bill the remainder to a heading that does not exist. The
    document is parsed, so a fence is content.
    """
    document = "# Real\n\n```sh\n# not a heading\ncd /tmp\n```\n\ntail\n"

    sections = guidance_sections(document)

    assert [section.heading for section in sections] == ["Real"]
    assert sections[0].used == document_byte_size(document)


def test_depth_is_kept_so_a_subsection_reads_as_one() -> None:
    """A `###` under a `##` is indented, not listed as its equal."""
    document = "# One\n\n## Two\n\n### Three\n"

    assert [section.level for section in guidance_sections(document)] == [1, 2, 3]


def test_a_document_that_opens_on_a_heading_reports_no_banner() -> None:
    """The banner row exists because generated trees carry one, not always."""
    assert [section.heading for section in guidance_sections("# Only\n\nbody\n")] == [
        "Only"
    ]
