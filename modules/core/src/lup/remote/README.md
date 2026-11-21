# Remote

A room's `git push` and `git fetch`, carried out with the operator's own credentials, as their terminal has them, within what the project's declaration allows (`DESIGN.md`, *Defaults*). A room holds no SSH key and no login: lent into it, credentials would answer to nothing, since an SSH agent forwarded signs anything its keys sign, for every host they reach. `Remote` is one of lup's default modules.

## From a room

A room's git configuration rewrites each URL of the repository's remotes to `lup::<url>`, so git runs `git-remote-lup` for each push and fetch (`lup.environment.remote`), a fetch too, since a remote's URL may name an alias of the operator's ssh configuration, which only the part resolves. The helper turns each batch git hands it into one call of `Remotes`' services (`listed`, `pushed`, `fetched`), through the room's socket, so the call is the session's agent's. A source git names as written (`HEAD~1`) is resolved in the room's repository, and only object ids cross. What a refusal says is printed on git's standard error, and each ref's `ok` or `error` is git's to show. No upstream is recorded (`git push -u` pushes, and says it couldn't write `config`), since a room can't write `config`: the room's git pushes the current branch by default.

## What it does with them

`Remotes` is each project's part, in a container of its own, from the commit the operator approved, holding the project's git directory and the operator's SSH agent alone (`lup/hosting/README.md`, *Lending*), so what a store a room wrote could do to git reaches one project's directory:
- **Where it goes is the repository's word,** never the room's: a remote the repository's `config` names, which no room writes, pushed to at each of its push URLs, fetched from its first URL. A URL from the room, or a name only a file of the room's defines (`remotes/`, `branches/`), is refused. git runs pinned to the git directory (`lup.programs.git`, `Store`), reading no configuration but the repository's own.
- **Each update is held to the declaration's limits** before git runs (`Remote.actions`, `Remote.protected`): a ref git doesn't take; a protected one, a tag by default; the release branch (`Landing.released`), which only the operator merges into; the integration branch (`Landing.integration`) from a room, which moves only when the operator accepts a landing; a forced update (`+`, `--force`, `--force-with-lease`) unless the declaration allows `force-push`; a deletion unless it allows `delete-any`, or the branch has landed (`delete-landed`, the default). Beyond them, an action is refused, saying that allowing it is the operator's call.
- **A branch has landed** where its tip on the remote is in the history of the integration branch's tip there, both fetched into the store first, each commit's parents read from the commit alone; its deletion is pushed with a lease on the tip it checked, so one that moved since isn't deleted.
- **What a push publishes is told first:** each commit the remote lacks, one `Publishing` event each, then nothing leaves where a part hearing it refuses, its words on git's standard error (`lup/publishing/README.md`).
- **It pushes by object id,** one update a push, or the batch as one where git asked for an atomic push, forcing only an update git forced; a fetch brings the objects named into the store, writing no ref, after which each must be there. Neither runs from a store that reads objects from outside it (alternates, a link under `objects/`), through which a push would send another repository's history.

The operator's accept of a landing is to push through the same part, as the machine's, which may move the integration branch.

## Promises

`promises.py` runs git for real in a temporary directory: a forge's bare repository and the project's clone of it, its `config` naming the forge `origin`, ssh stood in for, never run. A room's push reaches its own branch and never the integration branch, the release branch or a tag; a forced push is refused unless the declaration allows it; a branch is deleted only once it has landed; a fetch writes no ref; a remote the repository doesn't name is refused; and a part refusing at `Publishing` keeps a push from leaving. The helper is lup's own code in a room and runs only there: its protocol is git's, as the second lup's helper spoke it for months.
