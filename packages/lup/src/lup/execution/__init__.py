"""What carrying work out runs into, and what to do about each of it.

The retry and the throttle a flaky or rate-limited service is met with, the
executor a blocking call is handed to so work in flight outlives any one
loop's teardown, and whether a path can be written at all — or whether a
boundary owns it and something merely died holding a lock.

Every module here imports nothing else in this library, which is what makes
them one entry: they are the mechanics of running something rather than a
subject with dependencies of its own. `lup.sandbox` deliberately stays
outside for exactly that reason — a container that reads devtools, tools and
observability is a subject, and folding it in here would bury four
foundations inside one.
"""
