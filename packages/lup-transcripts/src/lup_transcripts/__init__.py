"""Transcripts: every session's record kept, out of reach of the runtime's cleanup, and readable by later sessions.

The module's library side, what code calling agents may import: its root error
alone (`lup_transcripts.errors`). What the module does runs in a project's
environment, in its environment side, `lup_transcripts.environment`, which this
package never imports (`packages/lup-transcripts/README.md`, *Layout*).
"""
