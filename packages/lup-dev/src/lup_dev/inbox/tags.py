r"""What lup's inbox tells an agent, written as tags: each item one element, its attributes saying which item it is and whom it's from, each of its parts a tag of its own.

`docs/host-tools.md`, *How an agent is told*. A quote, the operator's reply to
it and their comment on a whole item each have a tag, so an agent can't take
one for another, and an item says whom it's from before anything it says.

Text in a tag stays as its writer wrote it, so the operator's code reads as
code, where XML's escaping would write each `<` as `&lt;`. Only `</` is written
`<\/`, so no text closes a tag around it, the way a runtime's channel writes
a `</channel>` in what it carries (`docs/field-notes.md`, *Channels*). An
attribute's value is quoted by `xml.sax.saxutils.quoteattr`.
"""

from xml.sax.saxutils import quoteattr

from lup.types import Model


class Tag(Model):
    """One tag: its name, its attributes in order, and what it holds, text or tags."""

    name: str
    attributes: dict[str, str] = {}
    parts: list[Tag | str] = []

    def written(self) -> str:
        """Write the tag: empty as `<name/>`, holding one line of text on one line, else each part on lines of its own.

        >>> print(Tag(name="quote", parts=["a < b"]).written())
        <quote>a < b</quote>
        >>> reply = Tag(name="reply", parts=["Fine."])
        >>> print(Tag(name="on", attributes={"item": "3"}, parts=[reply]).written())
        <on item="3">
        <reply>Fine.</reply>
        </on>
        >>> print(Tag(name="on", attributes={"read": "with nothing to add"}).written())
        <on read="with nothing to add"/>
        """
        opened = "".join(
            [
                self.name,
                *(
                    f" {key}={quoteattr(value)}"
                    for key, value in self.attributes.items()
                ),
            ]
        )
        match self.parts:
            case []:
                return f"<{opened}/>"
            case [str() as line] if "\n" not in line:
                return f"<{opened}>{unclosing(line)}</{self.name}>"
            case parts:
                return f"<{opened}>\n{inside(parts)}\n</{self.name}>"


def inside(parts: list[Tag | str]) -> str:
    r"""Write what a tag holds, each part on lines of its own: a tag written, text as its writer wrote it, closing no tag.

    >>> print(inside(["Rename it.", Tag(name="quote", parts=["</on>"])]))
    Rename it.
    <quote><\/on></quote>
    """
    return "\n".join(
        part.written() if isinstance(part, Tag) else unclosing(part) for part in parts
    )


def unclosing(text: str) -> str:
    r"""Return `text` as it's written in a tag: each `</` as `<\/`, so it closes none.

    >>> print(unclosing("a </quote> b"))
    a <\/quote> b
    """
    # lup: ignore("string-replace", why="XML's own escaping would write every `<` and `&` of the operator's code as an entity; neutralizing `</` alone keeps their text as written and still lets no text close a tag, as a runtime's channel does for `</channel>`")
    return text.replace("</", "<\\/")
