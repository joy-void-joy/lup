"""What a run keeps, and how two processes reach the same copy of it.

The slot, stream, cursor and wait a producer and a reader meet over, and the
workspace a session's context, history, notes and paths are kept in. One
subject: state that outlives the call that wrote it, and the atomicity that
makes reading it while it is being written a defined thing rather than a race.

Not the durable record itself — an ordered log is kept for a reader to answer
for what happened, which is :mod:`lup.observability`'s subject rather than
this one.
"""
