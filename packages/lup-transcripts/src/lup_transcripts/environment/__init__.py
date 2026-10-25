"""Transcripts: every session's record kept, out of reach of the runtime's cleanup, and readable by later sessions.

A module with an environment side only: `lup.transcripts.module` is the
`Transcripts` module a project selects, and `lup.transcripts.serving` what it
does when a launch opens and when it stops.
"""
