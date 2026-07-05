"""Source scanning for development tooling: review notes and forbidden shapes.

`common` holds the scanning core the two scanners share — comment-column
tokenization, docstring detection, ignore-directive matching, file-level
opt-out, and the line cursor. `markers` lists `# lup:` review notes;
`antipatterns` audits forbidden code shapes.
"""
