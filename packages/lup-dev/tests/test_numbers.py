"""An inbox item's number in text read outside lup: found where Markdown reads text, never in code, an address, a mention or a version."""

from lup_dev.inbox.numbers import Number, numbered


def said(text: str) -> list[str]:
    """Return each item's number `text` writes, as it's written."""
    return [each.said for each in numbered(text)]


def test_an_item_and_a_part_are_found_on_their_line_and_column() -> None:
    message = (
        "fix(landing): a merge's files count as committed\n"
        "\n"
        "That's @1505: ac7ce4b's checkpoint flagged again, as the\n"
        "operator had approved as @1477 and @1479.3.\n"
    )
    assert numbered(message) == [
        Number(
            said="@1505",
            line=3,
            column=8,
            text="That's @1505: ac7ce4b's checkpoint flagged again, as the",
        ),
        Number(
            said="@1477",
            line=4,
            column=26,
            text="operator had approved as @1477 and @1479.3.",
        ),
        Number(
            said="@1479.3",
            line=4,
            column=36,
            text="operator had approved as @1477 and @1479.3.",
        ),
    ]


def test_one_in_a_subject_line_or_after_a_bracket_is_found() -> None:
    assert said("Merge told-once: each finding told once (@1210, #142's case)") == [
        "@1210"
    ]
    assert said("(@1236, answering @1234).") == ["@1236", "@1234"]
    assert said("cites @820[why … it] and @12's file") == ["@820", "@12"]


def test_none_is_found_in_code() -> None:
    message = (
        "An item is cited `@270`, a part `@414.3`, an operator's words\n"
        "`@820.9[first … last]`; the drawer says `␣a approves\n"
        "@55, every file` across a line.\n"
        "\n"
        "```\n"
        "lup-dev inbox show @12\n"
        "```\n"
        "\n"
        "    answer @2\n"
    )
    assert said(message) == []


def test_addresses_mentions_decorators_and_git_s_own_at_are_not_items() -> None:
    message = (
        "Co-Authored-By: Claude <noreply@anthropic.com>, and\n"
        "joy@1505.example, @joy-void-joy, @dataclass, @override, HEAD@{1},\n"
        "stash@{0}, pnpm@11, icon@2x.png, @2x, a bare @ and @@270.\n"
    )
    assert said(message) == []


def test_a_number_running_on_into_a_word_or_a_version_is_not_an_item() -> None:
    assert said("pinned at @1.2.3, scaled @2x, and @12abc") == []
    assert said("version @1.2 stays a part") == ["@1.2"]


def test_a_backslash_keeps_it_as_text() -> None:
    assert said(r"written \@1505 on purpose") == []


def test_the_same_number_in_code_and_out_is_placed_where_it_s_out() -> None:
    [found] = numbered("`@1505` names it; so does @1505.")
    assert (found.line, found.column) == (1, 27)


def test_lists_quotes_and_tables_are_read_as_text() -> None:
    message = (
        "- first point\n"
        "  continued @7 here\n"
        "> quoting @8\n"
        "\n"
        "| item | why |\n"
        "|---|---|\n"
        "| `@9` | after @10 |\n"
    )
    assert [(each.said, each.line, each.column) for each in numbered(message)] == [
        ("@7", 2, 13),
        ("@8", 3, 11),
        ("@10", 7, 16),
    ]
