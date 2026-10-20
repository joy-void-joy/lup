"""Every citation of a document names a document the repository has, and headings it has.

A citation is a document's path in a code span, `docs/launch.md` or `DESIGN.md`,
and the sections it names follow in italics: "(`docs/launch.md`, *Guidance*)",
"`docs/host-tools.md`, *The server* and *The room's requests*",
"`docs/declaration.md`'s (*What a launch reads*, *The runner*)". Docstrings and
comments wrap a citation across lines, so each file is read with its lines
joined and their comment markers dropped. A section names a heading whole, or
its start before a parenthesis, a comma or a colon: *The Codex SDK* names "The
Codex SDK, `openai-codex` 0.162 (…)". A section is a heading, or the bold words
leading a paragraph or a list's item ("**Told once.** An item is told…"), which
a document uses for what's smaller than a heading.

Read in every file git tracks but the tests, whose documents are made up, and
the engine's bundled typeshed. A document of another repository is cited with
its name beside it ("`docs/rules.md` in `lup-legacy`"), and isn't checked.
"""

import re
from pathlib import Path

from lup.programs import run

REPOSITORY = Path(__file__).resolve().parents[3]

READ = [".py", ".ts", ".tsx", ".md", ".toml"]
"""The suffixes of the files citations are read in."""

SKIPPED = ["packages/*/tests/**", "packages/lup-dev/src/lup_dev/codescan/bundle/**"]
"""Paths whose citations aren't read: the tests' made-up documents, and the bundle."""

ELSEWHERE = ["lup-legacy", "first lup"]
"""Words that, just after a citation, say its document is another repository's."""

DOCUMENT = r"`((?:docs/[a-z-]+|DESIGN|AGENTS)\.md)`"
SECTIONS = r"(?:'s)?,? \(?(\*[^*]+\*(?:[,;]? (?:and |or )?\*[^*]+\*)*)"
CITATION = re.compile(DOCUMENT + f"(?:{SECTIONS})?")
JOINED = re.compile(r"\n[ \t]*(?:#|//)?[ \t]*")
FENCE = re.compile(r"^(```|~~~)")
HEADING = re.compile(r"^#{1,6} (.+?)\s*$")
LEAD = re.compile(r"^\s*(?:[-*] |\d+\. )?\*\*(.+?)[.,:]?\*\*")


def joined(text: str) -> str:
    """Join `text`'s lines, each line's indentation and comment marker dropped."""
    return JOINED.sub(" ", text)


def cited(text: str) -> list[tuple[str, list[str]]]:
    """Return each citation in `text`: the document, and the sections it names.

    >>> cited("as launched (`docs/launch.md`, *Guidance*).")
    [('docs/launch.md', ['Guidance'])]
    >>> cited("`docs/host-tools.md`, *The server* and *The room's requests*")
    [('docs/host-tools.md', ['The server', "The room's requests"])]
    >>> cited("`docs/declaration.md`'s (*What a launch reads*, *The runner*, *Requirements*)")
    [('docs/declaration.md', ['What a launch reads', 'The runner', 'Requirements'])]
    >>> cited(joined("its engine (`docs/judging-writes.md`,\\n    # *The engine: one typed tree*)"))
    [('docs/judging-writes.md', ['The engine: one typed tree'])]
    >>> cited("`DESIGN.md` describes it; `docs/rules.md` in `lup-legacy` too")
    [('DESIGN.md', [])]
    """
    found: list[tuple[str, list[str]]] = []
    for match in CITATION.finditer(text):
        after = text[match.end() : match.end() + 40]
        if any(word in after for word in ELSEWHERE):
            continue
        named = re.findall(r"\*([^*]+)\*", match.group(2) or "")
        found.append((match.group(1), named))
    return found


def sections(document: str) -> list[str]:
    """Return `document`'s sections, outside its fenced code: its headings, and the bold words leading a paragraph or an item.

    >>> sections("# A\\n\\n```\\n# not one\\n```\\n## B `c`\\n\\n**Told once.** Said.\\n- **D, e:** f\\n")
    ['A', 'B `c`', 'Told once', 'D, e']
    """
    found: list[str] = []
    fenced = False
    for line in document.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        named = HEADING.match(line) or LEAD.match(line)
        if named and not fenced:
            found.append(named.group(1))
    return found


def names(cited: str, section: str) -> bool:
    """Say whether `cited` names `section`: whole, or its start before a parenthesis, a comma or a colon.

    >>> names("The Codex SDK", "The Codex SDK, `openai-codex` 0.162")
    True
    >>> names("The room", "The room's git")
    False
    """
    return section == cited or any(
        section.startswith(cited + after) for after in [" (", ", ", ": "]
    )


def tracked() -> list[Path]:
    """List the files git tracks whose citations are read."""
    listed = run("git", "ls-files", "-z", cwd=REPOSITORY).text()
    paths = [Path(each) for each in listed.split("\0") if each]
    return [
        path
        for path in paths
        if path.suffix in READ
        and not any(path.full_match(pattern) for pattern in SKIPPED)
        and (REPOSITORY / path).is_file()
    ]


def test_every_citation_names_a_document_and_its_headings() -> None:
    documents: dict[str, list[str]] = {}
    wrong: list[str] = []
    checked = 0
    for path in tracked():
        for document, named in cited(joined((REPOSITORY / path).read_text())):
            checked += 1
            target = REPOSITORY / document
            if not target.is_file():
                wrong.append(f"{path}: `{document}` isn't a document here")
                continue
            if document not in documents:
                documents[document] = sections(target.read_text())
            wrong.extend(
                f"{path}: `{document}` has no section *{each}*"
                for each in named
                if not any(names(each, section) for section in documents[document])
            )
    assert checked > 100, "citations are no longer read: their form changed"
    assert wrong == [], "\n".join(["Citations naming what isn't there:", *wrong])
