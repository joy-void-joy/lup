"""The environment for developing a project with agents.

`lup_dev` is what a project uses only while it's being developed, as opposed to
the library `lup`, which the project's production code imports. Everything it
raises descends from `lup_dev.errors.LupDevError`.
"""
