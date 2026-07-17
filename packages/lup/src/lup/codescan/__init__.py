"""Source scanning for development tooling: review notes and forbidden shapes.

`common` holds the scanning core every scanner shares — comment-column
tokenization, docstring detection, ignore-directive matching, file-level
opt-out, and the line cursor. `markers` lists `# lup:` review notes;
`antipatterns` audits forbidden code shapes; `boundaries` keeps native
imports, native wire spellings, and kernel imports inside their sanctioned
homes; `capabilities` enforces the capability-ABC composition architecture
project-wide.
"""
