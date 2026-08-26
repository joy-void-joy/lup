"""Local web surfaces: the boundaries a page served on this machine keeps.

What a page served on this machine does to stay local-only: the loopback bind
refusal, the `Host` check that DNS rebinding would otherwise walk past, and the
browser round-trip an installed OAuth client needs. One subject — a local HTTP
surface a browser reaches — and the OAuth half is reached by a downstream
project rather than by anything here, which is the outward test answering in
the affirmative. The two user-facing pages, `devtools/dashboard` and
`devtools/supervisor`, sit *on* this; it does not belong beside them.
"""
