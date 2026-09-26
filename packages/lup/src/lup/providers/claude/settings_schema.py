"""Read which settings a Claude Code CLI takes, out of the program itself.

Claude Code publishes no command listing its settings keys. What it does ship
is the schema it validates every settings file against, baked into the
program as the zod object its bundler emitted, and the list of global
configuration keys ``claude config`` accepts, baked as an array literal.
Those two are what this module reads into a
:class:`~lup.providers.settings_schema.SettingsSchema`, so the keys lup
classifies are the ones the installed CLI takes rather than a list somebody
kept by hand.
"""

import json
from pathlib import Path

import sh

from lup.providers.claude.catalog import claude_program
from lup.providers.settings_schema import SettingsSchema

# lup: ignore[constant-declaration] — the CLI's own bytes, the description its
# settings schema gives its first key, which a minifier leaves untouched
SETTINGS_SCHEMA_MARKER = b'"JSON Schema reference for Claude Code settings"'
"""Where the settings schema's object literal is found inside the program.

The description of the schema's ``$schema`` key, which the bundler carries
through verbatim, so it survives every renaming a minifier does to the code
around it. The object literal opening before that key is the schema.
"""

# lup: ignore[constant-declaration] — the CLI's own bytes: a member of the array
# `claude config` checks a global key against, and of nothing else it ships
DOCUMENT_KEYS_MARKER = b'"shiftEnterKeyBindingInstalled",'
"""A member of the global configuration's key array, spelled as the bundler emits it.

One member no other literal carries finds the array; the array is the
bracketed list around it.
"""


class ScriptScan:
    """Walk a minified JavaScript program by its brackets, strings and regexes.

    Only as much of the grammar as finding an object literal's own keys
    needs: strings of all three quotes, template literals with their nested
    ``${}`` code, regular expression literals, and bracket depth. A key is a
    word or a string directly inside the object, following its opening brace
    or a comma and followed by a colon; everything deeper is a value.
    """

    def __init__(self, program: bytes) -> None:
        self.program = program

    def after_string(self, index: int) -> int:
        """Past the quoted string opening at ``index``."""
        quote = self.program[index]
        index += 1
        while self.program[index] != quote:
            index += 2 if self.program[index] == ord("\\") else 1
        return index + 1

    def after_template(self, index: int) -> int:
        """Past the template literal opening at ``index``, its code included."""
        index += 1
        while self.program[index] != ord("`"):
            if self.program[index] == ord("\\"):
                index += 2
                continue
            if self.program.startswith(b"${", index):
                index = self.walk(index + 1, [])
                continue
            index += 1
        return index + 1

    def after_regex(self, index: int) -> int:
        """Past the regular expression literal opening at ``index``."""
        index += 1
        in_class = False
        while in_class or self.program[index] != ord("/"):
            match self.program[index]:
                case 0x5C:
                    index += 1
                case 0x5B:
                    in_class = True
                case 0x5D:
                    in_class = False
            index += 1
        return index + 1

    def after_word(self, index: int) -> int:
        """Past the identifier starting at ``index``."""
        while chr(self.program[index]).isalnum() or self.program[index] in b"$_":
            index += 1
        return index

    def walk(self, opening: int, keys: list[str]) -> int:
        """Past the bracket opening at ``opening``, gathering its direct keys.

        A slash opens a regular expression where an operand is due — after
        an opening bracket, an operator or a separator — and divides
        anywhere else, which is the reading a minifier's output supports.
        """
        depth = 0
        previous = ord("{")
        index = opening
        while True:
            byte = self.program[index]
            quoted = byte in b"\"'"
            if quoted or chr(byte).isalpha() or byte in b"$_":
                end = self.after_string(index) if quoted else self.after_word(index)
                if depth == 1 and previous in b"{," and self.program[end] == ord(":"):
                    word = self.program[index:end].decode()
                    keys.append(json.loads(word) if quoted else word)
                index, previous = end, self.program[end - 1]
                continue
            if byte == ord("`"):
                index, previous = self.after_template(index), byte
                continue
            if byte == ord("/") and previous in b"(,=:[!&|?{};":
                index, previous = self.after_regex(index), byte
                continue
            depth += (byte in b"{([") - (byte in b"})]")
            if depth == 0:
                return index + 1
            previous = previous if chr(byte).isspace() else byte
            index += 1


def claude_settings_schema(program: Path | None = None) -> SettingsSchema:
    """The keys the installed Claude Code CLI takes, read from the CLI."""
    selected = program or claude_program()
    content = selected.read_bytes()
    described = content.find(SETTINGS_SCHEMA_MARKER)
    listed = content.find(DOCUMENT_KEYS_MARKER)
    if described < 0 or listed < 0:
        raise ValueError(
            f"{selected} carries no settings schema where lup reads it (the "
            f"description {SETTINGS_SCHEMA_MARKER.decode()} and the global key "
            f"{DOCUMENT_KEYS_MARKER.decode()}); the CLI has changed how it "
            "ships them, and this reader has to follow"
        )
    opening = content.rfind(b"{", 0, content.rfind(b"$schema:", 0, described))
    keys: list[str] = []
    ScriptScan(content).walk(opening, keys)
    start = content.rfind(b"[", 0, listed)
    document = json.loads(content[start : content.find(b"]", listed) + 1])
    version = str(sh.Command(str(selected))("--version")).strip()
    return SettingsSchema(observed=version, settings=keys, document=document)
