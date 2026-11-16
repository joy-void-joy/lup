"""The doors' library side: what a module's methods are reached through, and who may ask them.

`lup` re-exports the doors (`lup.tool`, `lup.action`, `lup.command`) and the
callers a method's `by` names; serving a module's methods and calling them
through their doors is the environment's (`lup.environment.doors`). Its reasons
are in `README.md` here.
"""
