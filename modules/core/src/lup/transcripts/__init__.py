"""Transcripts: every session's record, on both runtimes, read in place, indexed, and searched with the operator's words through lup among it.

What a view of it takes is offered here, as a module's promises and code read
it; the module itself is `lup.Transcripts`. Its reasons are in `README.md` here.
"""

from lup.transcripts.index import Listing, Searching, Showing

__all__ = ["Listing", "Searching", "Showing"]
