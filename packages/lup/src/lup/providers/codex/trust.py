"""What Codex says about one home's hooks, and how a home records trust.

A hook runs only where the home trusts it, per event and per hash, and Codex
*skips* an untrusted one rather than refusing it -- so a home carrying the
plugin with trust for one event of six runs every session past the five it
never granted, and says nothing about it.

Answering which those are here means constructing each trust record's name
from the manifest, over a table pairing the manifest's spelling of an
event with the record's. The table is the part that cannot hold. The
manifest is generated, so an event added to it is named nowhere here, and
the reader raises on this repository's own plugin instead of answering
about it -- which is the whole gate for a session an application opens.

So the question goes to the runtime that owns both spellings. ``hooks/list``
resolves the hooks for one working directory and reports, per hook, the
record's ``key``, the ``currentHash`` a record must carry, and the
``trustStatus`` Codex would act on. That is the entire answer, it is keyed
the way the home is keyed, and it leaves nothing here to keep in step with a
manifest.

Reading the hash is also what makes recording trust possible at all. A
record carries a digest of the hook definition, computed by Codex over a
canonical form this does not own; reimplementing it would produce records
that read as ``modified`` and are skipped exactly like absent ones. Handed
the hash, a launcher records trust for the plugin it generated moments
earlier, in a home it made for this checkout -- the same act, and the same
reasoning, as :func:`lup.providers.codex.home.trust_project`.
"""

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lup.providers.codex.app_server import CodexAppServer
from lup.providers.codex.login import CODEX_HOME
from lup.types import JsonObject

# lup: ignore[constant-declaration] — the app-server method Codex answers to
HOOKS_LIST = "hooks/list"
"""The request whose reply :class:`CodexHook` is read from."""


type CodexHookTrust = Literal["managed", "untrusted", "trusted", "modified"]
"""Every verdict Codex reaches about one hook definition it has been given.

``modified`` is the one a table of names cannot see and the one a generated
plugin meets constantly: trust was granted, the declaration was regenerated,
and the recorded digest now describes bytes that are gone.
"""


class CodexHook(BaseModel, frozen=True):
    """One resolved hook, as the runtime reports it for a working directory."""

    key: str
    """The name the home records trust under, spelled by whoever reads it."""

    event_name: str = Field(alias="eventName")
    plugin_id: str = Field(alias="pluginId", default="")
    source: str
    enabled: bool
    is_managed: bool = Field(alias="isManaged")
    current_hash: str = Field(alias="currentHash")
    trust_status: CodexHookTrust = Field(alias="trustStatus")

    def runs(self) -> bool:
        """Whether Codex would actually execute this hook as the home stands.

        Both halves are load-bearing and they fail differently: a disabled
        hook was turned off on purpose, an untrusted one was never answered
        for. Either way the dispatcher is present and never consulted, which
        is the failure this whole module exists to make visible.
        """
        return self.enabled and self.trust_status in ("trusted", "managed")


class CodexHookListing(BaseModel, frozen=True):
    """What one working directory resolves to, including what it could not."""

    cwd: str
    hooks: list[CodexHook] = []
    warnings: list[str] = []
    errors: list[JsonObject] = []


class CodexHookReport(BaseModel, frozen=True):
    """Every listing one request asked for."""

    data: list[CodexHookListing] = []

    def resolved(self) -> list[CodexHook]:
        """Every hook across every directory asked about."""
        return [hook for listing in self.data for hook in listing.hooks]

    def unresolved(self) -> list[str]:
        """Everything the runtime could not resolve, said in its own words.

        Carried rather than dropped because the states it reports are the
        ones a reader would otherwise diagnose as absence: a manifest that
        would not parse and a plugin whose cache is gone both arrive here as
        a directory with no hooks in it.
        """
        return [*self.warnings(), *(str(error) for error in self.failures())]

    def warnings(self) -> list[str]:
        """Native adjustments that do not themselves report failed loading."""
        return [warning for listing in self.data for warning in listing.warnings]

    def failures(self) -> list[JsonObject]:
        """Native errors leave hook discovery incomplete."""
        return [error for listing in self.data for error in listing.errors]


async def read_hooks(
    home: Path,
    cwd: Path,
    executable: Path = Path("codex"),
    arguments: list[str] | None = None,
    timeout_seconds: float = 120.0,
) -> CodexHookReport:
    """Ask one home which hooks it would run for one working directory.

    A connection rather than a file read, because trust is the runtime's
    verdict over state in two places -- the home's own records and the
    plugin cache the records name -- and only one of those is a file this
    could have read.
    """
    server = CodexAppServer(
        executable, arguments=arguments, environment={CODEX_HOME: str(home)}
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            await server.start()
            return CodexHookReport.model_validate(
                await server.request(HOOKS_LIST, {"cwds": [str(cwd)]})
            )
    finally:
        await server.close()


def hook_wire_fields() -> list[str]:
    """Every field this reads off a ``hooks/list`` reply, as Codex spells it.

    Read off the model rather than listed beside it. A second declaration of
    the same names is free to fall behind the first, which is precisely the
    failure a hand-kept table of these names would carry.

    What it is for: a rename on this reply fails *open*. Trust would be
    seeded against a field that is no longer there, every hook would resolve
    untrusted, and the session would run with the dispatcher present and
    never consulted -- so the doctor is given the names to check rather than
    the next operator being given the symptom.
    """
    return sorted(field.alias or name for name, field in CodexHook.model_fields.items())


def hooks_of(report: CodexHookReport, selector: str) -> list[CodexHook]:
    """Only the hooks one plugin declared, out of everything a home resolves.

    A home carries the operator's own hooks beside this plugin's, and those
    are theirs: an untrusted one of theirs is a decision they have not made
    yet rather than a session this project should refuse.
    """
    return [hook for hook in report.resolved() if hook.plugin_id == selector]


def skipped(report: CodexHookReport, selector: str) -> list[CodexHook]:
    """Which of one plugin's hooks the home resolves and would not run."""
    return [hook for hook in hooks_of(report, selector) if not hook.runs()]
