"""Programs this library ships to run somewhere it is not installed.

A file here is copied verbatim into a place that has neither this package nor
its settings -- inside a container, into a plugin tree -- and runs there on
the dependencies explicitly installed by their destination. They are files
rather than strings in the module that installs them: a program embedded as a
literal is one nothing lints, nothing type-checks and no test can import. Its first syntax error
is found by whoever it was copied to.

Most need only the standard library. The native clipboard helper also needs
python-xlib, Xvfb, and xauth, declared by the image's clipboard service. These
programs do not assume Lup's application dependencies; each names its boundary
in its opening comment block.
"""
