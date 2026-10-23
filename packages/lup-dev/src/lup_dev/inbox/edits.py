"""An edit of what an agent sent the operator: a passage of its text replaced, as a file's edit replaces one.

`docs/inbox.md`, *Editing what was sent*. An agent's `edit` names a passage of
its item's text exactly as it stands, found there once, and what replaces it,
or gives its text whole (`Delivery.edited`): the passage it names is the one
place an edit changes, so a citation fixed changes nothing else of a message
the operator may be reading.
"""

from lup_dev.inbox.store import InboxError, cited


def replaced(text: str, old: str, new: str, number: int) -> str:
    """Return `text`, item `number`'s, with `old`, a passage of it found there once, replaced by `new`.

    Raise `InboxError` where `old` is empty, isn't in `text` as written, or is
    in it more than once, saying which.

    >>> replaced("See @820.9[split].", "@820.9[split]", "@820.2[split]", 7)
    'See @820.2[split].'
    >>> replaced("a a", "a", "b", 7)
    Traceback (most recent call last):
    ...
    lup_dev.inbox.store.InboxError: `old` is in @7's text 2 times: give more of it, so it's found once
    """
    found = text.count(old) if old else 0
    if found == 0:
        message = (
            f"{cited(number)}'s text doesn't hold `old` as written: give a passage "
            "of it exactly as it stands"
        )
        raise InboxError(message)
    if found > 1:
        message = (
            f"`old` is in {cited(number)}'s text {found} times: give more of it, so "
            "it's found once"
        )
        raise InboxError(message)
    # lup: ignore("string-replace", why="an edit replaces the one passage of an item's text its sender gave exactly as written, checked found there once, as a file's edit does")
    return text.replace(old, new, 1)
