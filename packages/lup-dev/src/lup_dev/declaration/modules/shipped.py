"""The modules lup ships: the ones on by default, and every one.

`Modules.default()` and `Modules.all()` are recorded as they're written, and
resolved against these lists when the declaration is read, so a module a later
release adds to the default comes in, and `Modules.only(…)` keeps it out.
"""

from typing import TYPE_CHECKING

from lup.github.module import GitHub
from lup_dev.declaration.modules.code_rules import CodeRules
from lup_dev.declaration.modules.core import Core
from lup_dev.declaration.modules.python import Python
from lup_dev.private.module import Private
from lup_transcripts.environment.module import Transcripts

if TYPE_CHECKING:
    from lup_dev.declaration.module import Module


def default() -> list[Module]:
    """List lup's default modules, in their order."""
    return [Core(), Python(), CodeRules(), GitHub(), Transcripts(), Private()]


def shipped() -> list[Module]:
    """List every module lup ships: the default ones, then the optional ones.

    lup ships no optional module yet.
    """
    return default()
