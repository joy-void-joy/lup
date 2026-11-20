"""Reading a Python file's `# lup:` comments into models, with Python's own tokenizer and parser, no engine or project needed: what a check, a landing and a review read alike.

A comment is a directive's where, tokenized, it starts with the name `lup` and
a colon. What follows is parsed as one Python expression, so a directive is a
call: `ignore`, `defer` or `note`, and anything else a note as written. An
`ignore` or a `defer` the grammar refuses, or a call of another name passing
what only those take, is `Malformed`, never dropped, so it can't sit there
doing nothing unseen (`README.md` here, *`# lup:` comments*).
"""

import ast
import io
import tokenize
from typing import TYPE_CHECKING

from lup.types import Model
from lup_code_rules.directives import Defer, Directive, Ignore, Malformed, Note
from lup_code_rules.engine import LupComment

if TYPE_CHECKING:
    from collections.abc import Generator

LAYOUT = [
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
    tokenize.COMMENT,
]
"""The tokens that hold no code: what an `ignore` standing alone looks past
for the line it covers."""


class Forms(Model):
    """How each directive is written, as a malformed one is told it."""

    ignore: str = (
        'written as `ignore("<rule>", why="<reason>")`, with `issue=12` where it '
        "waits on that issue"
    )
    defer: str = (
        'written as `defer(issue=12, why="…")` or `defer(when=condition, why="…")`'
    )
    issue: str = '`issue` is a number, or a string such as `"owner/repo#7"`'
    tracking: list[str] = ["issue", "when"]
    """The keywords that track a deferral or an `ignore`, which no other call
    takes."""


def read_directives(source: str, forms: Forms | None = None) -> list[Directive]:
    r"""Return every `# lup:` comment in `source`, a Python file's text, in the order written.

    >>> [each.kind for each in read_directives('x = 1  # lup: ignore("regex", why="a")\n')]
    ['ignore']

    A file that doesn't tokenize has its comments read up to where it stops.
    """
    told = forms or Forms()
    tokens = list(tokens_of(source))

    def read() -> Generator[Directive]:
        for at, token in enumerate(tokens):
            if token.type != tokenize.COMMENT:
                continue
            body = lup_body(token.string)
            if body is None:
                continue
            line, column = token.start
            yield directive(body, line, column + 1, covered(tokens, at), told)

    return list(read())


def typescript_directives(
    comments: list[LupComment], forms: Forms | None = None
) -> list[Directive]:
    """Return the directives a TypeScript file's `// lup:` comments say, as the engine found them, each read with the grammar a Python file's is."""
    told = forms or Forms()
    return [
        directive(each.body, each.line, each.column, each.covers, told)
        for each in comments
    ]


def tokens_of(source: str) -> Generator[tokenize.TokenInfo]:
    """Yield `source`'s tokens, up to where it stops tokenizing, if it does."""
    try:
        yield from tokenize.generate_tokens(io.StringIO(source).readline)
    except tokenize.TokenError, SyntaxError:
        return


def lup_body(comment: str) -> str | None:
    """Return what a comment says after `lup:`, or none for another comment.

    >>> lup_body('# lup: note("x")')
    'note("x")'
    >>> lup_body("# lupine: x") is None
    True
    """
    text = comment.removeprefix("#")
    significant = [token for token in tokens_of(text) if token.type not in LAYOUT]
    match significant:
        case [
            tokenize.TokenInfo(type=tokenize.NAME, string="lup"),
            tokenize.TokenInfo(type=tokenize.OP, string=":") as colon,
            *_,
        ]:
            lines = text.splitlines() or [""]
            # lup: ignore("string-slice", why="cuts the comment at the column its tokenizer gave the colon, which no format of the comment's own says")
            return lines[0][colon.end[1] :].strip()
        case _:
            return None


def covered(tokens: list[tokenize.TokenInfo], at: int) -> int:
    """Return the line an `ignore` at `tokens[at]` keeps: its own where code comes before it there, else the next line holding code, so stacked ones keep the same line."""
    comment = tokens[at]
    line = comment.start[0]
    if any(each.start[0] == line and each.type not in LAYOUT for each in tokens[:at]):
        return line
    after = next((each for each in tokens[at + 1 :] if each.type not in LAYOUT), None)
    return after.start[0] if after is not None else line + 1


def directive(
    body: str, line: int, column: int, covers: int, forms: Forms
) -> Directive:
    """Return the directive `body` says, a comment at `line` and `column`, an `ignore` there keeping line `covers`."""
    try:
        parsed = ast.parse(body, mode="eval").body
    except SyntaxError:
        parsed = None
    match parsed:
        case ast.Call(func=ast.Name(id="ignore")) as call:
            return ignored(call, body, line, column, covers, forms)
        case ast.Call(func=ast.Name(id="defer")) as call:
            return deferred(call, body, line, column, forms)
        case ast.Call(
            func=ast.Name(id="note"),
            args=[ast.Constant(value=str() as said)],
            keywords=[],
        ) if said.strip():
            return Note(line=line, column=column, text=said.strip())
        case ast.Call(func=ast.Name(id=named), keywords=keywords) if any(
            each.arg in forms.tracking for each in keywords
        ):
            problem = (
                f"`{named}` is no directive, yet passes `issue` or `when`, which "
                "track a `defer` or an `ignore`: lup's calls are `ignore`, `defer` "
                "and `note`"
            )
            return Malformed(line=line, column=column, text=body, problem=problem)
        case _:
            pass
    match called(body):
        case "ignore" | "defer" as named:
            form = forms.ignore if named == "ignore" else forms.defer
            problem = f"`{named}` doesn't parse as a call: it's {form}"
            return Malformed(line=line, column=column, text=body, problem=problem)
        case _:
            return Note(line=line, column=column, text=body)


def called(body: str) -> str | None:
    """Return the name a directive's text starts calling, `defer` in `defer(why=`, or none where it starts no call."""
    match [token for token in tokens_of(body) if token.type not in LAYOUT]:
        case [
            tokenize.TokenInfo(type=tokenize.NAME, string=name),
            tokenize.TokenInfo(type=tokenize.OP, string="("),
            *_,
        ]:
            return name
        case _:
            return None


def ignored(
    call: ast.Call, body: str, line: int, column: int, covers: int, forms: Forms
) -> Directive:
    """Return the `ignore` `call` writes, or what's wrong with it."""

    def wrong(problem: str) -> Malformed:
        return Malformed(line=line, column=column, text=body, problem=problem)

    match call.args:
        case [ast.Constant(value=str() as rule)] if rule:
            pass
        case _:
            return wrong(f"`ignore` names one rule, as a string: it's {forms.ignore}")
    names = [each.arg for each in call.keywords]
    if None in names or len(dict.fromkeys(names)) != len(names):
        return wrong(f"`ignore` names a keyword twice: it's {forms.ignore}")
    unknown = [name for name in names if name not in ["why", "issue"]]
    if unknown:
        return wrong(f"`ignore` takes `why` and `issue`, not `{unknown[0]}`")
    match keyword(call, "why"):
        case ast.Constant(value=str() as why) if why.strip():
            pass
        case _:
            return wrong(f'`ignore` needs its reason, `why="…"`: it\'s {forms.ignore}')
    issue = keyword(call, "issue")
    tracked = issued(issue)
    if issue is not None and tracked is None:
        return wrong(forms.issue)
    return Ignore(
        line=line, column=column, covers=covers, rule=rule, why=why, issue=tracked
    )


def deferred(
    call: ast.Call, body: str, line: int, column: int, forms: Forms
) -> Directive:
    """Return the `defer` `call` writes, or what's wrong with it."""

    def wrong(problem: str) -> Malformed:
        return Malformed(line=line, column=column, text=body, problem=problem)

    if call.args or any(each.arg is None for each in call.keywords):
        return wrong(f"`defer` takes keywords only: it's {forms.defer}")
    names = [each.arg for each in call.keywords]
    if len(dict.fromkeys(names)) != len(names):
        return wrong(f"`defer` names a keyword twice: it's {forms.defer}")
    unknown = [name for name in names if name not in ["why", *forms.tracking]]
    if unknown:
        return wrong(f"`defer` takes `why`, `issue` and `when`, not `{unknown[0]}`")
    match keyword(call, "why"):
        case ast.Constant(value=str() as why) if why.strip():
            pass
        case _:
            return wrong(
                f"`defer` needs what's left undone, `why=\"…\"`: it's {forms.defer}"
            )
    issue = keyword(call, "issue")
    tracked = issued(issue)
    if issue is not None and tracked is None:
        return wrong(forms.issue)
    match keyword(call, "when"):
        case None:
            when = None
        case ast.Name(id=name):
            when = name
        case _:
            return wrong("`when` is the bare name of a declared condition")
    if tracked is None and when is None:
        return wrong("a defer needs an issue, a condition (`when=`), or both")
    return Defer(line=line, column=column, why=why, issue=tracked, when=when)


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    """Return what `call` passes as its keyword `name`, or none where it passes nothing so."""
    return next((each.value for each in call.keywords if each.arg == name), None)


def issued(node: ast.expr | None) -> int | str | None:
    """Return an `issue`'s value: a number here, or a string such as `"owner/repo#7"`; none where it's neither."""
    match node:
        case ast.Constant(value=bool()):
            return None
        case ast.Constant(value=int() | str() as value):
            return value
        case _:
            return None


class Reworded(Model):
    """A deferral kept, its reason rewritten: the same issue and condition, said otherwise."""

    before: Defer
    after: Defer


class Deferrals(Model):
    """The work left undone a change of a file adds, takes away and rewords: what a landing says it lands."""

    added: list[Defer] = []
    removed: list[Defer] = []
    reworded: list[Reworded] = []


def changed_deferrals(before: str | None, after: str | None) -> Deferrals:
    r"""Return the deferrals a change of a Python file adds, removes and rewords, from its text `before` and `after`, none where it's made or deleted.

    >>> changed = changed_deferrals(
    ...     '# lup: defer(issue=1, why="a")\n',
    ...     'x = 1\n# lup: defer(issue=1, why="b")\n# lup: defer(issue=2, why="c")\n',
    ... )
    >>> [each.issue for each in changed.added], len(changed.reworded)
    ([2], 1)
    """
    return deferrals_changed(
        read_directives(before) if before is not None else [],
        read_directives(after) if after is not None else [],
    )


def deferrals_changed(before: list[Directive], after: list[Directive]) -> Deferrals:
    """Return the deferrals a change adds, removes and rewords, from a file's directives `before` and `after` it, however they were read: a Python file's (`read_directives`) or a TypeScript file's (`typescript_directives`).

    A deferral moved to another line is the same one, so it's neither added nor
    removed; one whose issue and condition stay while its reason changes is
    reworded, not removed and added.
    """

    def same(left: Defer, right: Defer) -> bool:
        return (left.issue, left.when, left.why) == (right.issue, right.when, right.why)

    def tracked(left: Defer, right: Defer) -> bool:
        return (left.issue, left.when) == (right.issue, right.when)

    old = [each for each in before if isinstance(each, Defer)]
    new = [each for each in after if isinstance(each, Defer)]
    gone = [each for each in old if not any(same(each, kept) for kept in new)]
    come = [each for each in new if not any(same(each, was) for was in old)]
    reworded = [
        Reworded(before=was, after=now)
        for was in gone
        if (now := next((each for each in come if tracked(was, each)), None))
        is not None
    ]
    return Deferrals(
        added=[each for each in come if not any(each == r.after for r in reworded)],
        removed=[each for each in gone if not any(each == r.before for r in reworded)],
        reworded=reworded,
    )
