"""Named account profiles: one ``select`` verb, per-engine implementations.

``Profile`` holds the
:class:`~lup.adapters.profiles.Profile.Profile` ABC —
``select(name, client)`` returns a client running as the named account —
and each implementation beside it (e.g. ``claude``) owns everything else
about its accounts, storage included.
"""
