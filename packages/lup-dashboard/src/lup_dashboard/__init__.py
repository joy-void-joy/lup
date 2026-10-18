"""lup's dashboard: where the operator works with every agent, in one page.

`docs/dashboard.md`. A process of its own, which the host service starts as its
child, serving the page and its API on localhost. The page asks the host service
through it exactly what the operator's commands ask, the host's own control
requests, and watches them as they change (`lup_dev/host/watch.py`), so it shows
nothing a command couldn't fetch.
"""
