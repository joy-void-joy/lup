<!-- Generated from lup.harness.content.docs.runs by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Runs

A job worth launching in the background is a job nobody can see. `lup.runs`
answers that with one directory and a protocol over it, so a run launched
detached, launched by somebody else, or launched before this shell existed is
fully readable — and reading it cannot perturb what it is reading.

## What a run writes

```
<run-dir>/
  manifest.json          what was scheduled, written before the first unit
  units/<step>/<item>.json   one result per landed unit, written atomically
  attempts/<step>/<item>.json  one claim per unit currently running
  artifacts/<step>/<item>/     whatever a unit produces besides its result
  run.log                a line each time something happens
  summary.json           how the run ended, written whatever the ending
```

Every write is an atomic rename, because a reader holds no lock: it sees a
complete record or none. The claim is dropped in the same breath the result
lands, so no instant exists in which a unit is neither running nor landed.

The summary is what says a run is over. A unit count cannot: a pipeline whose
second stage failed never lands its fourth, so waiting for the total is
waiting forever. It is written from a `finally`, so it appears whether the run
succeeded, failed, or was interrupted — and its absence beside a directory
nothing is touching is exactly the evidence that the runner was killed.

## A claim is a lease

A killed runner — a power cut, an OOM, a `kill -9` — leaves its claims on disk
with no result beside them and no process to finish them. On disk that is
indistinguishable from a unit that is simply taking a long time, and age
cannot separate them: it grows for a healthy unit exactly as fast.

So a claim carries `renewed_at` as well as `started_at`, and the runner
re-stamps it from the same heartbeat that writes the log line. The interval
sits well inside the lease, so a runner that stopped writing lines has also
stopped renewing and the two readings cannot disagree. A claim nobody has
renewed within the lease is one nobody holds:

- `run monitor` reports it as `abandoned=` rather than counting it as running,
  and says so outright when every claim has lapsed and no summary was written.
- A resumed run frees the lapsed claims and re-runs those units, naming each in
  the log. Claims whose lease is live are left alone, so two runners sharing a
  directory do not free each other's work.

The process table is not consulted, here or anywhere in this package. Under a
sandbox `/proc` is PID-isolated, so a healthy run is indistinguishable there
from a dead one — a liveness answer that asks it is no answer at all on the
host a long job most often runs on. The `pid` on a claim is there for a person
diagnosing the machine they are standing on, and nothing decides on it.

## Resuming

A pipeline is resumable by default, and nothing has to be arranged for it. Each
unit's result lands in its own file as it completes, and reuse is decided by
fingerprint — a step's own declaration folded together with the fingerprints of
everything it depends on. Re-running the same pipeline over the same directory
reuses every unit whose fingerprint still stands and re-runs the rest, so an
interrupted run costs only what never landed. Editing a step changes its
fingerprint, which reruns it and everything downstream without anybody
maintaining the list of what that is.

Nothing here consults the process table. Under a sandbox `/proc` is
PID-isolated, so a healthy run is indistinguishable there from a dead one; a
liveness answer that asks the process table is no answer at all on the host a
long job most often runs on.

## Watching one

`run monitor <run-dir>` redraws a reading in place: the units landed against
the units scheduled, where each step stands, and what is being worked on. That
is for a person at a second terminal.

`run monitor <run-dir> --events` emits one line per landing, step change,
failure and stall, and exits when the run ends. That is for a watcher, which
sees lines rather than a screen — it is how an agent follows a job instead of
asking whether it is done. The first line is a baseline rather than a replay:
attaching to a run that has already landed four hundred units says so once.

`--once` takes a single reading, for a report.

Silence is the failure that matters, so a run whose heartbeat has stopped is
reported as stalled rather than left looking like one still working.
`--quiet-limit` is how long counts as silence; a pipeline of shell steps is
quiet for seconds, a solver sweep for hours.

### The estimate

A reading never repeats the runner's own estimate of the time left. A progress
bar smooths its rate over the last few landings, and units land in bursts —
one per worker as a batch of budgets expires — so that number once said
twenty-nine seconds about thirty-six two-hour cells. The estimate here divides
everything landed so far by the whole elapsed time, which is the only estimate
bursty landings support. A runtime writing its own bar sets `smoothing=0` for
the same reason.

## Declaring the work

A `Pipeline` is a name and a list of steps. A step is a `CallableStep` around
a Python callable or a `ShellStep` around a command, it names what it depends
on, and it may fan out over items — `FixedItems` when the sweep is known when
the pipeline is written, `ComputedItems` when its width is read off what a
dependency landed.

A step body takes a `StepContext`: the run, which item it is, its dependencies'
results, and a `workspace` of its own to write into. A `ComputedItems` callable
takes the same thing without an item — a `FanContext` — because deciding a
width usually means reading what a dependency *wrote*, and `artifacts_of(result)`
is where one of those results put it. Neither reconstructs a path by hand.

```python
pipeline = Pipeline(
    name="sweep",
    workers=8,
    steps=[
        ShellStep(id="discover", command="ls corpus/*.json"),
        CallableStep(
            id="solve",
            dependencies=["discover"],
            over=ComputedItems(compute=each_line),
            body=solve_one,
            retries=1,
        ),
        CallableStep(id="report", dependencies=["solve"], body=summarize),
    ],
)

if __name__ == "__main__":
    pipeline.main()
```

`main()` serves the pipeline as a command line, so every pipeline gets the
same flags without writing any: `run`, with `--directory`, `--only`, `--from`,
`--force`, `--workers` and `--fresh`, and `plan`, which prints each step's
fingerprint. A shell step reaches its unit's coordinates through
`$LUP_RUN_ITEM`, `$LUP_RUN_STEP`, `$LUP_RUN_DIR` and `$LUP_RUN_WORKSPACE`
rather than through substitution into its text, which a command full of `$`
and `{}` would have to fight.

`examples/monitored_run.py` is a working one, and needs no credentials.

## Rerunning one part

A landed result records the fingerprint it was computed under. A step's
fingerprint folds its own declaration — its `params`, and its body's source
where that can be read — together with the fingerprints of everything it
depends on. So a step is reused when nothing it rests on has changed, and
recomputed when something has, along with everything downstream of it, without
anybody maintaining the list of what that is.

That is what makes the flags reach one part:

- `--only a b` runs exactly those steps.
- `--from encode` runs that step and everything downstream.
- `--force encode` reruns a step whose fingerprint has *not* changed, and
  everything downstream, which rests on a result just recomputed.
- `--fresh` discards every landed result first.

A run killed halfway needs no flag at all: the units that landed are reused
and the ones that never did are run, because that is what the fingerprints
already say. A step whose body cannot be read — one built at runtime, one
defined in a REPL — rests on its declared `params` alone, so editing it will
not invalidate what it landed; declare the parameters that matter.

A step whose dependency has landed nothing refuses rather than guessing, which
is what `--only` on a middle step gets when its input was never run.

## Failure

A unit that raises lands a result with its whole traceback, and its step
fails. Steps that read a failed step are skipped and named in the summary; the
rest of the run carries on, and everything that landed stays landed. `retries`
buys a step another attempt, and the tracebacks of the attempts it survived
are kept on the result that succeeded — a step that passes on its third try is
not the same as one that passed.

A `ShellStep` writes its output to files under `artifacts/` and points at them
from its result, because a step printing a hundred megabytes is an ordinary
step: a record that swallowed it would be unreadable, and one that kept a
prefix would look complete while being cut.

Shell steps fork from a process running a worker pool, which Python warns
about: a fork from a multi-threaded process can deadlock if the child touches
a lock another thread held. `sh` forks and execs promptly, and `sh` is what
this repository's rules mandate over `subprocess`, so the warning stands
rather than being silenced. A pipeline whose shell steps are long and few is
unaffected in practice; one that fans a shell step out over thousands of tiny
items is the shape to watch.

## Writing the layout without the runtime

A project with its own runner does not need `Pipeline`. Writing
`manifest.json`, a result per unit under `units/`, and a heartbeat line makes
that runner followable by the same `run monitor`, because the monitor reads
the layout rather than the runtime. `lup.runs.directory.RunDirectory` is where
every path is spelled, so both ends meet there instead of drifting.
