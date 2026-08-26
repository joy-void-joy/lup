"""What happened, recorded so that a later reader can answer for it.

One subject that used to be four top-level entries answering the same reader
question. The ordered record file every durable log appends to; the lossless
hash-chained audit stream a session writes as it runs; the compact markdown
trace and its sidecar a later reader skims to find a session worth opening;
the console display; the per-tool metrics; the replay divergence check; the
per-turn cost arithmetic; and the account-level metered usage. What separates
them is what each is kept *for* — evidence, navigation, or a bill — and never
the mechanism, which they share.
"""
