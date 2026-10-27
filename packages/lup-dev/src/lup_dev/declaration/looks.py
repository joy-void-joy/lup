"""The core's looks: how the dashboard's own views look, which every repository's looks carry before its modules'.

`docs/declaration.md`, *Views and blocks*. The dashboard lays out some views
itself until each moves into its module (#113, step 4): an item's body by its
kind's, an agent's task list, what its branch changed since the operator
approved it, and the parts of its banner. Each is declared here as its owner's,
so the page holds no fold kind, drawer or tone of its own, and a module taking
one of their letters or names fails the load (`resolve.looked`):
- the shell's fold kinds, an agent's group, an item, its context, and a
  file's, a body's and a run of unchanged lines', which `Diff` and `Code` fold
  under (`lup.SHELL_FOLDS`); the shell's tones, which every module's spans may
  name (`lup.SHELL_TONES`); and the tones of what the shell's views say beside
  their text: a fold's summary line, and what the host refused;
- the runtime adapters': an agent's task list, a drawer (`TASKS_DRAWER`, beside
  `Task` in `host/records.py`), and its banner's part, what it's working on
  and how full its context is;
- the judge's: what an agent's branch changed since the operator approved it,
  a drawer, the line of a file standing as they last saw it, and its banner's
  part, whether its flagged writes are held. The judge's code sits above the
  declaration in `lup_dev`'s layers, so its parts are declared here.
"""

from lup.blocks import SHELL_FOLDS, SHELL_TONES, Drawer, Tone
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
"""The runtime adapters' part of an agent's banner: the current entry of its
task list, and its context's ring, the tokens in use against its model's
window."""

SINCE = Drawn(
    module="judge",
    view="since",
    place=Drawer(letter="s", called="since you approved", colour="warn"),
)
"""What an agent's branch changed since the operator approved it, the judge's
drawer (`lup_dev/policy/since.py`)."""
REVIEWED_TONE = Tone(name="reviewed", like="muted")
"""A file of "since you approved" standing as the operator last saw it: a line
of its own, with nothing under it."""
HOLDING = Bannered(module="judge", view="banner")
"""The judge's part of an agent's banner: whether the operator holds each of
its flagged writes for their answer (`set-holding`)."""

CORE_LOOKS = Looks(
    folds=SHELL_FOLDS,
    tones=[*SHELL_TONES, SUMMARY_TONE, REFUSED_TONE, TASK_TONE, REVIEWED_TONE],
    drawers=[TASKS, SINCE],
    banners=[WORKING, HOLDING],
)
"""The core's looks, the shell's, the runtime adapters' and the judge's, in the
order the page lays them out: before each repository's modules'."""
