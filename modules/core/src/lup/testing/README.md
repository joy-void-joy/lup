# Promises

What a module promises, and how the gate checks it. A promise is a method behind `@lup.promise` whose docstring says what someone can count on, in a class a module lists in its `parts`, as its other methods are:

```python
import lup
from lup import Part
from lup.testing import Step, Testing


class CounterPromises(Part):
    """The counter's promises."""

    @lup.promise
    def never_goes_back(self, step: Step[Count]) -> bool:
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

## A law and a scenario

A promise takes one of two shapes, told apart by what it takes.
- **A law** is about every moment: a predicate over one step, `def name(self, step: Step[State]) -> bool`, the state before, the call made through a door, what it answered, and the state after. It isn't async and takes the step alone, so it can't drive lup, and it answers its verdict, so it can't check nothing. "Never X unless Y" is a law.
- **A scenario** is about a run: `async def name(self, by: Testing) -> None`, a story through the harness that asserts where it ends. What only a run can say is a scenario: that something can happen at all, where several steps end up, and a setup a generator wouldn't build. What it explores it draws from the harness, `by.any(Kind)`: a value of any type hypothesis can build, a model's every field explored and its constraints kept, and a run that breaks the promise is shrunk to the smallest values that do.

A law is checked over every slice of every call of every run the harness makes: the runs it generates for the law, and every scenario's too, so a scenario is also a check of every law of the modules it starts.

## Laws

A law over `Step[State]` reads its module's state through a door of the module that only reads: a tool marked `reads=True` answering `State`, taking nothing it must be given and no `by`, and answering at once. The harness reads it before and after each step, so a law sees only what a party can see, and reading never changes what it reads. A module holding a law with no such door fails to start, naming the law.

A step is a slice of a call: what one call runs from one `await` to the next. Each call runs as a task of its own, so where calls overlap, each slice is credited to its own call, and a law sees exactly what that call changed and when. `step.answered` is what the call answered, on the slice that ended it, and none before. A law a slice breaks is raised from that call when it ends (`BrokenLawError`), so a scenario sees it where it called.

The gate checks a law over runs of calls through every door of its own module: each tool, command and service, given a value of what it takes, by a party of any its doors name, all started at once. Only they change the state the law reads, its services among them, which another module's code calls; the rest of a project's doors would dilute the search, and the core's grow with each submodule. A scenario checks every law of every module it starts, over every call it makes, whichever module's door it goes through. A run that breaks it is shrunk to the fewest calls, in the order closest to asyncio's own, and told with the order their slices ran in.

## Time and order

Every run is made on an event loop the harness keeps (`lup.environment.testing.simulation`): wherever more than one thing could run next, hypothesis picks which, its first choice asyncio's own (first ready, first run); where a timer waits, it may fire early, as a loaded machine would make it. The clock is a number that moves only to the next timer, when nothing else can run, so an hour's `asyncio.sleep` passes at once. So no run depends on how loaded the machine is, and an order that breaks a promise is shrunk like any value. A run in which every task waits on something nothing will do fails, as does one past a ceiling of slices.

## The harness

`Testing`, handed to a scenario as `by`, starts lup on a declaration, a `Project` or a declaration file's text, as lup's start loads and resolves one (`by.started(…)`, raising `ProjectError` where it doesn't), and draws values (`by.any(…)`). What it starts (`Started`) has the modules it resolved to, the tools a session is told of, and its doors, called as a party calls them: `call`, `act` and `run`, each answering `Accepted` or `Refused`, every law checked over each call (`BrokenLawError` where one doesn't hold). `checked(module, promise)` checks another module's promises as the gate does, for promises about checking itself, in a thread of its own, since asyncio runs one task at a time in a thread. `raises(Kind)` says a block fails, since a module's promises can't import a test runner.

What the harness does is said on the library side and done on the environment's: loading a declaration imports neither hypothesis nor the environment, and another harness, driving real agents, could check the same promises.

## Checking

A project's gate checks the promises of its own modules, not those of lup's it installs, which lup's own gate checks. The plugin (`lup.environment.testing.plugin`, which pytest finds by the core's entry point) collects the promises of the modules the declaration resolves to, where pytest's paths reach it: `lup_project.py` at pytest's root, or the file `lup_declaration` names in its settings. Each promise is one check, named by its module, its class and its own name.

The gate's check is repeatable: each promise draws a hundred runs, their values and their orders, from a seed its own name and source fix, with no deadline, so a tree gets the same verdict whatever the machine's load. `pytest --lup-explore=RUNS` checks each over that many runs of random values instead, to find what the gate's don't; the gate never runs it, and whoever fixes what it finds writes the values into a scenario, which the gate then keeps. Nothing waits on real time or starts a process, but the promises of running programs, which can't be checked otherwise (`lup/programs/README.md`).

A broken promise is told with what it promises, the smallest values it drew, the shortest run of calls that broke it and how their slices interleaved, and where.

## What the gate runs

Promises, and docstrings' examples, which show how something is used. A test function names no promise, and the gate fails it, saying to write it as one; one that can't be said as a law or a scenario is kept with `@pytest.mark.unpromised(why=…)`, and what couldn't be said is sent as a friction. A class of the repository's holding promises that no module lists in its `parts` fails too, since nothing would check them.
