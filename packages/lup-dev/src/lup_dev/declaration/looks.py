"""The core's looks: how the dashboard's own views look, which every repository's looks carry before its modules'.

`docs/declaration.md`, *Views and blocks*. The dashboard lays out some views
itself until each moves into its module (#113, step 4): an item's body by its
kind's, an agent's task list, what their branch changed since the operator
approved it, and the parts of their banner. Each is declared here as its owner's,
so the page holds no fold kind, drawer or tone of its own, and a module taking
one of their letters or names fails the load (`resolve.looked`):
- the shell's tones, which every module's spans may name
  (`lup.SHELL_TONES`), and the tones of what the shell's views say beside
  their text: a fold's summary line, and what the host refused; the shell's
  fold kinds, an agent's group, an item, its context, and a file's, a body's
  and a run of unchanged lines', which `Diff` and `Code` fold under, are
  `Core`'s field (`Core.folds`, `lup.SHELL_FOLDS`), so a person's layer
  changes them;
- the runtime adapters': an agent's task list, a drawer (`TASKS_DRAWER`, beside
  `Task` in `host/records.py`), and their banner's part, what they're working on
  and how full their context is;
- the judge's: what an agent's branches changed since the operator approved
  them, a drawer, each place of it where the agent worked in several, a fold
  kind, the line of a file standing as the operator last saw it, and the agent's
  banner's part, whether their flagged writes are held and what landings wait
  on, and its verb, holding them. The
  judge's code sits above the declaration in `lup_dev`'s layers, so its parts
  are declared here.

The verbs and the fold kinds are fields of `Core` (`verbs`, `folds`), the
shell's, the judge's and the runtime adapters' alike, so a person's
layer gives one another key; the rest is the core's own until each moves into
its module.
"""

from lup.blocks import SHELL_TONES, Drawer, FoldKind, Tone, Verb
from lup_dev.host.protocol import Bannered, Drawn, Looks
from lup_dev.host.records import TASK_TONE, TASKS_DRAWER

SUMMARY_TONE = Tone(name="summary", like="muted")
"""A fold's summary line in one of the shell's views, saying what it hides:
`5 reviewed`."""
REFUSED_TONE = Tone(name="refused", like="muted")
"""A line saying what the host refused to show, and why: `no files: …`."""

TASKS = Drawn(module="adapters", view="tasks", place=TASKS_DRAWER)
"""An agent's task list, the runtime adapters' drawer."""
WORKING = Bannered(module="adapters", view="banner")
"""The runtime adapters' part of an agent's banner: the current entry of their
task list, and their context's ring, the tokens in use against their model's
window."""

SINCE = Drawn(
    module="judge",
    view="since",
    place=Drawer(letter="s", called="since you approved", colour="warn"),
)
"""What an agent's branch changed since the operator approved it, the judge's
drawer (`lup_dev/policy/since.py`)."""
BRANCH_FOLD = FoldKind(
    name="branch",
    letter="p",
    called="branches",
    one="the branch",
    level=1,
    colour="warn",
)
"""One place of "since you approved", a worktree with the branch it has checked
out or a branch alone, where the agent worked in several: its files under it,
its line saying which and what it holds (`lup_dev/policy/since.py`). `Core`
declares it beside the shell's (`Core.folds`) until the judge is a module, so a
person's layer changes it as it does theirs."""
ROLE_FOLD = FoldKind(
    name="role",
    letter="l",
    called="roles",
    one="the role",
    level=1,
    colour="warn",
)
"""The files of one path role in a place of "since you approved", where it shows
several: under a line saying the role and what its files hold (`source · 3 to
review`, `tests · 5 automatic`), which Space `d` settles whole
(`lup_dev/policy/since.py`). `Core` declares it beside the shell's."""
REVIEWED_TONE = Tone(name="reviewed", like="muted")
"""A file of "since you approved" standing as the operator last saw it: a line
of its own, with nothing under it."""
HOLDING = Bannered(module="judge", view="banner")
"""The judge's part of an agent's banner: whether the operator holds each of
the agent's flagged writes for their answer (`set-holding`)."""
HOLD = Verb(name="hold", key="h", called="hold")
"""The judge's verb: holding each flagged write of an agent and their subagents
for the operator's answer, which its banner offers. `Core` declares it until
the judge is a module (#113, step 4), so a person's layer may give it another
key."""

CORE_LOOKS = Looks(
    tones=[*SHELL_TONES, SUMMARY_TONE, REFUSED_TONE, TASK_TONE, REVIEWED_TONE],
    drawers=[TASKS, SINCE],
    banners=[WORKING, HOLDING],
)
"""The core's looks, the shell's, the runtime adapters' and the judge's, in the
order the page lays them out: before each repository's modules'. The shell's
fold kinds are `Core`'s, first among the modules', the judge's with them."""
