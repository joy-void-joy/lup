"""The one prompt renderer, spelling each part through a runtime's vocabulary.

Rendering a prompt document is the same walk for every runtime: which parts
appear and in what order is portable, and only the words differ. Making that
walk once and asking a :class:`NativeSpellings` for each native word keeps a
new runtime a vocabulary rather than another copy of the walk, and keeps the
walk itself free of any platform's spelling.
"""

from typing import assert_never

from lup.harness.contracts import NativeSpellings, PromptRenderer
from lup.harness.models import (
    ArgumentsRef,
    AskUser,
    Delegate,
    NativePath,
    PluginPath,
    PromptDocument,
    PromptPart,
    RelocateSession,
    RequestApproval,
    ResolverEntry,
    RuntimeDocs,
    SkillInvocation,
    SkillPattern,
    TextPart,
)


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
        text = "".join(self.spell(part) for part in prompt.parts)
        return text if text.endswith("\n") else text + "\n"

    def location(self, part: NativePath | PluginPath) -> str:
        """Spell one location for the reader, or for every runtime at once."""

        def spelled(runtime: NativeSpellings) -> str:
            match part:
                case NativePath(location=location):
                    return runtime.tree(location)
                case PluginPath(plugin=plugin, location=location, member=member):
                    return runtime.plugin(plugin, location, member)

        match part.scope:
            case "this_tree":
                return spelled(self.own)
            case "every_tree":
                return ", ".join(
                    f"{spelled(runtime)} under {runtime.runtime_name}"
                    for runtime in self.every
                )

    def spell(self, part: PromptPart) -> str:
        """Render one part, reaching the runtime for every native word."""
        match part:
            case TextPart(text=text):
                return text
            case SkillInvocation():
                return self.own.render(part)
            case NativePath() | PluginPath():
                return self.location(part)
            case SkillPattern(plugin=plugin, placeholder=placeholder):
                return self.own.invocation_pattern(plugin, placeholder)
            case RuntimeDocs():
                return self.own.runtime_docs()
            case AskUser(question=question):
                return self.own.ask_user(question)
            case Delegate(subagent_type=subagent_type, prompt=prompt):
                return self.own.delegate(subagent_type, prompt)
            case RequestApproval(action=action, reason=reason):
                return self.own.request_approval(action, reason)
            case RelocateSession(path=path):
                return self.own.relocate_session(path)
            case ResolverEntry():
                return self.own.resolver_entry()
            case ArgumentsRef():
                return self.own.arguments_ref()
            case _ as unhandled:
                assert_never(unhandled)
