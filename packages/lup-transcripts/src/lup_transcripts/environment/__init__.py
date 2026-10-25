"""Transcripts' environment side: what lup does with the records, run by `lup-dev` in a project's environment.

`lup_transcripts.environment.module` is the `Transcripts` module a project
selects, `lup_transcripts.environment.serving` what it does when a launch opens
and when it stops, and `lup_transcripts.environment.views` the kept sessions as
`lup-dev transcripts` prints them. It imports `lup_dev`, which the library side
never does (`packages/lup-transcripts/README.md`, *Layout*).
"""
