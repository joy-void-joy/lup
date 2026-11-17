"""How lup runs a project's modules, its environment side: planning a declaration, and the program a container runs.

`python -m lup.environment.running` is that program: given what to do as one
JSON message on its input, it prints a declaration's plan, or starts a
project's parts and answers calls on a socket until it's stopped
(`lup/running/README.md`).
"""
