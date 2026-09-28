"""Running a launched CLI in the foreground, between a repository's lifecycle steps."""

from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager

import sh
from pydantic import BaseModel

from lup.launch.declaration import LaunchCommand, LaunchStep
from lup.launch.refusal import LaunchRefused


def run_in_foreground(command: LaunchCommand) -> int:
    """Hand this terminal to ``command`` until it ends, and answer its exit status.

    The terminal is inherited rather than piped, because an interactive CLI
    draws on it and reads its keys: a launch that captured the output would
    open a session nobody can type into.
    """
    program, *arguments = command.argv
    try:
        sh.Command(program)(
            *arguments, _fg=True, _env=command.env, _cwd=str(command.cwd)
        )
    except sh.CommandNotFound as error:
        raise LaunchRefused(
            f"Cannot launch: executable {error} was not found. Check PATH."
        ) from error
    except sh.ErrorReturnCode as error:
        return error.exit_code
    return 0


class SessionOutcome(BaseModel):
    """Whether the session a step ran around succeeded, known only once it ends."""

    succeeded: bool = False


@contextmanager
def stepped(step: LaunchStep, outcome: SessionOutcome) -> Iterator[None]:
    """One step around what runs inside it: its ``before``, then its ``after`` however that ended."""
    step.before()
    try:
        yield
    finally:
        step.after(outcome.succeeded)


def between_steps(steps: Sequence[LaunchStep], session: Callable[[], int]) -> int:
    """Run ``session`` inside ``steps``, answering its exit status.

    Each step wraps everything after it, the way nested ``with`` blocks do:
    every ``before`` runs in the order given, then the session, then every
    ``after`` in the reverse order, for each step whose ``before`` ran. An
    ``after`` runs however the session ended — a refusal or an interrupt
    included, told the session did not succeed — because a checkpoint skipped
    on the failed session is the one that was needed.
    """
    outcome = SessionOutcome()
    with ExitStack() as stack:
        for step in steps:
            stack.enter_context(stepped(step, outcome))
        status = session()
        outcome.succeeded = status == 0
        return status
