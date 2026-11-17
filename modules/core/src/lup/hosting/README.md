# Hosting: what runs on the operator's machine

Containers don't start themselves: something outside every container runs podman, and whatever runs podman can mount anything of the operator's, so it's as powerful as they are. In lup that something is a module like any other, `Hosting`: parts that hold the machine (`machine=True`), one for the whole machine (`shared=True`), run there from the home repository's approved commit, their doors checked by promises. The home repository's declaration selects it (lup's own does); a project's doesn't.

The only thing that isn't a module is the loader in the `lup` the operator installs, which starts these parts from the commit they approved.

## Who may call them

What's privileged in a machine part is for the machine's own parts alone: its services take `by: Machine`, a party only a call made where those parts run is, never a call carried from a container, the home repository's own branch among them. So code a project runs, an agent, and lup's own unapproved branch can ask for nothing the machine does for itself.

## Containers

`Containers` holds podman (`podman: Program`). It builds an image where its tag isn't there yet (`built`), a Containerfile's text tagged by its digest, so a changed definition is a new tag; starts a container, detached (`started`); and stops one (`stopped`). Every container it starts stands behind the same walls, whatever asked for it (`Walls`): the operator's uid inside, every capability dropped and no privilege gained, a limit on processes, reaped by `--init`, removed when it ends, no image fetched by a short name, no log kept. A directory mounted into a container is read-only unless its spec says, and lands at its own path, a path holding a comma kept whole. podman failing refuses the call that asked, saying why.

These are the second lup's room's walls, as measured with rootless podman 6.1 (`docs/field-notes.md`, *the engine's command lines*).

## Secrets

`Secrets` keeps each project's secrets, a JSON file each under its own data, outside every repository, readable by the operator alone, so a downstream project's user never learns where: lup asks them for a secret the first time a part holding it starts. Only the machine's own parts read one (`held`), handing a part the secrets kept for its project that it holds and naming those that aren't, for the operator to be asked for; another project's secret of the same name is never among them. Only the operator keeps one (`keep`, a command).

## Promises

`promises.py`, through the harness, the machine's parts started as the machine's own (`by.started(…, machine=True)`), podman stood in for as each promise scripts it (`programs={"podman": Scripted(…)}`): the gate checks what lup asks podman to do, and never runs it.
