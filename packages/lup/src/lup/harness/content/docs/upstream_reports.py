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

SUBAGENT_SESSION_OUTLIVES_THREAD = UpstreamReport(
    slug="subagent-session-outlives-thread",
    component="Codex",
    version="0.155.1",
    repository="openai/codex",
    title=(
        "A subagent's unified-exec session outlives its thread, and rollout "
        "items are still recorded against the dead thread at session end"
    ),
    # lup: ignore[native-spelling] — the event names are the evidence, quoted
    # back to the people who chose them; a report that paraphrased them would
    # be unverifiable by the person receiving it
    body=r"""**What happens.** A PTY session a subagent opened with `exec_command`
keeps running after that subagent's thread has ended, and at the end of the
parent session `codex` prints:

```
ERROR codex_core::session: failed to record rollout items: thread <id> not found
```

The id is the subagent's `agent_id`, as `SubagentStart` and `SubagentStop`
spell it. Something is still producing rollout items addressed to a thread
that no longer exists.

**Reproduced twice**, in two independently written probe kits, on 0.155.1,
model `gpt-6-astra`, `permission_mode: bypassPermissions`, launched
non-interactively with `codex exec`. Offsets below are from each session's
own hook record.

**Run A** — session `01a0babf-84f5-7d63-83bb-9e8e61401a4a`, subagent
`01a0babf-9ef4-75a2-91e7-38bf459e89c9`:

| offset | event | what |
| --- | --- | --- |
| +1152.18s | `PreToolUse` (subagent) | `sleep 494`, **no `&`**, `tool_use_id` prefixed `exec-` |
| +1157.77s | `SubagentStop` | the subagent reports |
| +1157.95s | `PostToolUse` (parent) | `collaborationwait_agent` → `{"message":"Wait completed.","timed_out":false}` |
| +1186.00s | `PostToolUse` (parent) | `ps` → `3767521      33 sleep 494` |
| +1190.13s | `Stop` | session ends |

`etimes` is 33 and `1186.00 − 1152.18 = 33.8`, so this is one process alive
continuously, seen **28.2 seconds after the subagent reported**. The command
carries no `&`, so it is not an orphan reparented to init: the PTY holds it,
and the PTY outlived the thread that opened it. The call also returned in 5.6
seconds for a 494-second command, so it handed back a session rather than
blocking.

Immediately after `Stop`, on the terminal:

```
2026-09-19T17:39:18.950689Z ERROR codex_core::session: failed to record rollout items: thread 01a0babf-9ef4-75a2-91e7-38bf459e89c9 not found
```

**Run B** — subagent `01a0bacb-ffb1-7361-bd6b-09353dce0fbc`, a kit written to
force output onto the session *after* the report:

| offset | event | what |
| --- | --- | --- |
| +12.2s | `PreToolUse` (subagent) | `tail -f …/wake.txt` on an empty file, no `&` |
| +15.17s | `SubagentStop` | the subagent reports |
| +29.52s | `PreToolUse` (parent) | `date +%s >> …/wake.txt` — output forced, 14.4s after the stop |
| +65.21s | `PostToolUse` (parent) | `ps` → `1060999      53 tail -f …/wake.txt` |
| +73.64s | `Stop` | session ends |

The PTY survived **50 seconds past the subagent's stop**, 35 of them after
output was forced onto it. Same line at `Stop`:

```
2026-09-19T17:53:15.188815Z ERROR codex_core::session: failed to record rollout items: thread 01a0bacb-ffb1-7361-bd6b-09353dce0fbc not found
```

**Why the surviving session looks like the producer.** In both runs it is the
only thing still attached to the subagent's thread when the error fires, and
the id in the error is that run's subagent in each case. We have not read the
subagent rollout files themselves, so that is as far as the evidence goes:
reproducible, twice, with one candidate.

**Possibly two defects rather than one.**

1. A subagent's unified-exec sessions are not closed when its thread ends.
   `exec_command` describes itself as "Runs a command in a PTY, returning
   output or a session ID for ongoing interaction" and `write_stdin` as
   "Writes characters to an existing unified exec session"; neither is scoped
   to a thread's lifetime, and no tool closes a session outright.
2. Output from such a session is still routed to the ended thread's rollout,
   where it fails with the error above rather than being dropped or re-homed.

**What it costs a caller.** Every session in which a subagent left a PTY open
ends with what reads as an internal failure in an otherwise successful run. It
does not resume the subagent — measured separately: twelve hook records follow
the single `SubagentStop` in run B and none carries the subagent's `agent_id`.

**What would help you chase it.** The two subagent rollouts, at the
`agent_transcript_path` each `SubagentStop` carried. They sit in the
operator's home directory and are attached by whoever files this.""",
)
"""The leaked PTY and the rollout error that follows it, measured twice.

Filed as one report because the second is the only visible symptom of the
first: the session that outlives its thread is measured directly, and the
error naming that thread is what a caller actually sees.
"""

LIST_AGENTS_REF_COLLISION = UpstreamReport(
    slug="list-agents-ref-collision",
    component="Claude Code",
    version="2.1.278",
    repository="anthropics/claude-code",
    title=(
        "ListAgents gives two live sessions the same bracketed ref, in the "
        "line that tells each how it is addressed"
    ),
    body=r"""**What happens.** `ListAgents` labels each row with a short bracketed
ref — `name [36024e]` — presented as what disambiguates two rows sharing a
name. Two live sessions in different containers, working in the same project
directory, are labelled with the **same** ref, including in the self-describing
first line each is shown for itself.

**Measured on 2.1.278.**

- Two background sessions in *one* container, distinct names: `refprobe-a
  [ce3140]` and `refprobe-b [0039df]` — distinct, as intended.
- A session's self-line carries its own ref: `refprobe-a` running `ListAgents`
  names itself `[ce3140]`.
- Two sessions in *different* containers, same project directory, each named
  itself `[36024e]`.

**Addressing fails closed, which is the good news.** Four sends through
`SendMessage`:

| `to:` | result |
| --- | --- |
| `refprobe-b [ce3140]` (name B, ref A) | refused — `No agent named 'refprobe-b [ce3140]' is reachable. Did you mean: refprobe-b, refprobe-a?` |
| `ce3140` (bare ref) | refused — `No agent named 'ce3140' is reachable.` |
| `refprobe-a [ce3140]` (matched pair) | delivered |
| `refprobe-a` (bare name) | delivered |

A mismatched pair is rejected rather than silently resolved, and a bare ref
resolves to nothing at all. So no message can be misdelivered by this: it is a
listing defect, not a routing one.

**Inference, not measurement.** In both colliding containers `claude` runs as
pid 7 — `lup-entrypoint` at pid 1, `claude` at 7 — and the two sessions share
a project directory. If the ref derives from the pid, perhaps with the project
path, then every contained session that believes itself pid 7 in the same
project collides. We cannot see the derivation; this is the hypothesis that
fits what we can see, and the distinct refs within one container are the
control.

**Why it is worth fixing although sends fail closed.** The collision shows up
in the self-description line, which is exactly the line a reader acts on: it
states the name other sessions use to reach this one. Two such lines side by
side read as one session listed twice.""",
)
"""Two live sessions sharing a ref, and the four sends that bound the harm.

Kept apart from the Codex report beside it because they are different
components; kept at all because the measurement that matters is the negative
one — a mismatched pair is refused — and that is the part a later reader would
otherwise have to re-run.
"""

ROSTER = UpstreamRoster(
    reports=[
        WORKTREE_TOKEN_WALL,
        SUBAGENT_SESSION_OUTLIVES_THREAD,
        LIST_AGENTS_REF_COLLISION,
    ]
)
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
                        "`packages/lup/src/lup/harness/content/docs/"
                        "upstream_reports.py`.",
                        "",
                        *[report.section() for report in roster.reports],
                    ]
                )
            )
        ],
    )
