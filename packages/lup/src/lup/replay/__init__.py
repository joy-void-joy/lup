"""Durable execution journals and the divergence check on replaying one.

What differs between users is the contract attached. An environment claiming
determinism says a replay must reproduce its outcomes, so a divergence there is
a defect in a claim; an environment claiming nothing still gets the report, and
there the divergence *is* the finding — the result depended on something
outside the journal. Both are replayable; only the first is certifiable.
"""
