# Contributing generated harness changes

Work in a feature worktree and change canonical Python first. The generated
Claude, Codex, and shared marketplace artifacts are committed because users
launch them directly and hooks must run without importing the checkout.

## Local loop

1. Edit typed content under `devtools/harness/content`, policy declarations,
   or an adapter renderer.
2. Run `uv run lup-devtools harness generate all`.
3. Review canonical and generated diffs together. Prompt changes should be
   understandable from their content module; policy-data changes should trace
   to `HookSet` or canonical rule objects.
4. Run `uv run lup-devtools harness check all`. This is read-only and fails on
   desired-tree, ownership, executable-mode, or stale-file drift.
5. Run `uv run lup-devtools dev check` before committing.

The pre-commit hook regenerates and stops when generation changes tracked
files. This makes omitted generated output visible without silently adding it
to the commit. Pull-request CI runs formatting, lint, type, unit, anti-pattern,
native-boundary, and generated-drift checks. The two user-deferred review notes
remain visible in the complete local `dev check`; they are not silently removed
or treated as unrelated CI failures.

## Reviewing generated artifacts

- Treat `.lup-ownership.json` as generated proof, not hand-authored metadata.
- Verify both native trees when a portable declaration changes.
- Verify only the owning adapter tree for an adapter-private renderer change.
- Confirm `hooks/runtime/kernel.py` is the canonical kernel copy and
  `policy_data.py` contains configuration only.
- Do not commit credentials, plugin trust, installed cache contents, active
  sessions, or local profile configuration.
- Do not resolve a conflict by deleting an unknown file. Classify ownership or
  leave the conflict explicit.

## Native evidence

Deterministic fixtures run on every change. The scheduled native workflow runs
the full integration marker, including the installed Claude and Codex binaries
for the session-id, pager, dynamic-tool-schema, and blocked-edit boundaries.
`harness doctor` compares installed versions with the typed evidence ledger. A
newer component warns locally and fails the nightly strict check, but the live
job still runs so the drift cannot suppress the evidence needed to review it.

The credentials-gated native job is a real workflow result: a failure stays
failed, and a skipped job is not release evidence. A release cut requires two
consecutive scheduled runs with successful `native` jobs and no version drift;
review the probes and `docs/native-capabilities.md` rather than updating the
ledger mechanically.

## Rule documentation

`docs/rules.md` is generated from executable rule objects:

```bash
uv run lup-devtools dev rules
uv run lup-devtools dev rules --check
```

Change the rule object and tests first, regenerate the reference, and review
the diagnostic and matching shape together. Never hand-edit the generated
reference.
