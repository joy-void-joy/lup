"""The judge's review, parked in the first lup's dashboard through its host half.

A bridge: until lup's own dashboard exists, `lup-dev install` shows the operator
the judge's source in the first lup's review dashboard, where the interim review
hook shows them an agent's calls (`docs/judging-writes.md`, *The judge's review,
in the dashboard*). Only `lup_dev.cli` imports this module; it goes, with its
setting, when lup's own dashboard lands as another `Reviewer`.

The first lup's host half (`policy/assets/host.py` in its checkout) uses only the
standard library, so it's loaded by path, and the dashboard reads exactly the
records it writes. What it answers is modelled here, read against the host at
`40c2d28`:
- the review is one `Propose`: each changed file whole at `HEAD`, its text at the
  commit approved last recorded as the review's precondition; the dashboard works
  out the diff;
- the before side is exported into the checkout (`CheckoutLayout.install_review`)
  and the review's paths are there, since the dashboard retires a review whose
  recorded files don't stand on disk as recorded; line comments come back to the
  checkout's paths;
- the dashboard expires a review an hour after it's parked when its requester
  isn't on the first lup's roster, which `lup-dev install` never is, so an expired
  review is parked again under another id, and the remarks on each id are read;
- an approval is spent through the host, as an agent's repeated call spends it,
  so the dashboard records the review as carried out;
- the host offers no way to withdraw a review, so Ctrl-C removes the export, and
  the dashboard retires the review as stale at its next look.
"""

import importlib.util
import shutil
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Literal, override

import typer
from pydantic import TypeAdapter

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.install import Answer, InstallError, LineComment, Review, Reviewer
from lup_dev.layout import CheckoutLayout
from lup_dev.policy.store import Git

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup_dev.settings import LupDevSettings


class Parked(Model):
    """What the host half answers when it's asked to park a review."""

    state: Literal["pending", "approved", "rejected", "unavailable"]
    """`pending` while the review waits; `approved` once its approval is spent;
    `rejected` once it's declined; `unavailable` where it can't be parked."""
    id: str
    reason: str


class Entry(Model):
    """A review as the first lup's relay keeps it: the part a wait reads."""

    id: str
    state: str
    """`pending` while it waits; `expired`, `stale` or another state once it left."""
    outcome: str = ""
    """Why it left the queue, where the relay says."""


class HostComment(Model):
    """A line comment as the first lup keeps it, on a file where the page shows it."""

    path: Path
    start: int
    end: int
    side: Literal["before", "after"] = "after"
    note: str

    def comment(self, export: Path) -> LineComment:
        """Return the comment on the file's path in the checkout, out of `export`."""
        path = (
            self.path.relative_to(export)
            if self.path.is_relative_to(export)
            else self.path
        )
        return LineComment(
            path=path, first=self.start, last=self.end, side=self.side, note=self.note
        )


class HostSaid(Model):
    """What the operator wrote on a review, as the first lup keeps it."""

    note: str = ""
    comments: list[HostComment] = []


class HostAnswer(HostSaid):
    """The operator's decision on a review, with what they wrote."""

    approved: bool


class RecordedAnswer(Model):
    """An answer as the host keeps it, naming the review it settles."""

    question: str
    answer: HostAnswer


class RecordedRemark(Model):
    """A remark the operator sent without deciding, as the host keeps it."""

    question: str
    remark: HostSaid


class ProposedFile(Model):
    """One file of a `Propose`: where it is, and the text it becomes."""

    path: Path
    content: str | None
    """Its text at `HEAD`; none where the change deletes it."""
    about: str = ""


class Proposal(Model):
    """What a `Propose` carries: why, and every file it changes."""

    why: str
    files: list[ProposedFile]


class Call(Model):
    """The judge's review as the host half parks it.

    The same at every park, so the host recognizes it again by its fingerprint: a
    review still waiting is found again rather than parked twice, and an answer
    given to it is read back.
    """

    root: Path
    """The checkout of lup being installed: the review's relay is kept there."""
    requester: str
    proposal: Proposal
    preconditions: dict[Path, str | None]
    """Each file's text at the commit approved last, by its path in the export."""
    reason: str
    answers: Path
    """The host's file of the operator's answers and remarks on the relay's reviews."""


class Host(Model, arbitrary_types_allowed=True):
    """The first lup's host half, loaded from its checkout, which parks reviews."""

    module: ModuleType

    @classmethod
    def load(cls, source: Path) -> Host:
        """Load the host half from its file at `source`."""
        spec = importlib.util.spec_from_file_location("lup_legacy_host", source)
        if spec is None or spec.loader is None:
            message = f"Python can't load {source} as a module"
            raise InstallError(message)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return cls(module=module)

    def relay(self, root: Path) -> Path:
        """Say where the reviews parked from `root` are kept, for dashboards to read."""
        return Path(self.module.review_home(root)) / ".lup" / "questions.jsonl"

    def answers(self, relay: Path) -> Path:
        """Say where the operator's answers and remarks on the relay's reviews go."""
        home = self.module.review_answers_home("LUP_REVIEW_ANSWERS")
        return Path(self.module.review_answers(relay, home))

    def park(self, call: Call) -> Parked:
        """Park the review, or read back the review already parked for it.

        An approval read back is spent: the host claims it, once.
        """
        preconditions = TypeAdapter(dict[Path, str | None]).dump_json(
            call.preconditions
        )
        try:
            return Parked.model_validate(
                self.module.review_hook_call(
                    call.root,
                    call.requester,
                    "Propose",
                    call.proposal.model_dump_json(),
                    preconditions.decode(),
                    call.reason,
                    "lup-dev-install",
                    "quality_review",
                    "human_only",
                    answers=str(call.answers),
                )
            )
        except ValueError as failure:
            message = f"the first lup's host half couldn't park the review: {failure}"
            raise InstallError(message) from failure

    def spend(self, call: Call, review: str) -> None:
        """Spend the approval of `review`, so the dashboard records it as carried out.

        The host claims an approval when the review is parked again, once.
        """
        spent = self.park(call)
        if spent.state != "approved" or spent.id != review:
            message = (
                f"your approval of review {review} couldn't be spent through the first "
                f"lup's host half: it answered {spent.state} for review {spent.id}"
            )
            raise InstallError(message)

    def entries(self, relay: Path) -> dict[str, Entry]:
        """Return the reviews kept in the relay at `relay`, by id."""
        try:
            return TypeAdapter(dict[str, Entry]).validate_python(
                self.module.native_review_records(relay)
            )
        except ValueError as failure:
            message = f"the first lup's relay at {relay} can't be read: {failure}"
            raise InstallError(message) from failure

    def records(self, answers: Path) -> list[RecordedAnswer | RecordedRemark]:
        """Return the answers and remarks kept in `answers`, oldest first."""
        try:
            return TypeAdapter(list[RecordedAnswer | RecordedRemark]).validate_python(
                self.module.review_records(answers)
            )
        except ValueError as failure:
            message = f"the first lup's answers at {answers} can't be read: {failure}"
            raise InstallError(message) from failure

    def decided(self, answers: Path, review: str) -> HostAnswer | None:
        """Return the operator's answer to `review`, or none while it waits."""
        return next(
            (
                record.answer
                for record in self.records(answers)
                if isinstance(record, RecordedAnswer) and record.question == review
            ),
            None,
        )

    def remarks(self, answers: Path, reviews: list[str]) -> list[HostSaid]:
        """Return the remarks the operator sent on any of `reviews`, oldest first."""
        return [
            record.remark
            for record in self.records(answers)
            if isinstance(record, RecordedRemark) and record.question in reviews
        ]


class LegacyDashboard(Reviewer, Model, arbitrary_types_allowed=True):
    """The first lup's review dashboard, reached through its host half."""

    checkout: Path
    """The checkout of lup being installed, whose relay keeps the review."""
    legacy: Path
    """The first lup's checkout."""
    clock: Clock
    poll: timedelta = timedelta(seconds=2)
    """How often it looks for the operator's answer."""
    requester: str = "lup-dev install"
    """Who the review names as asking for it, which may never answer it."""

    @classmethod
    def configured(
        cls, checkout: Path, settings: LupDevSettings, clock: Clock
    ) -> LegacyDashboard:
        """Find the first lup's checkout as the interim review hook does.

        The setting is read from the directory holding the repository's git
        directory, as the hook reads it, so one setting points both at it.
        """
        common = Git(cwd=checkout).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        legacy = Path(common).parent / settings.lup_interim_review_legacy_checkout
        return cls(checkout=checkout, legacy=legacy, clock=clock)

    @property
    def host(self) -> Path:
        """The first lup's host half, in its checkout."""
        assets = self.legacy / "packages" / "lup" / "src" / "lup" / "policy" / "assets"
        return assets / "host.py"

    @override
    def answer(self, review: Review) -> Answer:
        """Park the review in the dashboard, wait for the answer, and read it.

        The before side waits in the checkout while the review does, and is
        removed once it's answered or withdrawn.
        """
        if not self.host.is_file():
            message = (
                f"the first lup's host half isn't at {self.host}, so its dashboard "
                "can't show the review: set LUP_INTERIM_REVIEW_LEGACY_CHECKOUT to the "
                "first lup's checkout, or review in this terminal with "
                "`lup-dev install --in-terminal`"
            )
            raise InstallError(message)
        host = Host.load(self.host)
        export = CheckoutLayout(root=self.checkout).install_review(review.since)
        shown = export.relative_to(self.checkout)
        why = (
            f"{review.heading()} Approve to install it as the judge that runs; "
            "declined, the copy installed before keeps judging. Each file is at its "
            f"path in the checkout under {shown}/, the commit approved last before "
            "and `HEAD` after."
        )
        call = Call(
            root=self.checkout,
            requester=self.requester,
            proposal=Proposal(
                why=why,
                files=[
                    ProposedFile(path=export / changed.path, content=changed.after)
                    for changed in review.files
                ],
            ),
            preconditions={
                export / changed.path: changed.before for changed in review.files
            },
            reason=review.heading(),
            answers=host.answers(host.relay(self.checkout)),
        )
        if export.exists():
            shutil.rmtree(export)
        try:
            for changed in review.files:
                if changed.before is None:
                    continue
                kept = export / changed.path
                kept.parent.mkdir(parents=True, exist_ok=True)
                kept.write_bytes(changed.before.encode())
            return self.waited(host, call, review, export)
        except KeyboardInterrupt:
            typer.echo(
                "Withdrawn: the review's files are removed, so the dashboard retires "
                "it as stale, and nothing is installed."
            )
            raise
        finally:
            if export.exists():
                shutil.rmtree(export)

    def waited(self, host: Host, call: Call, review: Review, export: Path) -> Answer:
        """Park `call` and wait for its answer, parking it again each time it expires.

        Return the answer with every remark sent on each review parked for it.
        """
        parked = host.park(call)
        match parked.state:
            case "unavailable":
                message = f"the first lup's host half can't park it: {parked.reason}"
                raise InstallError(message)
            case "pending":
                typer.echo(self.waiting(review, parked.id))
            case "approved" | "rejected":
                typer.echo(f"Review {parked.id} of this same change is answered.")
        parks = list(self.reviews(host, call, parked.id))
        last = parks[-1]
        final = host.decided(call.answers, last)
        if final is None:
            message = f"review {last} ended unanswered"
            raise InstallError(message)
        if final.approved and parked.state != "approved":
            host.spend(call, last)
        said = [*host.remarks(call.answers, parks), final]
        comments = [
            comment.comment(export) for each in said for comment in each.comments
        ]
        note = "\n\n".join(each.note for each in said if each.note)
        if note or comments:
            typer.echo(
                f"What you wrote stays in the first lup's answers file, {call.answers}."
            )
        return Answer(approved=final.approved, note=note, comments=comments)

    def waiting(self, review: Review, parked: str) -> str:
        """Say what waits, where, how to read it, and how to withdraw it."""
        command = (
            f"uv run --directory {self.legacy} lup-devtools dashboard serve "
            f"--root {self.checkout}"
        )
        return "\n".join(
            [
                review.heading(),
                (
                    f"It waits for your answer as review {parked} in the first "
                    "lup's dashboard, which this serves:"
                ),
                f"    {command}",
                (
                    "Unanswered for an hour, it expires and is parked again under "
                    "another id: what you sent as remarks stays with it, drafts not "
                    "yet sent don't."
                ),
                "Ctrl-C withdraws the review and installs nothing.",
            ]
        )

    def reviews(self, host: Host, call: Call, first: str) -> Iterator[str]:
        """Yield each review parked for `call` from `first`, until one is answered.

        The dashboard expires a review an hour after it's parked; it's parked again
        under another id. A review that leaves the queue otherwise refuses.
        """
        relay = host.relay(call.root)
        current = first
        yield current
        while host.decided(call.answers, current) is None:
            match host.entries(relay).get(current):
                case Entry(state="pending"):
                    self.clock.sleep(self.poll.total_seconds())
                case Entry(state="expired"):
                    again = host.park(call)
                    if again.state != "pending":
                        message = (
                            f"review {current} expired, and parking it again "
                            f"failed: {again.state} {again.reason}"
                        )
                        raise InstallError(message)
                    typer.echo(
                        f"Review {current} expired unanswered; it's parked again as "
                        f"review {again.id}."
                    )
                    current = again.id
                    yield current
                case Entry(state=state, outcome=outcome):
                    message = (
                        f"review {current} left the dashboard unanswered, {state}: "
                        f"{outcome}"
                    )
                    raise InstallError(message)
                case None:
                    message = f"review {current} isn't in the first lup's relay {relay}"
                    raise InstallError(message)
