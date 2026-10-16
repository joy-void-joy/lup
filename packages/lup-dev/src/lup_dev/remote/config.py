"""The room's git configuration: each of the repository's remotes through lup's helper, and nothing that writes the repository's `config`.

`docs/host-tools.md`, *git through a remote helper*. A room's git reads the
repository's `config`, mounted read-only, and a file of its own in place of the
operator's `~/.gitconfig`, which isn't mounted (`docs/launch.md`, *The
mounts*): "if `GIT_CONFIG_GLOBAL` is set, neither `$HOME/.gitconfig` nor
`$XDG_CONFIG_HOME/git/config` will be read" (`git(1)`). That file holds:
- for each URL the repository's remotes name, their push URLs among them,
  `url."lup::<url>".insteadOf = <url>`, so git runs lup's helper for each push
  and fetch: a rewrite outside the repository's `config` applies to a URL inside
  it, for a push and a fetch alike (measured, git 2.56.0 on the host and 2.55.0
  in the room), and as the longest match it wins over the repository's own.
  Fetching needs it as much as pushing, since a remote's URL may use an alias of
  the operator's SSH configuration, which the room can't resolve;
  `pushInsteadOf` would leave fetches failing, and is ignored for a remote with
  a push URL of its own;
- `branch.autoSetupMerge = false` and `push.default = current`: the room's writes
  to `config` fail, so nothing records an upstream there, and a branch's push
  names its remote or relies on `push.default`;
- `lup.requestSocket`, the launch's request socket as the room sees it, where the
  helper sends its requests.

The URLs are read from the repository's `config` as written, which is what the
room's git rewrites; git writes each value (`git config --file`), quoting it.
git runs in the repository's git directory pinned there (`Git.pinned`), so a
`commondir` a room planted at its top leads it to no other `config`.
"""

from typing import TYPE_CHECKING

from lup_dev.git import Git, nul_separated

if TYPE_CHECKING:
    from pathlib import Path


def room_config(repository: Path, path: Path, requests: Path) -> None:
    """Write the room's git configuration to `path`, for the repository whose git directory is `repository`.

    `requests` is the launch's request socket, where the room mounts it.
    """
    git = Git.pinned(repository)
    own = ["config", "--file", str(repository / "config"), "--no-includes", "-z"]
    keys = nul_separated(
        git.run(
            *own,
            "--name-only",
            "--get-regexp",
            r"^remote\..*\.(url|pushurl)$",
            ok=[0, 1],
        ).stdout
    )
    urls = dict.fromkeys(
        url
        for key in dict.fromkeys(keys)
        for url in nul_separated(git.run(*own, "--get-all", key).stdout)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    written = str(path)
    for url in urls:
        git.run("config", "--file", written, "--add", f"url.lup::{url}.insteadOf", url)
    git.run("config", "--file", written, "branch.autoSetupMerge", "false")
    git.run("config", "--file", written, "push.default", "current")
    git.run("config", "--file", written, "lup.requestSocket", str(requests))
