"""The tools an agent uses to reach the rest of its cohort, and the outside.

Written once here because every consumer needs the same three verbs and had
been writing its own: list who I spawned, say something to one of them, say
something back to whoever spawned me. Each hand-written copy disagreed
slightly with the delivery path about what an address was, and the copy that
disagreed is the one where a message was reported sent and read by nobody.

The descriptions are part of the mechanism rather than decoration. An agent
never sees this module; the description is its whole documentation, and the
distinction between telling something and stopping it is only useful if the
tool says which is which.
"""

from pydantic import BaseModel, Field

from lup.actors.cohort import ActorCohort
from lup.actors.roster import SpawnedActor
from lup.channels.models import Door
from lup.mcp import LupMcpTool, ToolError, lup_tool


class NoInput(BaseModel):
    """A tool that asks the cohort about itself takes no arguments."""


class SpawnListOutput(BaseModel):
    """Every agent this session spawned, still working ones first."""

    spawns: list[SpawnedActor] = []


class SpawnSayInput(BaseModel):
    address: str = Field(
        description=(
            "Which spawn to reach. Anything the spawn listing printed works, "
            "including the bare id"
        )
    )
    text: str = Field(description="What the spawn should read")
    redirect: bool = Field(
        default=False,
        description=(
            "Whether to stop the spawn rather than inform it. A redirect "
            "refuses its next tool call and hands back this text as the "
            "reason, so it cannot carry on without reading why. Use it when "
            "the task was wrong, not when a fact has merely changed"
        ),
    )


class SpawnSayOutput(BaseModel):
    address: str
    delivered: bool
    outstanding: int = Field(
        description=(
            "How much is queued for this spawn and not yet handed over. "
            "Nonzero after a spawn has ended means it read none of it"
        )
    )


class TellSpawnerInput(BaseModel):
    text: str = Field(description="What whoever spawned you should know")
    in_reply_to: str = Field(
        default="",
        description="The id of a message or question this answers, if any",
    )


class TellSpawnerOutput(BaseModel):
    delivered: bool = Field(
        description="Whether the message reached the cohort's record"
    )


def create_cohort_tools(
    cohort: ActorCohort, door: Door = Door.AGENT
) -> list[LupMcpTool]:
    """The three verbs an agent needs to stay in contact, bound to one cohort."""

    @lup_tool(
        "List the agents you have spawned and what each was asked, with the "
        "ones still working first. Their addresses are what the say tool "
        "takes. Use it when you want to steer something you started and do "
        "not remember its address, or to see what a finished spawn concluded "
        "without re-reading its output. Returns {spawns: [{address, kind, "
        "task, running, summary, error}]}.",
        name="spawn_actors",
    )
    async def spawn_actors(_params: NoInput) -> SpawnListOutput:
        return SpawnListOutput(spawns=cohort.live())

    @lup_tool(
        "Say something to an agent you spawned, while it is still working. "
        "It lands in front of that agent's next tool call whether or not it "
        "thinks to look, so nothing has to be arranged with it in advance.\n\n"
        "Two verbs, and the difference matters. A message rides alongside "
        "the agent's next call and it keeps going — use it to hand over a "
        "fact it could not have had: a bound you just computed, a result "
        "that makes half its task moot. A redirect refuses that call and "
        "hands back your text as the reason, so the agent cannot take one "
        "more step down what it was doing without reading why it was "
        "stopped — use it when the task itself was wrong.\n\n"
        "This is what makes a long spawn worth starting: an agent checking "
        "the wrong statement, or working a branch you have since closed, is "
        "otherwise unreachable until it finishes. Address it by anything the "
        "spawn listing printed — the bare id works. Returns {address, "
        "delivered, outstanding}, where outstanding counts what is queued "
        "and not yet handed over: a spawn that has ended reads nothing more.",
        name="spawn_say",
    )
    async def spawn_say(params: SpawnSayInput) -> SpawnSayOutput:
        actor = cohort.reaching(params.address)
        if actor is None:
            known = ", ".join(spawn.address for spawn in cohort.live()) or "none"
            raise ToolError(
                f"no spawn of this session answers to {params.address!r}; "
                f"this session has spawned: {known}"
            )
        cohort.say(actor, params.text, redirect=params.redirect, door=door)
        return SpawnSayOutput(
            address=actor.label(),
            delivered=True,
            outstanding=cohort.outstanding(actor),
        )

    @lup_tool(
        "Tell whoever spawned you something, without waiting for a reply. "
        "Use it to volunteer what you have found, to flag a consequence for "
        "whoever picks your work up, to answer something you were asked, or "
        "to say that you are blocked on something you cannot do yourself — "
        "a gate that refused you, a file you cannot remove.\n\n"
        "This never blocks and never stops anything. If you need a decision "
        "before you can continue, that is a question and not a message; ask "
        "it as one. What this is for is everything that is worth someone "
        "knowing and is not worth stalling you.\n\n"
        "It goes to one address that a person reads, not to the other agents "
        "working alongside you.",
        name="tell_spawner",
    )
    async def tell_spawner(params: TellSpawnerInput) -> TellSpawnerOutput:
        cohort.tell_spawner(params.text, door=door, in_reply_to=params.in_reply_to)
        return TellSpawnerOutput(delivered=True)

    return [spawn_actors, spawn_say, tell_spawner]
