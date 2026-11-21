# Promises

What a module promises, and how the gate checks it. A promise is a method behind `@lup.promise` whose docstring says what someone can count on, in a class a module lists in its `parts`, as its other methods are:

```python
import lup
from lup import Part, State
from lup.testing import Step, Testing


class CounterPart(Part):
    """The counter's tools."""

    tally: State[Tally] = Tally()
    """How far it has counted: what its invariants read."""

    @lup.tool
    async def bump(self, bumping: Bumping) -> Count:
        """Move the count by as much as asked."""
        self.tally = Tally(count=self.tally.count + bumping.by)
        return Count(count=self.tally.count)


class CounterPromises(Part):
    """The counter's promises."""

    @lup.promise
    def never_goes_back(self, step: Step[Tally]) -> bool:
        """The count never goes down."""
        return step.after.count >= step.before.count

    @lup.promise
    async def counts_what_its_told(self, by: Testing) -> None:
        """A bump up moves the count up by what it asks."""
        started = await by.started(Project(modules=Modules.default().add(Counter())))
        climbing = by.any(Climbing)
        agent = by.any(Agent)
        await started.call("bump", climbing, agent)
        counted = await started.call("counted", Asking(), agent)
        assert isinstance(counted, Accepted)
        assert counted.output == Count(count=climbing.by)
```

Its library side (`lup.testing`) is what a promise imports: the harness, and what a call answers. Checking promises is the environment's (`lup.environment.testing`), with the pytest plugin the gate runs them through. A promise imports `lup` and `lup.testing` alone, never the core's insides nor the environment, which an import contract holds, so a change inside a module leaves its promises alone.

## An invariant and a scenario

A promise takes one of two shapes, told apart by what it takes. Start from the invariants: what always holds of a module, or never happens, is what a design rests on, and one invariant is checked everywhere.
- **An invariant** is about every moment: a predicate over one step, `def name(self, step: Step[State]) -> bool`, the state before, the call made through a door, what it answered, and the state after. It isn't async and takes the step alone, so it can't drive lup, and it answers its verdict, so it can't check nothing. "Never X unless Y", "only the operator does X", "X never goes back" are invariants.
- **A scenario** is about a run: `async def name(self, by: Testing) -> None`, a story through the harness that asserts where it ends. What only a run can say is a scenario: that something can happen at all, where several steps end up, and a setup a generator wouldn't build. What it explores it draws from the harness, `by.any(Kind)`: a value of any type hypothesis can build, a model's every field explored and its constraints kept, and a run that breaks the promise is shrunk to the smallest values that do.

An invariant is checked over every slice of every call of every run the harness makes: the runs it generates for the invariant, and every scenario's too, so a scenario is also a check of every invariant of the modules it starts.

## Invariants

An invariant over `Step[State]` reads its module's state where a part of the module keeps it: a field typed `State[State]`, with its default, which the part reads and changes as it would any field (`lup.State`). The harness copies it before and after each step, so what a slice changes in place leaves the state before as it was. A state too big to copy at every slice, as a whole database, is read instead through a door of the module that only reads: a tool marked `reads=True` answering `State`, taking nothing it must be given, and answering at once. Where it says who may call it, the harness reads it as the first party its `by` names that's made with nothing given: `by: Operator` keeps a module's whole state off every agent's list of tools. A module holding an invariant with neither fails to start, naming the invariant.

A step is a slice of a call: what one call runs from one `await` to the next. Each call runs as a task of its own, so where calls overlap, each slice is credited to its own call, and an invariant sees exactly what that call changed and when. `step.answered` is what the call answered, on the slice that ended it, and none before. An invariant a slice breaks is raised from that call when it ends (`BrokenInvariantError`), so a scenario sees it where it called.

The gate checks an invariant over runs of calls through every door of its own module: each tool, command and service, given a value of what it takes, by a party of any its doors name, all started at once. Only they change the state the invariant reads, its services among them, which another module's code calls; the rest of a project's doors would dilute the search, and the core's grow with each submodule. A scenario checks every invariant of every module it starts, over every call it makes, whichever module's door it goes through. A run that breaks it is shrunk to the fewest calls, in the order closest to asyncio's own, and told with the order their slices ran in.

## Time and order

Every run is made on an event loop the harness keeps (`lup.environment.testing.simulation`): wherever more than one thing could run next, hypothesis picks which, its first choice asyncio's own (first ready, first run); where a timer waits, it may fire early, as a loaded machine would make it. The clock is a number that moves only to the next timer, when nothing else can run, so an hour's `asyncio.sleep` passes at once. So no run depends on how loaded the machine is, and an order that breaks a promise is shrunk like any value. A run in which every task waits on something nothing will do fails, as does one past a ceiling of slices.

## The harness

`Testing`, handed to a scenario as `by`, starts lup on a declaration, a `Project` or a repository's files (`Repository`), read with their layers as lup reads a repository's (`by.started(…)`, raising `ProjectError` where it doesn't), and draws values (`by.any(…)`). What it starts (`Started`) has the modules it resolved to, the tools a session is told of, the guidance a session is told (`guidance(by)`), and its doors, called as a party calls them: `call`, `run`, `serve` and `view`, each answering `Accepted` or `Refused`, every invariant checked over each call (`BrokenInvariantError` where one doesn't hold). `typed(words, by)` types on the command line as `by` does, its call made through the same doors, and answers what it did (`Typed`: what its help listed, the call it made, what it printed and how it ended). `checked(module, promise)` checks another module's promises as the gate does, for promises about checking itself, in a thread of its own, since asyncio runs one task at a time in a thread. `raises(Kind)` says a block fails, since a module's promises can't import a test runner.

A part's programs (`lup.Program`) are stood in for as the promise starting lup says, by each program's name (`by.started(…, programs={"podman": …})`), each run heard (`Started.ran`); a program it names none for isn't there. `Scripted` answers each run by the arguments it starts with, `Responding` is code the promise writes answering a run from its arguments and input, and `Acting` code told the whole run, its variables and directory too. git is the one program run for real: `RealGit` runs it on scratch repositories the promise makes (`made`, `committed`), reading no configuration of the machine's or the operator's, every commit's author and time the same at every run, reaching nothing but files. A promise about what lup asks git is checked against git itself, since a script of git's answers by their arguments breaks as soon as lup asks git otherwise, and says what its writer thought git would; a repository made, a commit and a few reads take milliseconds.

What the harness does is said on the library side and done on the environment's: loading a declaration imports neither hypothesis nor the environment, and another harness, driving real agents, could check the same promises.

## Checking

A project's gate checks the promises of its own modules, not those of lup's it installs, which lup's own gate checks; but a promise about every project (`@lup.promise(every_project=True)`) of any module it selects, over its own declaration, which the harness hands it as `by.project()`, so the core's promise that a project's guidance fits is checked at every project's gate (`lup/told/README.md`). The plugin (`lup.environment.testing.plugin`, which pytest finds by the core's entry point) collects the promises of the modules the declaration resolves to, where pytest's paths reach it: `lup_project.py` at pytest's root, or the file `[tool.lup]`'s `declaration` names in `pyproject.toml`, as lup reads a repository's. Each promise is one check, named by its module, its class and its own name.

The gate's check is repeatable: each promise draws a hundred runs, their values and their orders, from a seed its own name and source fix, with no deadline, so a tree gets the same verdict whatever the machine's load. `pytest --lup-explore=RUNS` checks each over that many runs of random values instead, to find what the gate's don't; the gate never runs it, and whoever fixes what it finds writes the values into a scenario, which the gate then keeps. Nothing waits on real time or starts a process, but the promises of running programs, which can't be checked otherwise (`lup/programs/README.md`), and the guard's, below.

A promise the gate's check finds broken is checked once more on the same values. One that holds then depends on something besides its tree, so it passes, and is listed at the run's end with how it failed, to fix, rather than failing a branch it may have nothing to do with.

**The guard** (`lup.environment.testing.guarding`) holds every check to limits a loaded machine barely moves, never to the clock alone. Each slice a run of a promise runs tells it the check is moving.
- A check that goes `stalled` (30 s) without a run of it moving on, stuck on a lock or spinning in one place, fails there, naming where each thread was.
- A check taking more of the processor's time than its `ceiling` (120 s) fails as too slow.
- One taking more than `slow` (15 s) passes, and is listed to fix.

Each limit is the plugin's ini option of its name (`lup_stalled`, `lup_ceiling`, `lup_slow`, in seconds). A failing promise halted while hypothesis shrinks it is told with the smallest run found so far, saying so. A halt that doesn't end its check, as a thread that never wakes, ends the process with every thread's stack, as the check that crashed its worker. Each check the guard halted, each slow one and each flaky one carries a property saying so in pytest's report (`lup-halted`, `lup-slow`, `lup-flaky`).

A broken promise is told with what it promises, the smallest values it drew, each as Python writes it, the shortest run of calls that broke it and how their slices interleaved, and where. Hypothesis's explain phase is left out: the report says this itself, and explaining reruns a broken promise hundreds of times.

## What the gate runs

Promises, and docstrings' examples, which show how something is used. A test function names no promise, and the gate fails it, saying to write it as one; one that can't be said as an invariant or a scenario is kept with `@pytest.mark.unpromised(why=…)`, and what couldn't be said is sent as a friction. A class of the repository's holding promises that no module lists in its `parts` fails too, since nothing would check them.
