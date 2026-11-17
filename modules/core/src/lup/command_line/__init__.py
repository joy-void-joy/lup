"""The command line, its library side: what typing words on it did, and what its calls are handed to.

`lup <module> <method> …`, and a project's own command, parse words into a call
that crosses (`lup.running.wire`) and hand it to an answerer (`Answerer`), which
names who calls and returns the reply; the command line prints it. Parsing,
built with typer from the answerer's plan, is `lup.command_line.line`, which
nothing imports until the command line runs; the answerer in this process, and
`lup`'s and a project's scripts, are the environment's
(`lup.environment.command_line`). Its reasons are in `README.md` here.
"""

from lup.command_line.answering import Answerer, Offered, Runnable, Typed

__all__ = ["Answerer", "Offered", "Runnable", "Typed"]
