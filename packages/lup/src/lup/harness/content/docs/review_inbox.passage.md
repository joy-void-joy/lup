# Review inbox

The `review-inbox` module gives an operator one browser page for the pending
approval queue across repository worktrees. It is independent of the `sandbox`
module. Declining it removes the browser commands and launch service; the core
`dev questions list`, `show`, `answer`, `reject`, and `cancel` commands remain.

Native Claude and Codex harness launches start or reuse one background inbox
per repository on the host. Active harness sessions share it, including sessions
in sibling worktrees. Closing or interrupting a harness releases its ownership;
the last session's exit stops the server even while the browser remains open.
An abruptly terminated launcher also releases ownership. `--generate-only`
generates artifacts without starting an inbox.

`dev questions status` reports the background endpoint and active session count
without revealing its browser credential. Inside an agent session it reports only
the endpoint advertised by the launcher, without claiming to verify availability.
The operator uses `dev questions open` to open an existing background inbox or
`dev questions stop` to stop it explicitly, including while harnesses are active.
`open` never creates an unattended server; when no background inbox is running,
start a harness or use `serve`. These operator commands run outside agent sessions.

`dev questions serve` runs a separate foreground server in the current terminal.
Ctrl+C stops that server; closing a harness does not stop it. `--root <checkout>`
selects a repository instead of the current one, and repeating it watches the
selected repositories together. `--host` selects a loopback address, `--port`
selects the foreground port, and `--no-open` keeps the browser closed. If that
port is already occupied, use another port or stop the background inbox with
`dev questions stop` before serving.

Native launches try their preferred port and select an available port if it is
occupied by another listener. They authenticate a recorded service before reusing
or stopping it. A recorded service without session ownership is replaced during
launch; an unrelated or manual listener is left alone. Background services retain
their browser assets beside private host state, so removing a source worktree
does not break the page while another harness still owns it.

The page shows complete commands and file changes, pending requests, decision
history, and requester identity. Approve or reject with an optional note.
Review decisions are recorded durably before requester notification, and a
notification failure does not undo the decision. The requesting runtime must
retry the exact operation; the browser never executes it.

The local server uses a bearer credential, loopback binding, and request-origin
checks. Its private local state is not committed. An edit whose preimage changed
cannot be approved until a fresh request captures the current content.

## Reviewing requests

The inbox titles requests from captured evidence: a file's action and path,
the number of files, or the command to run. The exact operation, requester,
rule, reason, command or captured file diff, and recorded answer remain visible.
The default view includes files that require review and highlights newly
introduced rule exceptions. Files the policy allows automatically or explicitly
leaves to the native provider, and existing exceptions, remain available in the
full-operation view. A captured deferral means Lup requests no approval for that
file; the native provider still applies its own permissions. Approval still applies
to the exact complete submission. Where recorded evidence cannot establish a
file's status, it remains visible rather than being treated as automatically allowed.
The file navigator shows change counts and supports searching paths. Select
one file to inspect its colored, numbered diff or complete Before, After and
Raw views; `[` and `]` move between files. A shared directory appears once,
with complete paths available for inspection. The queue, navigator and evidence
panels scroll independently; smaller screens offer panel switches.
Typed `lup: ignore[...]` comments are highlighted in the code and grouped by
rule; existing exceptions appear only in the full-operation view. Expand a
group for written reasons and occurrence links, or use `n` and `p` to jump
between exceptions.

Approve or reject one question with an optional note. Auto-advance opens the
next pending request after a successful decision; turn it off to stay on the
answered request. New arrivals do not move a selection already under review.
Use `j` / `k` for next / previous request, `Shift+A` to approve, `Shift+R` to
reject, `c` to open and focus the collapsed comment, and `?` for shortcut help.
Decision buttons stay visible beneath the selected evidence. Shortcuts pause
in text fields, and holding a decision key cannot answer another request.

Use **Copy link** to share a request without sharing a credential. Links use
`#review=<question-id>`; copied links also name the checkout to distinguish
identical IDs. They open the exact pending or historical request,
including in another tab of an already authorized browser. Back, forward, and
changed links select the corresponding request. A missing ID stays selected
while the inbox watches for it; it never silently opens a different request.

The decision is recorded in the
same durable relay that the terminal commands use, so a browser and terminal
answering concurrently cannot replace each other's answer. Session notification
is best effort after the answer is saved. The browser can advance while the
server completes delivery; a missing route or failed delivery does not erase
the answer. Each browser answer retains a separate notification outcome
in `.lup/review-notifications/`, bound to its question, fingerprint and answer
timestamp. Answered requests show a compact status with expandable details:
mail queued, native queue accepted, failed or unconfirmed. Interrupted attempts
remain unconfirmed; diagnostics failures never undo the recorded approval.
Native retries notify only a unique registered requester whose bound native
session matches the request. Queue acceptance does not prove the agent read
the message. A native-hook approval still requires the agent to retry the exact
tool call. The inbox never executes a reconstructed command.

The server's capability is carried in the browser URL's fragment, which HTTP
requests do not send to the server. The
page removes the credential from the address and keeps it in local storage for
that exact origin: scheme, hostname, and port. Tabs at that origin authenticate
queue API requests with its bearer credential, so shared request links carry
only review identity. The credential is never a cookie or read from stale
session storage. A fresh launch link updates other open tabs through storage
events; opening it in the same tab keeps the selected review and draft comment.
If browser storage is blocked, the page explains that access is limited to the
tab that opened the launch link. The page and its assets contain no credential.
Restarting the server replaces the capability; reopen its printed launch link.
Treat the full address as an operator credential and keep it out of agent
messages. The server binds loopback, checks Host against DNS rebinding, and
checks the origin of answer submissions. These controls protect the browser
surface; they are not isolation against arbitrary processes running as the
operator's user. The session's filesystem and process boundary remains part
of the authority boundary.


## Runtime parity

`uv run lup-devtools dev questions serve` provides the same foreground browser
inbox for durable review records from either runtime. One operator capability
protects its queue APIs; the same captured diffs, exact commands, approval and
rejection notes, and atomic answer transition apply to both. The command that
mints that capability is operator-only under both generated policies. Claude's
native permission requests remain native requests; the inbox displays what
was parked in the durable relay. Browser settlement records the answer before
returning to the browser; notification continues in the server, and its
failure does not undo the decision.
Queue acceptance alone does not prove that a particular recipient took a turn.
The Codex idle-wake integration test measures the complete browser-to-relay
path on CLI 0.156.1. The fixture forwards its declared launch identity into a
real native stdio child. Its owned heartbeat recovers a pulse aged beyond the
120-second presence window while preserving the hook-bound route. A completed
first turn is followed by an autonomously queued review
notification and a second completed turn carrying the operator's nonce to an
inert local Responses endpoint. It uses the recorded home and normal native
Unix socket discovery, without manually resuming the thread. Native
approval releases an exact retry through that runtime's existing hook path;
the inbox does not execute the operation itself.
