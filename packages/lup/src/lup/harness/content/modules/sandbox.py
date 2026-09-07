"""The confined execution a session is offered.

Tools and policy, and nothing else — no skill, no sub-app, no page of its
own, its prose folded into the permissions page core publishes. The second of
the two modules that exist to prove a subject need not reach a project through
content at all: what a session gets from this is a tool group and a rule about
what may leave the confinement, both of which arrive without anybody reading
anything.
"""

from lup.harness.content.modules.specs import SANDBOX
from lup.harness.modules import Module


def module() -> Module:
    """Confined execution as one value."""
    return Module(spec=SANDBOX, tool_groups=["sandbox"])
