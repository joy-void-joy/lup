"""Source scanning for development tooling: review notes and rule families.

`common` holds the scanning core the scanners share — comment-column
tokenization, docstring detection, token-masked line projections,
ignore-directive matching, file-level opt-out, and the line cursor. `markers`
lists `# lup:` review notes; `antipatterns` audits forbidden code shapes;
`boundaries` enforces the adapter-import, native-spelling, and kernel-import
seams; `capabilities` enforces capability-ABC architecture; `registry` indexes
every rule family with its definition site for the generated rule reference.
"""
