"""Running more than one piece of work, and staying able to speak to it.

A cohort of addressable held sessions with mail that lands in front of each
one's next tool call; a background agent that coalesces wakes into turns; a
scheduler and relay for work that sleeps; durable out-of-process jobs; the
review gates a turn passes through; and spec-driven delegation for runtimes
whose own subagents will not do.

One subject that used to be five top-level entries all plausibly answering
"run work concurrently". What separates them is not the concurrency, which
they share, but who holds the work: this process, another process, or a model
in a session of its own.
"""
