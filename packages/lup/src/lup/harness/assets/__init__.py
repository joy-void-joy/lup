"""Programs this library ships to run somewhere it is not installed.

A file here is copied verbatim into a place that has neither this package nor
its settings -- inside a container, into a plugin tree -- and runs there on
the standard library alone. That is why they are files rather than strings in
the module that installs them: a program embedded as a literal is one nothing
lints, nothing type-checks and no test can import, and its first syntax error
is found by whoever it was copied to.

They are held to the standard library and to their own readability rather
than to this repository's architecture rules, which describe a codebase these
do not run in. Each says so in its own opening comment block.
"""
