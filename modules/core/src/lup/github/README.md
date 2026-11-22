# GitHub

The tools sessions act on GitHub through, with the operator's own login, as `gh` on their machine has it, within what the project's declaration allows (`DESIGN.md`, *Defaults*). `GitHub` is one of lup's default modules: a project not on GitHub drops it, or puts its forge's module in its place.

## What agents may do

`GitHub.actions`, every action lup carries out unless a project drops one, each with its reason:
- **`read`:** `read_issue` and `find_issues`, on any repository the operator's login can read, named as `owner/name`; a pull request is read with its reviews and the comments on lines of its diff among its comments, and its checks. The `issue_state` service says whether an issue is open, as the gate asks of what a `defer` or an `ignore` waits on.
- **`file-issue`, `edit`, `close-issue`, `comment`, `edit-comment`:** on the project's own repository alone: file an issue, edit an issue's or a pull request's title, body and labels, close an issue with a reason or reopen it, comment, edit a comment.
- **`pull-request`:** open a pull request from a pushed branch into the branch work lands on, a draft unless asked otherwise, and mark a draft ready.

There's no merge and no approval: either would show the operator's name on a decision they didn't make. Work lands through `land`, and what reaches the release branch is theirs.

## How it acts

`Forge` is each project's part, in a container of its own, from the commit the operator approved, holding their GitHub login alone (`GitHubLogin`): the token `gh auth token` prints on their machine as the part starts (`lup/hosting/README.md`, *Lending*), so a login they renew is the one the next start uses. Each tool:
- **writes to the project's own repository,** named by the remote it lands on (`Landing.remote`), as `remote` says where that is (`Remotes.hosted`), an alias of the operator's ssh configuration resolved as ssh resolves it; a remote that isn't on GitHub writes nowhere. A repository a call names is read only where it's `owner/name` as GitHub spells one, so nothing else reaches `gh --repo`.
- **is held to `GitHub.actions`** before `gh` runs, and refused beyond them, saying that allowing it is the operator's call.
- **tells what it would post at `Publishing` first** (`lup/publishing/README.md`): a refusal there posts nothing.
- **runs `gh` with every value as `--flag=value` and a body on its input,** never through a shell, its login in `GH_TOKEN`, never on disk, and its own configuration in memory.

Closing or reopening posts its comment first, then closes or reopens, so a close that fails leaves the comment said, which the answer reports; each checks first that the number is an issue in the state it changes, a pull request's closing being the operator's. A comment is edited by its link, found on its thread in the project's own repository, so a comment elsewhere the login could edit is never reached. An edit keeps GitHub's edit history, which only the operator can clear: the tools that edit say to tell them where an edit takes out something that shouldn't be public.

## What's left

- Writing to the other repositories the operator relates to a project, a harmon agent filing an issue on lup's, once a declaration names them (#2).

## Promises

`promises.py`, `gh` stood in for as each promise scripts GitHub's answers, the project's clone made for real with its `origin` on GitHub, ssh stood in for: an issue goes to the project's own repository, as its remote names it; a post a part refuses at `Publishing` isn't posted; an action the declaration drops never reaches `gh`; a repository named otherwise than `owner/name` is refused; closing a pull request is refused before its comment; an issue's state is GitHub's word.
