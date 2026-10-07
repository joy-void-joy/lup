"""Build with Claude and Codex agents from code.

`lup` is what a project's production code imports, as opposed to `lup_dev`, which
the project uses only while it's being developed. It grows to hold
(`DESIGN.md`, *Calling agents from code*):
- clients for Claude and Codex, whose `ask` returns a typed answer, and
  conversations with their history;
- tools written as plain Python functions;
- rooms: an agent working on a task inside a container, waited on, left running
  as a spawned session, or opened in a terminal;
- coordination between the agents a project runs, and request budgets shared
  across processes;
- runs, durable work that outlives the call that started it, and the outcome
  loop that compares versions of a project's agents by how they fared;
- traces and cost for every call;
- a fake agent, and a guard that keeps tests from reaching real agents or the
  network.

For now it holds the shared types every model and settings class builds on
(`lup.types`); the clients come with the library's first slice (`docs/library.md`).
"""
