"""The Codex engine's construction door: ``create_codex`` + the composition.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`) over the translation in
:mod:`lup.adapters.clients.codex.translate`, then composes
:class:`~lup.adapters.clients.codex.sessions.CodexSessions` — the
runtime's one native component — into the one client shape (the runtime
reports a turn only once complete, so the stream slot is filled by
replay).
"""

from lup.adapters.clients.Client import Client
from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.clients.codex.translate import build_codex_native
from lup.adapters.clients.codex.sessions import CodexSessions
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.options import LupAgentOptions
from lup.realtime.relay import RealtimeMailbox


def create_codex(options: LupAgentOptions) -> Client:
    """Build a Codex-runtime client from neutral options.

    Consumes the subprocess mechanism payloads (served tool groups, env
    relay, writable roots) and ignores the in-process ones (hooks, tool
    servers — enforcement here is the runtime's native sandbox) and the
    Claude-only ``coding_harness_preset``/``sdk_sandbox`` shape flags. Subagent
    specs are served through the ``run_subagent`` tool group rather than
    run natively. Persistent mode surfaces the file-relay mailbox.
    """
    client = compose_codex(refuse_unconsumed("codex", options, build_codex_native))
    if options.realtime and options.realtime_dir is not None:
        client.mailbox = RealtimeMailbox(options.realtime_dir)
    return client


def compose_codex(native: CodexNativeConfig) -> ComposedClient:
    """Compose the Codex runtime's components into the one client shape.

    Codex contributes only its sessions — the runtime reports a turn only
    once complete, so the stream slot is left to the replay gap-filler.
    ``openai-compat`` reuses this composition over its own translation.
    """
    return ComposedClient(CodexSessions(native))
