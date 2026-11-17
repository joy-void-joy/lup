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

## Carrying

Each container lup starts gets a directory of sockets of its own (`directory`), mounted at `/run/lup` in it: `calling.sock`, which it calls out through, and `listening.sock`, which it answers calls on. Who a call is by is `Carrying`'s word, from the directory it came in on, never what the call says: a project's container is its project's `Codebase`, the operator's own directory, which no container mounts, is the `Operator`, and a directory that's neither is refused (`routed`). A call is answered by a part of the caller's project, the one the operator names for theirs, or else by a part one for the whole machine. Every socket is a file: rooms share the machine's network, which takes in Linux's abstract sockets, so lup never uses one. Binding the sockets and forwarding calls is the environment's; this part keeps where each part runs (`placed`) and decides each route.

## Projects

`Projects` runs a project (`open`, the operator's command, or `opened`, the machine's service): it plans the project's declaration in a container, which prints the plan, then starts one container for every part holding nothing, and one of its own for each part holding something that isn't the machine's, given only the secrets that part holds, as files in its socket directory. A part whose secret nothing kept waits, not started, until the operator gives it. Each container mounts the project's tree read-only, and the machine's uv-managed interpreters read-only at their own paths, nothing fetched, its Python environment and uv's cache in directories of the project's own under this part's data, so a container starts on what it synced before.

## Promises

`promises.py`, through the harness, the machine's parts started as the machine's own (`by.started(…, machine=True)`), podman stood in for as each promise scripts it (`programs={"podman": Scripted(…)}`): the gate checks what lup asks podman to do, and never runs it.
