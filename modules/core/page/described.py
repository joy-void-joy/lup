"""Write what the page reads from the core, as JSON Schema, on standard output: the page's types are generated from it (`package.json`'s `types`)."""

import sys

from lup.environment.shell import described

sys.stdout.write(described())
