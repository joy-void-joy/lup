"""The one prompt renderer, spelling each part through a runtime's vocabulary.

Rendering a prompt document is the same walk for every runtime: which parts
appear and in what order is portable, and only the words differ. Making that
walk once and asking a :class:`NativeSpellings` for each native word keeps a
new runtime a vocabulary rather than another copy of the walk, and keeps the
walk itself free of any platform's spelling. The guidance banner is composed
here for the same reason: what it has to say about the other trees is a
spelling question.
"""

from typing import assert_never

from lup.harness.banner import REGENERATE_COMMAND, GeneratedBanner
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


def guidance_banner(
    prompts: PromptRenderer, guidance: PromptDocument
) -> GeneratedBanner:
    """Name the one guidance source, and every tree that renders a copy of it.

    Each runtime reads guidance under its own name, so a reader who opens one
    copy has to be told the other is not a second document to keep in step.
    """
    every_tree = prompts.location(
        NativePath(location="guidance_file", scope="every_tree")
    )
    return GeneratedBanner(
        source=guidance.declared_source(),
        command=REGENERATE_COMMAND,
        notes=[f"Deliberately rendered as {every_tree}."],
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

    # lup: Never dispatch on the type of our own models — no `isinstance` over a
    # closed union, no `case ClassName()` arms, no `assert_never` net. Let the
    # union's base declare the operation and let each subtype decline it, so a
    # new variant is one class rather than an edit to every match. This method
    # is the canonical violation; six more walks sit at `adapters/harness.py:124`,
    # `codescan/portable.py:77`, and `harness/models.py:237,273,460,516,524`.
    # `NativeSpellings` already closes the *runtime* axis this way ("closed by
    # construction rather than by a reminder to edit two renderers") — make the
    # part axis symmetric. Write the principle into the Type Safety conventions
    # in guidance, and consider an antipattern rule for it, scoped to dispatch
    # over project `BaseModel` unions: a blanket ban would swallow the ~160
    # legitimate narrowing sites at untyped boundaries that guidance prescribes.
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
