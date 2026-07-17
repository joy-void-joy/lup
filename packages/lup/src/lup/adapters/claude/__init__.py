"""Claude-specific capability implementations and composition roots.

The runtime side: ``runtime`` opens Claude SDK sessions behind the
:mod:`lup.runtime` contracts, ``config`` holds profile and compatible-endpoint
transforms, and ``profile_store`` is the personal account registry the CLI
composition roots read. The harness side: ``harness`` renders canonical
declarations into the ``.claude`` plugin tree (including the generated policy
dispatcher), ``harness_runtime`` probes the installed CLI for doctor
evidence, ``native`` decodes hook payloads into :mod:`lup.policy` events and
renders decisions back to the wire, and ``hooks`` translates neutral hook
configs into SDK handlers.
"""
# lup: I'm very confused. Both plan.md and plan-content-kernel.md insisted on using the philosophy of having ABC and having the backend implementation only being filling of those ABC in (the tacocast philosophy)
# lup: But both adapters/claude and adapters/codex are anything but, they declare their own ProfileStore, etc... Why?
