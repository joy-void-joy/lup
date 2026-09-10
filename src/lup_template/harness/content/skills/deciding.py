"""The decision walk the design-facing skills share.

Brainstorm, distill, and meta each turn a pile of claims — the user's ask, a
prior session's notes, a worked example — into decisions the user has made
rather than inherited. The walk is the same in all three: read and verify
before asking, put every decision to the user whole and numbered, rebuild a
concept from its failure when asked, check what can be checked now, and
close with a briefing the user did not have to watch being written.
"""

import lup.harness.models as models


def deciding_parts() -> list[models.PromptPart]:
    """Walk every decision from scratch and leave each one the user's."""
    return [
        models.TextPart(
            text=r"""
## Walking the Decisions

### Before the first question

- **Read everything the user named, whole**, and the worked examples behind
  it — the repository it happened in, the notes it left, the register of what
  went wrong. Design from a failure inventory is grounded; design from first
  principles is a guess.
- **Prior notes are claims.** A `tmp/` design, an earlier session's
  conclusion, a document headed "settled": each records what an agent argued,
  approved by nobody until the user says so here. Say you are treating them
  that way, and walk each decision they contain as if it were new.
- **Verify every claim about the tree before repeating it** — a budget
  figure, "this appears nowhere in policy", "no such type exists". Open with
  where the tree disagrees with the notes; a discrepancy there reshapes the
  questions more than any answer will.

### The questions

- **Number them, in plaintext, all at once.** The user answers a batch by
  number in their own words and skips what is yours to decide; the structured
  facility takes one fork at a time and is kept for a single fork or a
  confirmation.
- **Each stands alone**: the failure it answers, drawn from the worked
  example with where it is recorded; the options; your recommendation marked
  as yours; one question. Someone who read nothing else can answer it.
- **Open every later reply with what is now decided, read back in your
  words.** A misreading surfaces there — "I'm unsure that should be on by
  default" — and costs one line to fix instead of a build.

### When the user says "walk me through" or "from scratch"

- **Rebuild the concept from the problem it solves** — what went wrong, what
  any solution has to provide, then the shape — defining every term. Do not
  restate the option list in more words.
- **When the user offers their own shape, test whether it dissolves your
  objection** before defending the objection. It often does.
- **When the user gives a scenario, trace it literally** against the design
  as stated and say where it breaks. The break is the finding; a design that
  survives only the cases you chose is not settled.

### Verify, do not defer

- **A claim you can check in this session is checked now** — a CLI version,
  whether a hook fires, what a payload carries — with a script under `tmp/`
  when a command will not do. A stale document the check corrects becomes the
  first task of the build, on its own branch.
- **"Did you check?" gets a plain yes or no**, with what you read against
  what you ran. A ledger quoted is not a probe run.
- **A recommendation rests on claims already checked.** Marking one "I have
  not verified this" and recommending it anyway hands the user the check and
  dresses a guess as a caveat; the questions they push back on are the ones
  where that happened. Run it first. When the check refutes the reason, say
  so and give the recommendation the evidence now supports — a reversed
  recommendation with a measurement behind it is the turn worth taking, not
  an embarrassment to soften.

### A second case study

When the user names another repository that went through the same thing,
read it and derive the common denominator. What only one case needs leaves
the scope **by decision**, recorded as such, not by silence.

### Closing

- **The deliverable is a briefing rewritten whole** — `DESIGN.md` before a
  project exists, a `tmp/` briefing inside one: what is settled, what is out
  of scope and why, the build order, the empirical checks still owed, and what
  stays open, marked as the user's. Remove the notes it supersedes.
- **Do not start building.** How the work is cut into branches and when it
  starts are the user's; ask, with a recommendation.
- **Then ask what made the conversation work** and put it into this skill.
"""
        ),
    ]
