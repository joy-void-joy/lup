"""Named account profiles: a neutral registry plus per-engine support.

``common`` is the backend-neutral registry (name -> config dir and the
active selection, stored in ``~/.lup/profiles.json``) and the
:class:`~lup.adapters.profiles.common.ProfileSupport` ABC; each engine
module beside it (e.g. ``claude``) supplies the config-dir default and
the runner env that are properties of that backend.
"""
