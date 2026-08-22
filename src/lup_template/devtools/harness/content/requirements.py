"""The external programs this repository needs, and what going without costs.

Mechanism and batteries both come from the library: `lup.harness.requirements`
says what a requirement *is*, `lup.harness.toolchain` offers one constructor
per program lup has an opinion about, and what is *this project's* is the
composition below -- which constructors it takes, what it passes them, and
anything lup never heard of.

Two axes are worth reading together, because either alone misreports. *Where*
says who is expected to have it: a container runtime is the host's and must
never be the image's, a TypeScript toolchain is the image's and the host has
no reason to carry one. *Absence* says what going without costs, down to a
grade only worth saying to somebody setting a machine up. Between them, a
laptop with no bun and no clipboard is told nothing at all at launch, which
is correct -- neither is a fault of that machine.
"""

from lup.harness.requirements import Manifest
from lup.harness.toolchain import (
    agent_session_requirement,
    bun_requirement,
    clipboard_requirement,
    container_requirement,
    github_requirement,
    metadata_refused_requirement,
    proxy_reachable_requirement,
    proxy_tunnels_requirement,
    reaped_orphans_requirement,
    same_path_mount_requirement,
    terminal_handoff_requirement,
    typescript_requirement,
    uv_requirement,
)


def manifest() -> Manifest:
    """This repository's requirements, host side and image side.

    Nothing here names a path, a container client, or an image tag, and that
    is load-bearing rather than tidy. This manifest sits inside the `Harness`
    the ownership digest hashes, so a host fact written into it moves that
    digest per machine: measured, two worktrees of one commit hashing
    differently, which made every checkout but the last one to generate read
    its own committed tree as stale. The shapes are declared here and
    `lup.harness.toolchain.for_host` aims them at what this machine answered.

    Ordered by how early a session notices an absence, not by importance, and
    deliberately short. A first draft also declared ripgrep, and exercising it
    refuted the declaration twice over: this project never invokes `rg` --
    only the policy vocabulary judges it, which is a rule about what an
    *agent* may run -- and on the machine that raised the finding `rg` was a
    shell function rather than an executable, so `command -v` would have
    called it present while nothing spawned could reach it. A manifest that
    invents prerequisites refuses machines that were fine, which is this
    module's own failure pointed the other way.

    The image half is exercised inside the container a session opens, which
    `harness requirements --inside` is for. Four of its entries are the
    boundary taken component by component -- the proxy being reachable, a
    request reaching the world through it, the metadata endpoint still being
    refused, and the operator's terminal having arrived. Each was a thing the
    first contained session found broken and no preflight was in a position
    to see, because the image half had been declared and never run.

    The fifth is about the container rather than the boundary, and is here for
    the same reason as the four: it was found by a session collapsing rather
    than by anything asking. A container with no reaper at PID 1 keeps every
    orphan it ever made, so the process bound is reached by a session that
    leaked -- and what announces that is an unrelated suite failing to start
    threads. Declared beside them because the cure and the check belong to the
    same argv, and a flag nothing measures is one that comes off in a refactor
    and is missed hours later by somebody bisecting their own change.
    """
    return Manifest(
        requirements=[
            # Every default taken as offered. Where this repository has an
            # opinion it is in what it *adds*: the JavaScript toolchain, which
            # `default_manifest` deliberately omits because most projects on lup
            # have none.
            uv_requirement(),
            container_requirement(),
            same_path_mount_requirement(),
            github_requirement(),
            clipboard_requirement(),
            # The image half, exercised behind the argv a session opens with.
            # Ordered as a session meets them: the proxy has to be reachable
            # before it can tunnel, the tunnel has to stand before a turn can
            # run, and the terminal is what the operator sees either way.
            proxy_reachable_requirement(),
            proxy_tunnels_requirement(),
            metadata_refused_requirement(),
            terminal_handoff_requirement(),
            reaped_orphans_requirement(),
            bun_requirement(),
            typescript_requirement(),
            agent_session_requirement(),
        ],
    )
