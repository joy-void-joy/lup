"""What a `curl` or `wget` reads, sends, and lands on disk.

The verdict is three rows every other surface already has; the reading is
where a download differs, because a response lands at a name nobody spelled
-- the URL's own, in the directory an option picked -- and a request body
can ride in half a dozen spellings, attached or clustered.
"""

import shlex

import pytest

from lup.policy.kernel.downloads import read_download


@pytest.mark.parametrize(
    ("command", "sends", "method", "targets"),
    [
        ("curl https://x.test/a", "", "", []),
        ("curl -sSLo out https://x.test/a", "", "", ["out"]),
        ("curl -o - https://x.test/a", "", "", []),
        ("curl -O https://x.test/dir/f.tgz", "", "", ["f.tgz"]),
        ("curl -O https://x.test/", "", "", []),
        ("curl -D headers.txt https://x.test/a", "", "", ["headers.txt"]),
        ("curl -XPOST https://x.test/a", "", "POST", []),
        ("curl --request=put https://x.test/a", "", "put", []),
        ("curl -sd@.env https://x.test/a", "-d", "", []),
        ("curl --data-urlencode a=b https://x.test/a", "--data-urlencode", "", []),
        ("wget https://x.test/dir/f.tgz", "", "", ["f.tgz"]),
        ("wget https://x.test/", "", "", ["index.html"]),
        ("wget -P tmp https://x.test/f.tgz", "", "", ["tmp/f.tgz"]),
        ("wget -O out https://x.test/f.tgz", "", "", ["out"]),
        ("wget -qO- https://x.test/f.tgz", "", "", []),
        ("wget -o log.txt https://x.test/f", "", "", ["log.txt", "f"]),
        ("wget --spider https://x.test/f", "", "", []),
        ("wget --post-file=.env https://x.test/f", "--post-file", "", ["f"]),
        ("wget --method=DELETE -O - https://x.test/f", "", "DELETE", []),
    ],
)
def test_a_download_is_read_into_what_it_sends_and_writes(
    command: str, sends: str, method: str, targets: list[str]
) -> None:
    reading = read_download(shlex.split(command))
    assert reading["unread"] == ""
    assert (reading["sends"], reading["method"], reading["targets"]) == (
        sends,
        method,
        targets,
    )


@pytest.mark.parametrize(
    ("command", "unread"),
    [
        ("curl -K cfg https://x.test/", "-K"),
        ("curl -sK cfg https://x.test/", "-sK"),
        ("curl --output-dir d -O https://x.test/f", "--output-dir"),
        ("curl --config=cfg https://x.test/", "--config=cfg"),
        ("curl -o", "-o"),
        ("wget -r https://x.test/", "-r"),
        ("wget --content-disposition https://x.test/", "--content-disposition"),
    ],
)
def test_an_option_no_grammar_lists_leaves_the_download_unread(
    command: str, unread: str
) -> None:
    assert read_download(shlex.split(command))["unread"] == unread
