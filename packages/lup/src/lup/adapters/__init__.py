"""Native implementations of Lup's independently composed capabilities.

Provider configuration, wire formats, event decoding, harness rendering, and
session construction stay in the named adapter package. Portable callers use
the narrow contracts and semantic models in :mod:`lup.runtime`,
:mod:`lup.harness`, and :mod:`lup.policy`.

Parity between the two adapters
===============================

Parity here means each adapter answers every portable question its runtime
can answer, and says why where it cannot. It never means matching module for
module: the two runtimes are reached differently — one through an SDK, one
through a JSON-RPC process — so a module with no counterpart is usually that
difference showing rather than something missing.

What follows is a module-by-module reading of both packages in both
directions. Each unmatched module says which it is, so a later reader can
tell a decided asymmetry from an unnoticed one.

Matched, and answering the same questions
-----------------------------------------

``harness.py`` — both spell one :class:`~lup.harness.contracts.NativeSpellings`,
which is closed by construction: a method added there cannot be left
unanswered by either. Two methods are answered by declining (see below).
Codex additionally compiles native prefix rules and a project config file,
because it reads shell allows and tool servers from files Claude has no
equivalent of; Claude renders a separate MCP artifact for the same reason in
reverse.

``native.py`` — both decode their runtime's own tool payloads into the shared
policy vocabulary and render a decision back. Claude sees an edit preimage
and Codex an opaque patch, which is why one has separate edit and write
operations and the other one file-change operation; Codex's renderer also
carries ``supports_ask`` because approval at its hook boundary had to be
evidenced before it could be claimed.

``config.py``, ``login.py``, ``runtime.py``, ``assets/policy_dispatcher.py``
— matched, class for class.

``hooks.py`` — matched in purpose, not in shape. Codex adds an approval
responder because its transport elicits approvals over the wire that the
Claude SDK resolves internally.

``harness_runtime.py`` — Codex adds a plugin installer and a cache digest,
because its trust model requires an installed, verified plugin where Claude
trusts a directory it is handed.

``selection.py`` — both render a portable request into their own session
configuration and refuse nothing silently: Codex names the three fields it
has no spelling for and raises rather than dropping them. Each splits
rendering from building, so an application can stack a ``ConfigTransform``
onto what a request asked for before a session exists — which is what the
transforms in each ``config.py`` are for, and what the Codex side had no
entry point to until the split was made on both.

``usage/`` — both read an account's metered windows and its daily tokens into
the report in :mod:`lup.usage`, which owns the display, the pacing bars, and
the ``--json`` snapshot. This was Claude-only, on the belief that the other
runtime published nothing to read; it publishes both readings over its own
app-server, so the display was made neutral and each adapter left holding
only what its account actually reports. What still differs is that one
account splits its tokens by model and the other does not, which is why one
draws a legend and the other has none to draw.

Unmatched, and deliberately so
------------------------------

``codex/app_server.py``, ``codex/patch.py`` — the JSON-RPC transport and the
patch-envelope decoder. Both exist because the Codex runtime is a process
speaking a wire protocol; the Claude runtime is a library, and a counterpart
would have nothing to do.

``codex/home.py`` versus ``claude/profile_store.py`` — the same concern
answered differently, not a gap. Claude keeps several accounts as several
config directories, so its store is a registry of named profiles. Codex
keeps one rotating credential the runtime refreshes in place, so its store is
per-worktree homes converging on one account home; copying that credential
and diverging would strand every stale copy.

Declined rather than absent
---------------------------

Two portable ideas have no Codex spelling, and each says so through an
:class:`~lup.harness.contracts.Unsupported` carrying the reason: escaping the
sandbox for one call, whose Codex overrides exist only as session-level flags
on its binary, and handing a document whole to a tool, which nothing in its
roster does. Both are declared answers rather than missing methods, so prose
that asks for either gets nothing rather than an approximation, and an audit
gets the reason.
"""
