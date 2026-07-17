# The sync registry

`lup-devtools sync` keeps a registry of other repositories this project
exchanges improvements with, and reviews their commits since the last sync
(`/lup:update` and `/lup:import` are built on it). Two files declare what to
track.

## sync.json (committed)

The template's registry default. It ships listing only the `lup` entry — the
repository this template comes from — so a fresh project can immediately pull
template improvements:

```json
{
  "projects": [
    {
      "name": "lup",
      "url": "https://github.com/joy-void-joy/lup"
    }
  ]
}
```

`sync.json` is template scaffold, not personal state. **Agents must never
modify the tracked `sync.json`**, and neither should routine project work:
every personal registration belongs in `sync.json.local`. The edit policy
enforces this by treating `sync.json` as a protected path that requires
approval before any edit.

## sync.json.local (gitignored)

Personal registrations: local paths, per-project sync state
(`last_synced_commit`), branch overrides, `"ignore": true` opt-outs, and any
additional projects. Entries override `sync.json` entries by project name, or
add local-only projects. `lup-devtools sync setup` and `mark-synced` write
here — never to `sync.json`.

## Direction-neutral by design

The registry deliberately has no direction in its name: "sync" names the
mechanism, and whether a tracked repo is upstream or downstream depends on
where you sit.

- **A project built on the template** keeps the shipped `lup` entry and pulls
  improvements *from* it — from that seat, `lup` is an upstream.
- **The lup repository itself** sets `"ignore": true` for its own entry and
  registers the projects built on it in `sync.json.local` — from that seat,
  the tracked repos are its downstream fleet, whose emerged patterns
  `/lup:update` generalizes back into the template.

Same registry, same tooling, opposite seats.

## Legacy names

Repositories created before the rename may still have `downstream.json` /
`downstream.json.local`. The sync tooling reads them as a fallback when
`sync.json` / `sync.json.local` are absent and emits a deprecation warning;
migrate by renaming the files.
