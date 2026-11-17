"""The program a container runs: `python -m lup.environment.running`, what to do read as one JSON message on its input.

Asked to plan, it prints the declaration's plan as JSON and ends; asked to
start, it starts the parts named and answers calls on its socket until it's
stopped.
"""

import asyncio
import sys

from pydantic import TypeAdapter

from lup.environment.running.container import served
from lup.environment.running.planning import planned
from lup.running.wire import Asked, Planning, Start, read


def main() -> None:
    """Do what the input asks: print a plan, or serve a project's parts until stopped."""
    asked = read(sys.stdin.buffer.read(), TypeAdapter[Asked](Asked))
    match asked:
        case Planning(root=root, declaration=declaration):
            sys.stdout.write(planned(root, declaration).model_dump_json() + "\n")
        case Start():
            asyncio.run(served(asked))


main()
