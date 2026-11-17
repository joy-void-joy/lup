# Running a project's modules

How a project's modules run where `DESIGN.md`'s *Where code runs* puts them: the program on the operator's machine runs no project's code, so it reads a declaration's plan, starts containers from it, and carries calls between them; each container runs some of the project's parts and answers calls through their doors on a socket.

Its library side (`lup.running`) is what crosses: the plan (`plan.py`) and the messages (`wire.py`), which the program on the operator's machine reads too. Its environment side (`lup.environment.running`) is the program a container runs, `python -m lup.environment.running`, told what to do as one JSON message on its input.

## The plan

A declaration is code, so it's loaded where running a branch's code is harmless, a container, which prints its plan (`Planning`). The plan is each part of each module, what it holds (`Holds`), the file its class is defined in (what an approval calls out where it changes), and each method a party calls behind its door with who may call it (`Doorway`), the tools a session is told of, and the files loading the declaration imported, relative to the project's root.

What a part holds says where it runs (`PartPlan.apart`):
- **holding nothing,** it runs with every other such part in the project's own container, from the project's running commit;
- **holding a secret, the machine, what only approved code may, or being the whole machine's** (`shared`), it runs apart, from a commit the operator approved: a container of its own, with what it holds alone, or the machine itself. A shared part runs once on the machine, from the home repository, and serves every project.

The files are what loading the declaration imported, which an approval may point at; what it approves is the commit whole, its diff read from git's objects on the machine (`lup/hosting/README.md`, *Approvals*).

## A container

Started (`Start`), the program loads the declaration from the project's tree as mounted, makes the parts it's told to (every part holding nothing, or the ones named), each with its secrets, read from a file each in the directory it's given in memory and removed before any part starts, and a directory of its own for each field typed `Data` or `Runtime`, and answers each call coming in on its socket, one per connection. A service its parts' code calls is answered in the container where its part runs there, and otherwise sent to the program's socket (`Outward`), which carries it to where the part runs. Who calls is the program's word, from the socket a call came in on: a container sends a call with no `by`, and refuses one coming in without it, so a path that forgot to vouch refuses rather than lets anyone through. Stopped, it runs its parts' `Stopping` methods before it ends.

## What crosses

Each message is one JSON object, a line, carrying the version of its shape (`format`), read first (`read`): a reader meeting another version refuses in words, naming both and how to update, rather than failing on a field it doesn't know, as the second lup's host did when a newer copy wrote an approval it couldn't read. A call is a tool's, a service's, an action's or a command's (`Call`), its `by` one of the core's parties, tagged by `party`, which only the program on the operator's machine fills in, and never `Machine`, which is only ever a call made where the machine's parts run; an answer is what the method answered, as JSON (`Answered`), or the refusal (`Declined`). Nothing that crosses makes a container fail: what isn't a call, or is of another version, is refused.

## Promises

`promises.py`, checked through the harness, whose `Started.plan` is the declaration's plan and `Started.crossed` answers a message as the container running its parts would.
