"""The program a container runs: `python -m lup.environment.running`, what to do read as one JSON message from `LUP_ASKED`, or else its input.

Asked to plan, it prints the declaration's plan as JSON and ends; asked to
start, it starts the parts named and answers calls on its socket until it's
stopped; asked to host, it starts the machine's own parts, on the operator's
machine, and carries every call until it's stopped.
"""

import asyncio
import sys

from pydantic import TypeAdapter

from lup.environment.running.container import served
from lup.environment.running.machine import hosted
from lup.environment.running.planning import planned
from lup.environment.running.settings import Running
from lup.running.wire import Asked, Host, Planning, Start, read


def main() -> None:
    """Do what the input asks: print a plan, or serve a project's parts until stopped."""
    told = Running().lup_asked
    text = told.encode() if told is not None else sys.stdin.buffer.read()
    asked = read(text, TypeAdapter[Asked](Asked))
    match asked:
        case Planning(root=root, declaration=declaration):
            sys.stdout.write(planned(root, declaration).model_dump_json() + "\n")
        case Start():
            asyncio.run(served(asked))
        case Host():
            # lup: defer(issue=3, why="the machine's runner of programs, over `lup.programs` once it lands from module-contract-rest: until then a machine part's program is refused, saying nothing runs it")
            asyncio.run(hosted(asked, runs=None))


main()
