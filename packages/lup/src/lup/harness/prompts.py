"""The one prompt renderer, spelling each part through a runtime's vocabulary.

Rendering a prompt document is the same walk for every runtime: which parts
appear and in what order is portable, and only the words differ. The walk asks
each part to spell itself and hands it the vocabulary to do so, which keeps a
new runtime a :class:`NativeSpellings` rather than another copy of the walk, a
new kind of part one class rather than an arm here, and this module free of
both any platform's spelling and any part's identity.
"""

from lup.harness.contracts import NativeSpellings, PromptRenderer
from lup.harness.models import LocatedPart, PromptDocument


class SpelledPromptRenderer(PromptRenderer):
    """Render every part through the vocabulary of the runtime that reads it.

    ``every`` carries the other runtimes so a location can teach every tree at
    once. That rendering is identical whichever runtime produces it, because
    the product names come from the vocabularies themselves.
    """

    def __init__(self, own: NativeSpellings, every: list[NativeSpellings]) -> None:
        self.own = own
        self.every = every

    def render(self, prompt: PromptDocument) -> str:
        text = "".join(part.spell(self) for part in prompt.parts)
        return text if text.endswith("\n") else text + "\n"

    def location(self, part: LocatedPart) -> str:
        """Spell one location for the reader, or for every runtime at once."""
        match part.scope:
            case "this_tree":
                return part.spell_in(self.own)
            case "every_tree":
                return ", ".join(
                    f"{part.spell_in(runtime)} under {runtime.runtime_name}"
                    for runtime in self.every
                )
