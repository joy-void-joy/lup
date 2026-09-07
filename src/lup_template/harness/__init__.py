"""What this repository declares about the harness its own sessions run under.

The application side of :mod:`lup.harness`, and above ``devtools/`` for the
reason the library's half is: ``content/`` holds the typed skill, agent,
document and guidance declarations, ``catalog`` composes them with this
project's own hook policy into one canonical ``Harness``, and ``composition``
names the native trees that harness renders to.

None of it is a command. The Typer surface wiring generation and launch to
``lup-devtools harness ...`` is the library's, under
:mod:`lup.devtools.harness`, and it reads this rather than holding it.
"""
