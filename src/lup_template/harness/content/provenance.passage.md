- `{{ library_git }} rev-parse --abbrev-ref HEAD` — the branch the library would come from
- `{{ library_git }} symbolic-ref --short refs/remotes/origin/HEAD` — what the remote treats as stable

When they differ, {{ ask }}

Record the branch and the commit the answer settles on. Everything below is
about that commit — the acquisition mode pins its branch and the upstream
checkpoint is taken at it — so the checkout supplying the library has to be
standing there before you go on.

