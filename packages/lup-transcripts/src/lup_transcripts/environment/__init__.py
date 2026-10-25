"""Transcripts' environment side: what lup does with the records, run by `lup-dev` in a project's environment.

`lup_transcripts.environment.module` is the `Transcripts` module a project
selects, `lup_transcripts.environment.serving` what it does when a launch opens
and when it stops, `lup_transcripts.environment.views` the kept sessions as
`lup-dev transcripts` prints them, and `lup_transcripts.environment.conversation`
a conversation laid out in lup's building blocks, as its drawer shows it. It
imports `lup_dev`, which the library side never does
(`packages/lup-transcripts/README.md`, *Layout*).
"""
