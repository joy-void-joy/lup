"""Defects measured in the runtimes underneath, as reports ready to send.

A report addressed to the people who own a runtime quotes that runtime's own
identifiers back to them, so the bodies here carry minified variable names
and token sets verbatim. That is the evidence, not incidental detail: the
next release renumbers every one of them, and a report that paraphrased
instead would be unverifiable by the person receiving it.
"""

import lup.harness.models as models
from lup.devtools.upstream import UpstreamReport, UpstreamRoster

WORKTREE_TOKEN_WALL = UpstreamReport(
    slug="worktree-token-wall",
    component="Claude Code",
    version="2.1.237",
    repository="anthropics/claude-code",
    title=(
        "Worktree isolation refuses fifteen shell words in any argv position, "
        "including in read-only commands containing no git"
    ),
    body=r"""**What happens.** In a session isolated by `EnterWorktree`, a command is
refused whenever any of fifteen shell words appears as an argv element —
not only as `argv[0]`. The check is not gated on the command being a git
command, although every diagnostic in the family is phrased about git.

**Reproducer** (read-only, no git anywhere in it):

```
$ grep -c hash some_file.py
This session is isolated in the worktree …, but this command runs a string
through hash, which can't be verified to stay inside the worktree; run the
command directly instead. Refusing to run it — a worktree-isolated session's
git operations must target its own worktree.
```

`grep -c eval`, `rg complete src/` and `grep -rn enable .` fail identically.

Note the word must be its own argv element: `git log -S"ssh alias"` does
**not** reproduce, because quoting keeps `alias` from becoming one.

**The full set**, read out of the 2.1.237 binary rather than inferred:

```js
dNr = new Set(["eval","source",".","exec","nocorrect","fc","coproc","trap",
               "enable","mapfile","readarray","hash","bind","complete",
               "compgen","alias","let"])
qAv = new Set(["exec","nocorrect"])
A1p = new Set([...dNr].filter((e) => !qAv.has(e)))
```

So fifteen words match, of which several are ordinary English that appears in
argument position constantly: `hash`, `let`, `complete`, `enable`, `bind`,
`trap`, `source`. Searching a codebase for any of them is refused.

**The fix you already wrote, twice.**

First, `.` is in the same set and is index-gated to `argv[0]`:

```js
let n = e.find((o, i) => { let s = Hae.basename(o).toLowerCase();
                           return s === "." ? i === 0 : A1p.has(s) });
if (n !== void 0) {
  if (e.filter((i) => i !== n).length > 0)
    return `runs a string through ${Hae.basename(n)}, which can't be verified `
         + `to stay inside the worktree; run the command directly instead`
}
```

`.` was special-cased precisely because it appears in argument position
constantly. So do the other fourteen.

Second, and more tellingly: the two sibling checks in the very same function
**are** gated on git, and this one is not.

```js
ZLa = /^git(?:\.exe|\.real|-[a-z][\w-]*)?$/i
let t = e.some((o) => ZLa.test(Hae.basename(o)));

if (t && e.some((o) => WAv.has(...)))       // xargs / parallel — git-gated
if (t && r("find") && e.some((o) => VAv.has(o)))  // find -execdir — git-gated
if (n !== void 0)                            // this one — not gated
```

Both neighbours require a git-looking argv element before they refuse.
Applying either existing pattern — the `t &&` gate, or the `.` index gate —
would close this.

**No escape hatch reaches it.** Our project's approval marker is a leading
comment line on the command; the refusal is byte-identical with it present.

**It arms on the tool, not on the directory.** A session *launched* already
rooted in a worktree is not isolated and runs all of these; only calling
`EnterWorktree` turns the check on. That asymmetry is the workaround we have
adopted, and it is also why the check is easy to miss in testing.

**Impact.** A project whose workflow directs all work into worktrees loses
every command containing one of these words for the whole session, including
read-only ones.

---

**Related, same family.** `bwrap` hard-fails when a path in its mount list has
vanished, rather than skipping it. Two instances:

```
bwrap: Can't get type of source /tmp/claude-1000/claude-settings-<hash>.json: No such file or directory
bwrap: Can't get type of source …/lup.git/worktrees/<name>/config.worktree: No such file or directory
```

The second is a stale git worktree's config file, so the mount list is derived
from git state that outlives the worktree it describes.

A third, on a host with `max_user_namespaces` unbounded,
`unprivileged_userns_clone=1`, no AppArmor restriction, and the shell already
inside a user namespace:

```
apply-seccomp: unshare(CLONE_NEWUSER): Invalid argument
```

All three share the property that makes them expensive: **the command does not
run, prints the failure on its own line, and returns what reads exactly like a
successful run with no output.** A `grep` that matched nothing and a `grep`
that never executed are indistinguishable to the caller.""",
)
"""The shape-check over-match, and the sandbox failures found beside it.

Filed here rather than only in a design document because the evidence is the
part that cannot be reconstructed later: the token set and the two gated
siblings were read out of one binary on one day, and the next release
renumbers every identifier in them.
"""

ROSTER = UpstreamRoster(reports=[WORKTREE_TOKEN_WALL])
"""Every report this project holds against a component it does not own."""


def document(roster: UpstreamRoster = ROSTER) -> models.PromptDocument:
    """Render the roster as the page a reader browses before filing."""
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text="\n".join(
                    [
                        "# Upstream reports",
                        "",
                        "Defects this project measured in components it does "
                        "not own, each with the evidence that was actually "
                        "run and the command that files it.",
                        "",
                        "Nothing here files anything. Publishing under an "
                        "account belongs to whoever owns the account, so a "
                        "report stays *not filed* until a human runs the "
                        "command and records the URL in the declaration at "
                        "`packages/lup/src/lup/devtools/harness/content/docs/"
                        "upstream_reports.py`.",
                        "",
                        *[report.section() for report in roster.reports],
                    ]
                )
            )
        ],
    )
