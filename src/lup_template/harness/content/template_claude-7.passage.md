## Diagnostics after an edit

Every edit is type-checked, by the hook rather than by an editor's language server. The checker runs in the checkout that holds the file you edited, so its answer is about the copy you changed. Findings for that file arrive as a hook error naming the line; nothing arrives when it checks out clean.

That rooting is the point. A language server the runtime starts is rooted once, where the session opened, and keeps that root after work moves to a worktree -- so it resolves the same module names against the launch checkout and reports, with no sign anything is wrong, about a file nobody edited. Anything a session-wide language server tells you about a file in a worktree is worth confirming against this.

The `codeintel` tools answer navigation questions the same way, per question rather than per session. **Use them actively** -- they resolve imports and aliases, which grep cannot.

