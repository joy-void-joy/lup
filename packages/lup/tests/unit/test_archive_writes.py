"""Reading an archive verb's destination off the command line.

`None` is the answer for anything unmodelled, and it means the verb keeps
its own ask — so these cases are as much about what is declined as about
what is read.

`authored` and `consumed` are separate because absence means opposite
things of them: nothing standing where a path is authored is the reason it
costs nothing, while nothing standing where one is consumed is a fact the
host could not establish about something about to be destroyed.
"""

from lup.policy.kernel.archives import archive_write


def test_an_extraction_names_the_directory_it_unpacks_into() -> None:
    assert archive_write(["tar", "-xzf", "a.tgz", "-C", "dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }
    assert archive_write(["tar", "--extract", "--file=a.tar", "--directory=dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }
    assert archive_write(["unzip", "a.zip", "-d", "dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }


def test_an_extraction_naming_no_destination_names_nothing_at_all() -> None:
    """Unpacking where it stands is not a destination this can judge.

    The working directory is normally the repository, so it is both certain
    to be occupied and the last place an unread archive should land unasked.
    Every field comes back empty, and empty grants nothing.
    """
    assert archive_write(["tar", "-xf", "a.tar"]) == {
        "authored": [],
        "consumed": [],
        "directory": None,
    }
    assert archive_write(["unzip", "a.zip"]) == {
        "authored": [],
        "consumed": [],
        "directory": None,
    }


def test_creating_an_archive_authors_the_file_it_names() -> None:
    assert archive_write(["tar", "-czf", "out.tar.gz", "src"]) == {
        "authored": ["out.tar.gz"],
        "consumed": [],
        "directory": None,
    }


def test_compression_authors_one_path_and_consumes_the_other() -> None:
    """Neither verb adds beside its operand; both replace it."""
    assert archive_write(["gzip", "notes.txt"]) == {
        "authored": ["notes.txt.gz"],
        "consumed": ["notes.txt"],
        "directory": None,
    }
    assert archive_write(["gunzip", "notes.txt.gz"]) == {
        "authored": ["notes.txt"],
        "consumed": ["notes.txt.gz"],
        "directory": None,
    }


def test_a_flag_letting_members_escape_the_destination_is_declined() -> None:
    """`-P` keeps absolute member paths, so the destination stops bounding it."""
    assert archive_write(["tar", "-xf", "a.tar", "-C", "dest", "-P"]) is None
    assert (
        archive_write(["tar", "--extract", "--absolute-names", "-f", "a.tar"]) is None
    )


def test_an_unmodelled_mode_or_flag_keeps_the_verb_ask() -> None:
    assert archive_write(["tar", "-rf", "a.tar", "extra"]) is None
    assert archive_write(["tar", "-tf", "a.tar"]) is None
    assert archive_write(["tar", "xf", "a.tar"]) is None
    assert archive_write(["unzip", "-p", "a.zip"]) is None
    assert archive_write(["gzip", "-r", "somedir"]) is None
    assert archive_write(["gzip", "--best", "f"]) is None


def test_a_valued_flag_never_reads_as_an_operand() -> None:
    """`-C dest` must not leave `dest` looking like a path tar writes."""
    assert archive_write(["tar", "-xf", "a.tar", "-C", "dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }
    assert archive_write(["tar", "-xf"]) is None


def test_decompressing_something_not_named_as_compressed_is_declined() -> None:
    assert archive_write(["gunzip", "notes.txt"]) is None


def test_a_verb_this_module_does_not_model_answers_nothing() -> None:
    assert archive_write(["rm", "-rf", "x"]) is None
    assert archive_write([]) is None
