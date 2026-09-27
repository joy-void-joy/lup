"""Launching a declared agent: the vocabulary both compilations of one declaration read.

An agent declared as :class:`~lup.providers.claude.Claude` or
:class:`~lup.providers.codex.Codex` is compiled twice from the same fields:
into SDK options when a program opens a session in process, and into the
``(argv, env, cwd)`` an interactive CLI runs when a person launches one. What
the two compilations share without being either provider's lives here:

- :mod:`lup.launch.declaration` — the fields a launch adds to a declaration
  (the sandbox and its mounts, the coordination identity, the recording, the
  session a launch reopens) and the command a launch compiles to.
- :mod:`lup.launch.foreground` — running that command in the foreground with
  the terminal inherited, between the lifecycle steps a repository adds.
- :mod:`lup.launch.boundary` — vouching for the inner sandbox and settling
  the boundary a launch opens behind, the same for every runtime.

Each provider's own spelling of the same fields sits beside its adapter, in
``lup.providers.<runtime>.launch``.
"""
