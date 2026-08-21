"""What the boundary has been widened for, and which of it nobody uses.

A boundary that answers every refusal by widening its own declaration has an
obvious failure mode and no natural corrective. Each entry is perfectly
defensible when it is written -- something really was refused, and the widening
really did fix it -- and nobody afterwards can say whether it is still needed,
because the thing that needed it may have been deleted a year ago. Left alone,
mounts and allowed hosts accrete until the declaration describes a boundary
nobody would choose, arrived at one defensible step at a time.

So the entries carry what motivated them, and this reads the boundary's own
records to say which of them nothing has exercised. Two questions, and only
the first can be answered from the declaration alone:

**Which entry never said why.** Cheap, exact, and the one worth asking on
every check -- an entry with no reason cannot be argued about later, so the
argument is had now, while somebody still remembers.

**Which entry nothing has reached.** Read out of the proxy's access log,
which records every destination a session actually contacted. Evidence rather
than inference: an allowed host with no line of its own has not been reached
since the proxy started, whatever anybody believes about it.

Advisory throughout. An unexercised entry is a question, not a defect: a host
reached only by a command nobody has run this week is still needed, and a
check that failed on it would teach people to stop reading the check.
"""

from pydantic import BaseModel, Field

import sh

from lup.harness.egress import SessionEgress
from lup.harness.image import Image, detected_client


class Unexercised(BaseModel, frozen=True):
    """One widening of the boundary, and what is not known about it."""

    entry: str = Field(description="The host or path the declaration admits")
    finding: str = Field(description="What could not be established about it")

    def line(self) -> str:
        """This finding as one line of the check's report."""
        return f"  {self.entry}: {self.finding}"


def proxy_log(proxy: str) -> list[str]:
    """Every line the egress proxy has written, or nothing when it is not up.

    Asked of the running container rather than of a file, because the proxy
    logs to its own stdout precisely so that nothing has to agree with it
    about a path. A proxy that is not running yields nothing, and nothing is
    the honest answer -- there is no evidence either way, which is different
    from evidence of disuse and is reported as such.
    """
    engine = detected_client()
    if engine is None:
        return []
    try:
        written = sh.Command(engine.binary)("logs", proxy)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return []
    return str(written).splitlines()


def survey(
    image: Image, project: str, reached: list[str] | None = None
) -> list[Unexercised]:
    """Everything the boundary admits that nothing here can justify.

    ``reached`` is the proxy's log, taken as an argument so a caller that
    already has it -- or a test, which must not go looking for a container --
    supplies its own rather than this reaching for a runtime to answer a
    question about a declaration.
    """
    egress: SessionEgress = image.egress
    lines = proxy_log(egress.proxy_name(project)) if reached is None else reached
    return [
        *[
            Unexercised(entry=item.host, finding="admitted, but nothing says why")
            for item in egress.admits
            if not item.because
        ],
        *[
            Unexercised(
                entry=item.host,
                finding=f"admitted for {item.because}, and the proxy has not "
                "been asked for it once",
            )
            for item in egress.admits
            if item.because and lines and not any(item.host in line for line in lines)
        ],
        *[
            Unexercised(entry=cache.path, finding="mounted, but nothing says why")
            for cache in image.caches
            if not cache.because
        ],
    ]


def report(findings: list[Unexercised]) -> list[str]:
    """The survey as the lines a check prints, or nothing when there are none."""
    if not findings:
        return []
    return [
        f"boundary accretion: {len(findings)} entry(s) nothing here justifies",
        *[finding.line() for finding in findings],
    ]
