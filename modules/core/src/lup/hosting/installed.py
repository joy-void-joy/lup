"""The declaration the machine's parts run from where no home repository is named: lup's default modules, `Hosting` and `Sessions`, as the installed `lup` ships them.

Whoever only builds with lup never names a home repository: installing `lup` is
approving its code, so the machine's parts run from the installed package
itself (`lup/hosting/README.md`, *The loader*), and they start sessions as the
home repository's would.
"""

from lup.declaration.module import Modules
from lup.declaration.project import Project
from lup.hosting.module import Hosting
from lup.sessions.part import Sessions

project = Project(modules=Modules.default().add(Hosting(), Sessions()))
