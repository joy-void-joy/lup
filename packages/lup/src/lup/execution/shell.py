"""Running an external program that may not be installed.

A command declared at module scope resolves its binary at import: ``sh``
raises ``CommandNotFound`` from the constructor, so one missing program takes
down every invocation that imports the module holding it -- including the
preflight whose whole job is to report that program missing. Deferring
resolution to first use is what keeps that diagnostic reachable, and what
lets a declaration name a program the machine may turn out not to have.

``git`` sits here rather than beside the tooling that uses it most because
two subjects above it need the same one: the container's mount rail asks git
where this checkout's admin directories are, and the harness asks it who is
committing. A symbol two subjects share belongs below both, which is where
this package already was -- :mod:`lup.execution.writability` answers the
neighbouring question of whether git's own administrative files can be
written at all.
"""

from collections.abc import Callable, Iterable
from typing import IO, Literal, TypedDict, Unpack

import sh

# sh declares these only as stub-private aliases, which pyright refuses to
# import, so they are mirrored here. Each is narrowed where sh wrote `Any` —
# narrower still satisfies sh, and this repository does not spell `Any`.
type ShIn = str | bytes | IO[str] | IO[bytes] | sh.RunningCommand | Iterable[str]
type ShOut = str | int | IO[str] | IO[bytes] | Callable[..., object]
type ShTarget = bool | Literal["out", "err"]
type ShOkCode = int | list[int] | tuple[int, ...]
type ShDone = Callable[[sh.RunningCommand, bool, int], None]


class ShKwargs(TypedDict, total=False):
    """Every special keyword sh accepts, as sh's own stub declares them.

    `LazyCommand` is a proxy, so it must pass through whatever the command it
    stands in for accepts. `**kwargs: object` cannot: `object` is assignable
    to none of the concrete parameters sh declares, so unpacking it fails
    against every one of them at once. Naming them types the proxy as wide as
    the thing proxied rather than as wide as today's call sites.

    Two of sh's forty-five are missing, both refused by `tuple-shape`, which
    admits no suppression: `_tty_size` is a `tuple[int, int]`, and
    `_arg_preprocess` returns a fixed pair. Reach for `sh.Command` directly
    if either is ever wanted.
    """

    _fg: bool
    _bg: bool
    _bg_exc: bool
    _with: bool
    _in: ShIn | None
    _out: ShOut | None
    _err: ShOut | None
    _err_to_out: bool | None
    _in_bufsize: int
    _out_bufsize: int
    _err_bufsize: int
    _internal_bufsize: int
    _env: dict[str, str] | None  # lup: ignore[dict-str-payload] — open names
    _piped: ShTarget | None
    _iter: ShTarget | None
    _iter_noblock: ShTarget | None
    _iter_poll_time: float
    _ok_code: ShOkCode
    _cwd: str | None
    _long_sep: str | None
    _long_prefix: str
    _tty_in: bool
    _tty_out: bool
    _unify_ttys: bool
    _encoding: str
    _decode_errors: str
    _timeout: float | None
    _timeout_signal: int
    _no_out: bool
    _no_err: bool
    _no_pipe: bool
    _tee: ShTarget | None
    _done: ShDone | None
    _truncate_exc: bool
    _preexec_fn: Callable[[], None] | None
    _uid: int | None
    _new_session: bool
    _new_group: bool
    _log_msg: Callable[..., str] | None
    _close_fds: bool
    _pass_fds: set[int]  # lup: ignore[set-shape] — sh's own parameter type
    _return_cmd: bool
    _async: bool


class LazyCommand:
    """Shell command that resolves its binary on first use.

    ``sh.Command`` raises ``CommandNotFound`` at construction time, so a
    module-level command for a missing binary (e.g. ``gh``) would crash
    every CLI invocation at import — including ``--help``. Resolution is
    deferred to the first call or sub-command attribute access instead.
    """

    def __init__(self, name: str, *bake_args: str, tty_out: bool = True) -> None:
        self.name = name
        self.bake_args = bake_args
        self.tty_out = tty_out
        self.resolved: sh.Command | None = None

    def resolve(self) -> sh.Command:
        if self.resolved is None:
            command = sh.Command(self.name)
            if self.bake_args or not self.tty_out:
                command = command.bake(*self.bake_args, _tty_out=self.tty_out)
            self.resolved = command
        return self.resolved

    def __call__(
        self,
        *args: str,
        **kwargs: Unpack[ShKwargs],
    ) -> sh.RunningCommand | str | None:
        return self.resolve()(*args, **kwargs)

    def __getattr__(self, attr: str) -> sh.Command:
        return getattr(self.resolve(), attr)

    def out(
        self,
        *args: str,
        **kwargs: Unpack[ShKwargs],
    ) -> str:
        """The command's stdout with its trailing-newline framing removed.

        The single-value boundary: CLIs frame every output — `git rev-parse`,
        `gh pr list --json` — with a trailing newline, and ``sh`` exposes no
        trimmed accessor, so value reads go through here instead of a per-site
        `str(...).strip()`. Not for column-significant text (`status
        --porcelain` leading columns): use :meth:`lines`.
        """
        return str(self(*args, **kwargs)).strip()

    def lines(
        self,
        *args: str,
        **kwargs: Unpack[ShKwargs],
    ) -> list[str]:
        """The command's stdout as a list of lines.

        For line-oriented output (`--format=` templates, `--porcelain`
        records): the line breaks are consumed by ``splitlines``, while
        leading columns and blank separator lines are preserved exactly.
        """
        return str(self(*args, **kwargs)).splitlines()


git = LazyCommand("git", "--no-pager", "-c", "color.ui=never", tty_out=False)
