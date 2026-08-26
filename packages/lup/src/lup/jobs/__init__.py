"""Durable containerized jobs that outlive the process that submitted them.

A sandbox cell runs inside the caller's process, so the agent waits and a crash
takes the work with it; a job is submitted, left running, and asked about later
— possibly by a process started after that crash. Everything durable is on the
filesystem, and the scheduler's atomically-replaced view is deliberately
separate from the terminal result the container writes, so a job cannot forge
its own completion.
"""
