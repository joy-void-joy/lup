# Publishing

What's about to leave under the operator's name, told to every part of the project hearing it before it leaves: `Publishing`, an event a module's methods hear through `@lup.on`. `remote` fires it before each push, and `github` before each post. A method hearing it may refuse, raising `RefusedError` with the words the agent reads instead, and then nothing leaves; one that fails refuses too, since a check that didn't run let nothing through.

```python
import lup
from lup.publishing.events import Publishing


class Guard(lup.Part):
    """Refuses what names the operator's host."""

    @lup.on(Publishing)
    async def heard(self, publishing: Publishing) -> None:
        """Refuse a post or a push naming the host."""
        ...
```

It carries what would leave as text, so a part hearing it reads nothing of the repository's, and runs wherever its holdings put it:
- **a push** (`Push`): the remote, by its name in the repository's configuration, the ref it updates, and one commit the remote lacks, each in an event of its own, so a first push of a long history isn't one message: its id, its message, and each file it adds or changes, with the lines it adds against each parent (a merge's resolution, never what a parent brought), or its bytes whole where it isn't text. A push publishing no commit, a ref moved to one the remote holds, is told once with none, for its ref's name;
- **a post** (`Post`): what it is, in a few words, and each of its parts, a title and a body.

A refusal says where it found what it refuses, by its kind, never the value itself: a part hearing it knows what's private, and the agent reading the refusal needn't.
