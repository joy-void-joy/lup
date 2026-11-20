"""The runtimes lup holds sessions on, behind one interface: nothing outside this package names a runtime.

`lup.runtimes.runtime` is the interface; each runtime's own module fills it
(`claude`, `codex`), and `Core` holds them as entries of its `Runtimes`. Its
reasons are in `README.md` here.
"""
