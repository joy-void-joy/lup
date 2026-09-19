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


def destination(words: list[str]) -> dict[str, object] | None:
    """What a verb writes, without the words it read those paths out of.

    Where each path was read from is :func:`test_every_path_is_named_by_the_word_it_was_read_from`'s
    subject and nobody else's, so it stays out of the comparisons that are
    about the destination.
    """
    write = archive_write(words)
    return (
        None
        if write is None
        else {
            "authored": write["authored"],
            "consumed": write["consumed"],
            "directory": write["directory"],
        }
    )


def test_an_extraction_names_the_directory_it_unpacks_into() -> None:
    assert destination(["tar", "-xzf", "a.tgz", "-C", "dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }
    assert destination(["tar", "--extract", "--file=a.tar", "--directory=dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }
    assert destination(["unzip", "a.zip", "-d", "dest"]) == {
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
    assert destination(["tar", "-xf", "a.tar"]) == {
        "authored": [],
        "consumed": [],
        "directory": None,
    }
    assert destination(["unzip", "a.zip"]) == {
        "authored": [],
        "consumed": [],
        "directory": None,
    }


def test_creating_an_archive_authors_the_file_it_names() -> None:
    assert destination(["tar", "-czf", "out.tar.gz", "src"]) == {
        "authored": ["out.tar.gz"],
        "consumed": [],
        "directory": None,
    }


def test_compression_authors_one_path_and_consumes_the_other() -> None:
    """Neither verb adds beside its operand; both replace it."""
    assert destination(["gzip", "notes.txt"]) == {
        "authored": ["notes.txt.gz"],
        "consumed": ["notes.txt"],
        "directory": None,
    }
    assert destination(["gunzip", "notes.txt.gz"]) == {
        "authored": ["notes.txt"],
        "consumed": ["notes.txt.gz"],
        "directory": None,
    }


def test_a_flag_letting_members_escape_the_destination_is_declined() -> None:
    """`-P` keeps absolute member paths, so the destination stops bounding it."""
    assert destination(["tar", "-xf", "a.tar", "-C", "dest", "-P"]) is None
    assert (
        archive_write(["tar", "--extract", "--absolute-names", "-f", "a.tar"]) is None
    )


def test_an_unmodelled_mode_or_flag_keeps_the_verb_ask() -> None:
    assert destination(["tar", "-rf", "a.tar", "extra"]) is None
    assert destination(["tar", "-tf", "a.tar"]) is None
    assert destination(["tar", "xf", "a.tar"]) is None
    assert destination(["unzip", "-p", "a.zip"]) is None
    assert destination(["gzip", "-r", "somedir"]) is None
    assert destination(["gzip", "--best", "f"]) is None


def test_a_valued_flag_never_reads_as_an_operand() -> None:
    """`-C dest` must not leave `dest` looking like a path tar writes."""
    assert destination(["tar", "-xf", "a.tar", "-C", "dest"]) == {
        "authored": [],
        "consumed": [],
        "directory": "dest",
    }
    assert destination(["tar", "-xf"]) is None


def test_decompressing_something_not_named_as_compressed_is_declined() -> None:
    assert destination(["gunzip", "notes.txt"]) is None


def test_a_verb_this_module_does_not_model_answers_nothing() -> None:
    assert destination(["rm", "-rf", "x"]) is None
    assert destination([]) is None


def test_every_path_is_named_by_the_word_it_was_read_from() -> None:
    """A caller resolving one of these paths has to put it back where it was.

    The word and not the path, which is why a derived destination is absent:
    `gzip notes.txt` authors `notes.txt.gz`, a path nowhere in the command, so
    the operand it was derived from is what is named. A reader taking the
    resolved words afresh derives the resolved `.gz` beside it.
    """
    following = archive_write(["tar", "-xzf", "a.tgz", "-C", "dest"])
    assert following is not None
    assert following["named"] == [
        {"at": 2, "prefix": "", "path": "a.tgz"},
        {"at": 4, "prefix": "", "path": "dest"},
    ]
    attached = archive_write(["tar", "--extract", "--file=a.tar", "--directory=dest"])
    assert attached is not None
    assert attached["named"] == [
        {"at": 2, "prefix": "--file=", "path": "a.tar"},
        {"at": 3, "prefix": "--directory=", "path": "dest"},
    ]
    compressed = archive_write(["gzip", "notes.txt"])
    assert compressed is not None
    assert compressed["named"] == [{"at": 1, "prefix": "", "path": "notes.txt"}]
