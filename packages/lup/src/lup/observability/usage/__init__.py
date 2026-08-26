"""The usage display, and the report shape every runtime fills it from.

One account's metered usage, whichever runtime billed it: the windows a plan
meters and when each clears, where the tokens went day by day, and the display
that draws both. Ships no roster — each adapter declares the entry that reads
its own runtime into this shape, so a runtime joins the display by being read
rather than by growing a command beside it.

An account's metered windows and its day-by-day tokens are the same two
questions on every runtime that bills a subscription, so the report, the
pacing bars, the machine-readable snapshot, and the three display modes live
here once. What differs — a credential, an endpoint, a wire shape, how a
model family is named — reaches this through a :class:`~lup.observability.usage.models
.UsageReader` in the adapter that owns it.
"""
