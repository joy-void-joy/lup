"""A git object store the installed launcher alone writes, where no container reaches.

An approved snapshot is kept as a git tree, so the thing an operator approved
has a name any git can read back -- ``git --git-dir <store> ls-tree -r <id>``
answers what was approved, without this program. The store is a bare
repository under the launcher's own state directory rather than the checkout's
object database, and that placement is the point: the checkout's objects are
writable from inside the container, so an approved tree kept there could be
deleted, pruned by an ordinary ``git gc`` once nothing references it, or
replaced under its own name -- git does not re-hash a loose object it reads.
The export a trusted launch runs from is materialized out of this store, so
the store is what stands between approval and execution.

Objects are written and read here in Python rather than through ``git``, and
that is a boundary rather than a preference. Hashing a tree through ``git``
would run it against *some* repository's configuration and attributes -- a
clean filter, an fsmonitor, a ``core.hooksPath`` -- and the only configuration
that is certainly the operator's is none at all. The format is small and
stable: a header of kind and size, a NUL, the content, deflated, stored under
its SHA-1. Every read re-hashes what it found, so a corrupt or substituted
object is refused as unreadable instead of being handed on as approved.
"""

import hashlib
import zlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

type ObjectKind = Literal["blob", "tree"]
"""The two kinds of object a snapshot is made of."""

type EntryMode = Literal["100644", "100755", "120000", "160000", "40000"]
"""A tree entry's mode, spelled the way git writes it into a tree.

A file, an executable file, a symbolic link, a submodule commit, and a
directory. Git writes a directory's mode without its leading zero, and so does
this, or the tree id would name nothing git itself would produce.
"""


class ObjectUnreadable(Exception):
    """An object a snapshot names is missing, malformed, or not what its id says."""


class TreeEntry(BaseModel, frozen=True):
    """One name in a git tree: its bytes, its mode, and the object it points at.

    The name is bytes because a path is: git stores whatever the filesystem
    held, and a name decoded to text and encoded back is a different name
    wherever the two encodings disagree.
    """

    name: bytes
    mode: EntryMode
    oid: str

    def sort_key(self) -> bytes:
        """Where git places this entry: a directory sorts as though it ended in ``/``."""
        return self.name + b"/" if self.mode == "40000" else self.name


def object_id(kind: ObjectKind, data: bytes) -> str:
    """The id git gives an object of this kind and content."""
    header = f"{kind} {len(data)}".encode("ascii") + b"\0"
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def tree_data(entries: list[TreeEntry]) -> bytes:
    """One tree object's content: every entry, in git's order, name then raw id."""
    return b"".join(
        entry.mode.encode("ascii")
        + b" "
        + entry.name
        + b"\0"
        + bytes.fromhex(entry.oid)
        for entry in sorted(entries, key=TreeEntry.sort_key)
    )


def parsed_tree(data: bytes) -> list[TreeEntry]:
    """Read a tree object's content back into its entries.

    Refused as unreadable rather than read partially: a tree that does not
    parse to the end is not a snapshot anybody approved.
    """
    modes: dict[bytes, EntryMode] = {
        b"100644": "100644",
        b"100755": "100755",
        b"120000": "120000",
        b"160000": "160000",
        b"40000": "40000",
    }
    # lup: ignore[empty-collection] — a cursor walk over one binary record, whose next offset depends on the entry just read
    entries: list[TreeEntry] = []
    offset = 0
    while offset < len(data):
        space = data.find(b" ", offset)
        nul = data.find(b"\0", space + 1)
        if space < 0 or nul < 0 or nul + 21 > len(data):
            raise ObjectUnreadable("a tree entry is truncated")
        mode = data[offset:space]
        if mode not in modes:
            raise ObjectUnreadable(f"a tree entry carries the unknown mode {mode!r}")
        entries.append(
            TreeEntry(
                name=data[space + 1 : nul],
                mode=modes[mode],
                oid=data[nul + 1 : nul + 21].hex(),
            )
        )
        offset = nul + 21
    return entries


class ObjectStore(BaseModel, frozen=True):
    """A bare repository holding every snapshot this launcher has hashed."""

    root: Path

    def prepared(self) -> "ObjectStore":
        """This store, created as a minimal bare repository if it is not one yet.

        Written by hand rather than by ``git init`` for the reason objects are:
        ``init`` copies the operator's template directory, hooks included, and
        a store nothing ever runs a command in needs none of it. What is
        written is exactly what makes ``git --git-dir`` accept the directory.
        """
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        (self.root / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        head = self.root / "HEAD"
        if not head.exists():
            head.write_text("ref: refs/heads/main\n", encoding="ascii")
        config = self.root / "config"
        if not config.exists():
            config.write_text(
                "[core]\n\trepositoryformatversion = 0\n\tbare = true\n",
                encoding="ascii",
            )
        return self

    def location(self, oid: str) -> Path:
        """Where the loose object with this id lives."""
        return self.root / "objects" / oid[:2] / oid[2:]

    def write(self, kind: ObjectKind, data: bytes) -> str:
        """Store one object, once, and answer its id.

        An object already present is left alone: its name is its content's
        hash, so a second write could only write the same bytes. A new one is
        written beside its final name and renamed into place, so a reader never
        meets half an object.
        """
        oid = object_id(kind, data)
        target = self.location(oid)
        if target.exists():
            return oid
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(
            f"{target.name}.{hashlib.sha256(data).hexdigest()}.tmp"
        )
        header = f"{kind} {len(data)}".encode("ascii") + b"\0"
        staged.write_bytes(zlib.compress(header + data))
        staged.replace(target)
        return oid

    def read(self, oid: str, kind: ObjectKind) -> bytes:
        """One object's content, verified against its own id, or a refusal.

        Everything that can be wrong is refused the same way, because the
        caller's answer is the same for all of them: this snapshot cannot be
        shown as it was approved.
        """
        target = self.location(oid)
        try:
            raw = zlib.decompress(target.read_bytes())
        except FileNotFoundError as error:
            raise ObjectUnreadable(f"object {oid} is missing") from error
        except (OSError, zlib.error) as error:
            raise ObjectUnreadable(f"object {oid} cannot be read: {error}") from error
        nul = raw.find(b"\0")
        expected = f"{kind} ".encode("ascii")
        if nul < 0 or not raw.startswith(expected):
            raise ObjectUnreadable(f"object {oid} is not a {kind}")
        data = raw[nul + 1 :]
        if raw[len(expected) : nul] != str(len(data)).encode("ascii"):
            raise ObjectUnreadable(f"object {oid} is not the size its header states")
        if object_id(kind, data) != oid:
            raise ObjectUnreadable(f"object {oid} does not hash to its own id")
        return data
