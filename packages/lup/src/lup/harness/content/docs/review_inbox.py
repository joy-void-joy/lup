"""Reference owned by the optional browser review module."""

from lup.harness.models import Passage, PromptDocument

DOCUMENT = PromptDocument(source=__name__, parts=[Passage(module=__name__)])
