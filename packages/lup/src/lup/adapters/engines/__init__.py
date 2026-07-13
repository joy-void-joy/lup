"""The engine concept: the ``Engine`` ABC and one shipped implementation per file.

Every engine method body is a lazy one-liner into the implementation
module that owns the work — the per-engine ``create_*``/``build_*`` doors
under ``lup.adapters.clients.*`` and ``lup.adapters.background.*`` — so
importing an engine loads no SDK. The compat engines compose their base
engine (an ``Engine`` wrapping an ``Engine``), supplying only the client
construction that points it at the compatible endpoint.
:mod:`lup.adapters.wiring` assembles the shipped engines into the
``ENGINES`` and ``MODEL_ROUTES`` routers.
"""
