"""Build the semantic policies a declared hook set describes.

Generated native plugins erase a :class:`~lup.harness.models.HookSet` into
primitive rows and enforce them from their own dispatcher. A session this
program composes and runs itself has no dispatcher, so it needs the same
declaration as live policy objects — otherwise enforcement is written twice
and drifts, which is how a resolver worker came to be bounded by a directory
ACL while every generated plugin judged the same acts semantically.

The path rules here compile to exactly the rows :mod:`lup.policy.bundle`
renders, and a test holds them equal. A rule that reached one tree and not
the other would mean a run's permissions depended on who launched it.
"""

from pathlib import Path

from pydantic import BaseModel

from lup.harness.models import HookPathRole, HookSet, HookUrlScope
from lup.policy.assets.host import contained as measured_contained
from lup.policy.assets.host import delivers, measured_boundary
from lup.policy.enforcement import SemanticToolPolicy
from lup.policy.grants import LeaseGrants
from lup.policy.kernel.rows import PathRoleRow
from lup.policy.rules import (
    EditPolicy,
    FetchPolicy,
    PathRule,
    ShellPolicy,
    UrlScope,
    human_owned_path_rule,
)


def declared_scope(scope: HookUrlScope) -> UrlScope:
    """One declared hook scope, as the policies take it."""
    return UrlScope(
        origin=scope.origin,
        path_prefix=scope.path_prefix,
        reason=scope.reason,
        include_subdomains=scope.include_subdomains,
        any_port=scope.any_port,
    )


def protected_root_rule(root: Path) -> PathRule:
    """One declared root, as the protected-path rule it compiles to.

    Scratch is the exception and matches by path part rather than by subtree,
    because a scratch directory is reachable at more than one root and the
    rule is about what the directory is, not where it sits.
    """
    portable = root.as_posix()
    if portable == "tmp":
        return PathRule(
            kind="contains_part",
            value=portable,
            reason="scratch path requires approval",
        )
    return PathRule(
        kind="subtree",
        value=portable,
        reason="protected path requires approval",
        allow_autonomous=True,
    )


def declared_path_rules(hooks: HookSet) -> list[PathRule]:
    """Every protected-path rule this hook set implies.

    The last two are not declared by an application and are not optional for
    one: an `.env` file and a new devtools module are approvals regardless of
    what any adopter listed.
    """
    return [
        *[protected_root_rule(root) for root in hooks.protected_edit_roots],
        *[human_owned_path_rule(path.as_posix()) for path in hooks.human_owned_files],
        PathRule(
            kind="name_prefix",
            value=".env",
            reason="protected path requires approval",
        ),
        PathRule(
            kind="new_devtools",
            value="src",
            reason="new devtools module requires approval",
        ),
    ]


def declared_role_rows(roles: list[HookPathRole]) -> list[PathRoleRow]:
    """What each declared root is for, as the kernel reads it."""
    return [PathRoleRow(root=role.root.as_posix(), role=role.role) for role in roles]


class MeasuredContainment(BaseModel, frozen=True):
    """The container's two terms, as this session's launch measured them.

    They travel together because
    :meth:`~lup.policy.kernel.settlement.SettlementFacts.bounded` needs both: a
    container nothing measured a placement for confines nothing anybody here
    can prove, so neither term answers alone.
    """

    contained: bool = False
    inside_placement: bool = False


def measured_containment(root: Path | None = None) -> MeasuredContainment:
    """What the launch recorded about the boundary this process runs behind.

    Read from the same ``.lup/preflight`` ledger a generated dispatcher reads,
    so a policy composed in this process answers for the session composing it
    rather than for a bare host. A composition that left these out reported the
    question an unconfined host would ask, which is not what a contained
    session is told -- and the guidance sends a reader to `dev policy` *before*
    they spend a turn, so the whole gap fell on the one reader it exists for.
    """
    measured = measured_boundary(root)
    return MeasuredContainment(
        contained=measured_contained(measured),
        inside_placement=delivers(measured, "inside_placement"),
    )


def semantic_policy_for(
    hooks: HookSet,
    *,
    sandbox_active: bool = False,
    escapable: bool = False,
    recovered: bool = False,
    contained: bool = False,
    inside_placement: bool = False,
    interactive: bool = True,
    autonomous: bool = False,
    trusted_script_roots: list[str] | None = None,
    grants: LeaseGrants | None = None,
) -> SemanticToolPolicy:
    """Compose the fetch, shell, and edit policies one hook set declares.

    Every family is supplied. An undeclared family asks on every call, which
    is the right default and a useless composition: a session that must stop
    at a human for each shell command it runs is not bounded, it is stopped.

    The declared refusals travel with them, so a call this project decided
    against is refused by a session composed in process exactly as the
    generated plugin refuses it.
    """
    allowed = [declared_scope(scope) for scope in hooks.allowed_fetch]
    denied = [declared_scope(scope) for scope in hooks.denied_fetch]
    roles = declared_role_rows(list(hooks.path_roles))
    # One instance, given to both families. A shell write carrying its own
    # content reaches the edit gates, and it has to reach the same ones an
    # `Edit` reaches: a second instance would be a second table to keep in
    # step, and the route deciding which rules apply is the divergence this
    # whole policy exists to remove.
    edits = EditPolicy(
        declared_path_rules(hooks),
        autonomous=autonomous,
        path_roles=roles,
        grants=grants,
        acceptance_guard=guard.erased() if (guard := hooks.acceptance_guard) else None,
        edit_rules=hooks.resolved_edit_rules(),
    )
    return SemanticToolPolicy(
        fetch=FetchPolicy(allowed, denied, hooks.unjudged_ambient),
        shell=ShellPolicy(
            hooks.resolved_shell_rules(),
            allowed_urls=allowed,
            denied_urls=denied,
            sandbox_active=sandbox_active,
            sandbox_excluded_commands=hooks.excluded_commands(),
            escapable=escapable,
            recovered=recovered,
            contained=contained,
            inside_placement=inside_placement,
            trusted_script_roots=trusted_script_roots,
            interactive=interactive,
            # A reviewed worker is the one non-interactive session with a
            # route: the run it belongs to carries a mailbox reaching whoever
            # supervises it, so its refusals name that instead of telling it
            # to reshape a command it had every right to run.
            relayed=autonomous,
            path_roles=roles,
            path_rules=declared_path_rules(hooks),
            recoverable_target_limit=hooks.recoverable_target_limit,
            runner_targets=list(hooks.runner_targets),
            authored=edits,
        ),
        edit=edits,
        refused_tools=list(hooks.refused_tools),
    )
