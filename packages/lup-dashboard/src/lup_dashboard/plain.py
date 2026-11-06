"""The plain page: `dev` and each branch on trial to run, and the copies of `lup-dev` kept, a button to each, with nothing of the review's.

`docs/trust.md`, *The way back*; `docs/dashboard.md`, *The plain page*. The review
is React and CodeMirror, whose bundle can break in ways a server can't see, and
this is what's left when it does: HTML from the server, styled and scripted
inline, so it needs nothing the page's build makes. It works without a script
once the browser holds the dashboard's cookie, and each script here does one
thing a page can't do by itself:
- `signing_in` trades the token in the address's fragment, which no request
  carries, for the cookie, as the review's page does;
- `switching_page` waits for the next service, since the one that answered the
  button is stopping, and a browser doesn't retry a refresh that fails;
- `copies_page`'s keys press a copy's button by its place in the list, a branch's
  by its letter.

Picking is a form the server reads as sent (`picked`), a box ticked for each branch
of a set, and a button to run one alone.
"""

import json
from html import escape
from itertools import chain, repeat
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from lup.types import Model

if TYPE_CHECKING:
    from datetime import datetime

    from lup_dev.switching import CopiesListed, CopyListed, CopySwitching
    from lup_dev.trial import BranchListed, TrialListed

STYLE = """
body { font: 15px/1.5 ui-monospace, monospace; margin: 2em auto; max-width: 70em; padding: 0 1em; }
table { border-collapse: collapse; width: 100%; }
td, th { border-bottom: 1px solid #8884; padding: .4em .6em; text-align: left; vertical-align: top; }
.said { border-left: 3px solid #c60; padding: .3em .8em; white-space: pre-wrap; }
.running { font-weight: bold; }
"""
"""What the plain page looks like, inline since it can't rest on the page's build."""


KEYS = "abcdefghijklmnopqstuvwxyz"
"""The letters that press a branch's button, by its place: `r` runs what's ticked."""


class Picking(Model):
    """What the plain page's form sends."""

    branch: list[str] = []
    """Each box ticked."""
    only: list[str] | None = None
    """The button pressed, one to a form, to run one branch alone; its value empty for `dev` alone. None where none was, so it's what's ticked that runs."""


def document(title: str, body: str, last: str = "") -> str:
    """Return a whole page of `body`, titled `title`, its body saying which switch was the `last` it knows of, for a page waiting on one to tell."""
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>"
        f'<body data-last="{escape(last, quote=True)}">{body}</body></html>\n'
    )


def signing_in() -> str:
    """Return the page for a browser without the dashboard's cookie, trading the token in its address's fragment for it."""
    script = """
const token = new URLSearchParams(location.hash.slice(1)).get("token");
if (token) {
  fetch("/api/session", {method: "POST", headers: {Authorization: `Bearer ${token}`}})
    .then((given) => {
      if (given.ok) location.replace("/copies");
      else document.getElementById("said").textContent = "That token isn't this dashboard's.";
    });
}
"""
    return document(
        "lup: the copies kept",
        '<h1>The copies kept</h1><p id="said">Open this with the dashboard\'s token: '
        "the address <code>lup-dev dashboard --no-open</code> prints, with "
        "<code>/copies</code> before its <code>#</code>.</p>"
        f"<script>{script}</script>",
    )


def stamped(at: datetime | None) -> str:
    """Say a moment to the minute, in the server's time zone; `never` for none."""
    return "never" if at is None else at.astimezone().strftime("%Y-%m-%d %H:%M")


def row(place: int, copy: CopyListed) -> str:
    """Return one copy's row, with its button unless it's running, each named by its place in the list."""
    action = (
        "runs now"
        if copy.running
        else (
            f'<form method="post" action="/copies/{escape(copy.commit, quote=True)}">'
            f'<button id="copy-{place}">{place}: switch</button></form>'
        )
    )
    mark = ' class="running"' if copy.running else ""
    return (
        f"<tr{mark}><td>{action}</td><td>{escape(copy.commit)}</td>"
        f"<td>{escape(copy.subject)}</td><td>{stamped(copy.answered)}</td></tr>"
    )


def picked(body: str) -> list[str]:
    """Read the branches the plain page's form sent: the one its button ran alone, none for `dev` alone, where one was pressed; else each ticked.

    >>> picked("branch=a&branch=b")
    ['a', 'b']
    >>> picked("branch=a&only=c")
    ['c']
    >>> picked("branch=a&only=")
    []
    >>> picked("")
    []
    """
    sent = Picking.model_validate(parse_qs(body, keep_blank_values=True))
    if sent.only is not None:
        return [each for each in sent.only if each]
    return sent.branch


def branch_row(letter: str, trial: TrialListed, branch: BranchListed) -> str:
    """Return a branch's row: a box for the set, what it is, where it stands, and its button, named by its `letter` in the list, which none has past the last of them."""
    name = escape(branch.branch, quote=True)
    ticked = " checked" if branch.within else ""
    state = (
        f"in <code>{escape(trial.running)}</code>"
        if branch.within
        else escape(
            branch.conflict
            or (
                "out: you took it out"
                if branch.out
                else f"not in {trial.running} yet"
            )
        )
    )
    built = "; its copy is built" if branch.built else ""
    mark = ' class="running"' if branch.within else ""
    return (
        f'<tr{mark}><td><input type="checkbox" name="branch" value="{name}"{ticked}></td>'
        f"<td>{escape(branch.branch)}</td><td>{escape(branch.subject)}</td>"
        f"<td>{state}{built}</td>"
        f'<td><button name="only" value="{name}" id="branch-{letter}">'
        f"{letter}: run alone</button></td></tr>"
    )


def trial_part(trial: TrialListed) -> str:
    """Return what's on trial: `dev`, each branch, and the form that runs a set or one alone."""
    integration = escape(trial.integration)
    rows = "".join(
        branch_row(letter, trial, each)
        for letter, each in zip(chain(KEYS, repeat("")), trial.branches, strict=False)
    )
    none = (
        "" if rows else f"<p>Nothing is on trial: <code>{integration}</code> runs.</p>"
    )
    table = (
        "<table><tr><th></th><th>Branch</th><th>What it is</th><th>Where it stands</th>"
        f"<th></th></tr><tr><td></td><td>{integration}</td><td></td><td>always</td>"
        '<td><button name="only" value="" id="branch-dev">0: run alone</button></td></tr>'
        f"{rows}</table>"
    )
    return (
        f'<h1>What runs</h1><form method="post" action="/copies/pick">{none}{table}'
        '<p><button id="branch-ticked">r: run what\'s ticked</button></p></form>'
        f"<p>Two that conflict can't run together. A set you've said yes to runs at "
        "once, restarting the host service. One you haven't asks in your inbox first, "
        "and a yes builds it, in minutes, since a build runs its code on this machine. "
        "A set the gate has passed is one a landing made: running another is yours to "
        "judge. <code>lup-dev live accept</code> and <code>drop</code>, in a terminal, "
        "settle a branch.</p>"
    )


def copies_page(listed: CopiesListed | None, said: str) -> str:
    """Return the plain page of the copies `listed`, saying `said` above them; none where they couldn't be listed, which `said` says."""
    last = None if listed is None else listed.last
    told = [each for each in [said, "" if last is None else last.said] if each]
    paragraphs = "".join(f'<p class="said">{escape(each)}</p>' for each in told)
    rows = (
        ""
        if listed is None
        else "".join(row(at, each) for at, each in enumerate(listed.copies, start=1))
    )
    table = (
        "<table><tr><th></th><th>Commit</th><th>What it is</th><th>Last ran</th></tr>"
        f"{rows}</table>"
        if rows
        else "<p>No copy of <code>lup-dev</code> is kept yet.</p>"
    )
    script = """
addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const named = event.key === "r" ? "branch-ticked" : event.key === "0" ? "branch-dev" : null;
  (named ? document.getElementById(named)
    : document.getElementById(`copy-${event.key}`) ?? document.getElementById(`branch-${event.key}`)
  )?.click();
});
"""
    trial = "" if listed is None or listed.trial is None else trial_part(listed.trial)
    return document(
        "lup: the copies kept",
        f"{paragraphs}{trial}<h1>The copies kept</h1>{table}"
        "<p>A switch restarts the host service, in a few seconds, and your sessions "
        "wait for it. A copy that doesn't answer is switched back from, and this "
        "page then says why. The terminal's <code>lup-dev restore</code> does the "
        "same, with no service and no dashboard, and it alone restores the ledger.</p>"
        f"<script>{script}</script>",
        "" if last is None else str(last.at),
    )


def switching_page(switching: CopySwitching) -> str:
    """Return the page saying the service is moving, which goes back to the list once a service says what came of it: a later switch than the last it had said, which is how it tells this one from the one before."""
    last = "" if switching.last is None else str(switching.last.at)
    script = f"""
const before = {json.dumps(last)};
const began = Date.now();
const wait = () => fetch("/copies")
  .then((found) => found.ok ? found.text() : "")
  .catch(() => "")
  .then((page) => {{
    const said = new DOMParser().parseFromString(page, "text/html").body.dataset.last;
    if (page && said !== undefined && said !== before) location.replace("/copies");
    else if (Date.now() - began > 90000) document.getElementById("late").hidden = false;
    else setTimeout(wait, 500);
  }});
setTimeout(wait, 500);
"""
    return document(
        "lup: switching",
        f"<h1>Switching to {escape(switching.commit)}</h1>"
        "<p>The host service stops for that copy to start, in a few seconds. This "
        "goes back to the list once it's known what came of it. If nothing answers "
        "here within a minute, <code>lup-dev restore</code> in a terminal goes back, "
        f"and what came of this is in <code>{escape(str(switching.log))}</code>.</p>"
        '<p id="late" class="said" hidden>Nothing has said what came of it. '
        '<a href="/copies">Back to the list</a>.</p>'
        f"<script>{script}</script>",
    )
