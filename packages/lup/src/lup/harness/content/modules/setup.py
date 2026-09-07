"""Interactive configuration: keys, integrations, profiles.

The wizard and the local page are one subject seen twice — the dashboard is
literally "host the local setup dashboard", the same declarations rendered for
somebody who would rather click than answer prompts. Keeping them in one
module is what stops a project from declining one and keeping the other, which
would leave a page serving a wizard nobody can run.

This is deliberately *not* ``template-init``'s. Standing a project up happens
once; configuring its keys and integrations happens whenever a key rotates, so
a project that finished initializing and declined the init skills still has
every reason to keep this.
"""

from lup.harness.content.modules.specs import SETUP
from lup.harness.modules import Module


def module() -> Module:
    """Interactive configuration as one value."""
    return Module(spec=SETUP)
