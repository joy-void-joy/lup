Baseline the upstream checkpoint at *the recorded commit*, not at whatever the
remote's default branch points to. `--synced` reads the checkpoint from the
named checkout's HEAD, so that checkout has to be standing at the recorded
commit when this runs:

```
{{ project_devtools }} sync setup lup {{ library_checkout }} --branch <branch> --synced
```

`setup` records that checkout, the branch settled on above, and its HEAD as the checkpoint, so `{{ update_skill }}` only shows commits that land afterward. Plain `sync mark-synced lup` is wrong here: the shipped `sync.json` entry carries a URL and no branch, so it clones the remote's default branch and checkpoints *that* HEAD — so every commit the project already carries comes back as unported work once the branch merges.

A project that already consumed the library, and knows which commit it took, names it rather than moving a checkout to stand on it:

```
{{ project_devtools }} sync mark-synced lup --at <commit>
```

That is the case an adoption mid-stream is always in — the code is already here, and what is missing is only the record of how far it reached. Without the commit, marking synced claims every commit that landed afterward as reviewed, which is the one thing the checkpoint exists to prevent.

