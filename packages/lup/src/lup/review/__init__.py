"""Review-comment and forbidden-shape scanning for development tooling.

`common` holds the scanning core the two scanners share — comment-column
tokenization, docstring detection, ignore-directive matching, file-level
opt-out, and the line cursor. `markers` lists review notes; `antipatterns`
audits forbidden code shapes.
"""
