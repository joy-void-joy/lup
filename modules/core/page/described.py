"""Write, on standard output, what the page reads from the core as JSON Schema (`schema`), or the kinds the core declares (`looks`): the page's types are generated from the one (`package.json`'s `types`), and its promises lay their blocks out with the other, so neither can drift from the core."""

import sys

from lup.core import Core
from lup.environment.shell import Looks, described

match sys.argv[1:]:
    case ["schema"]:
        sys.stdout.write(described())
    case ["looks"]:
        sys.stdout.write(Looks.of([Core()]).model_dump_json(indent=2))
    case _:
        sys.exit("described.py takes `schema` or `looks`")
