# lup: ignore[set-shape, empty-collection, string-split]
# Graph sets over the shared symbol index are this AST rule's domain, and
# splitting a qualified name to its terminal symbol is how it names one.
"""Project-wide AST enforcement for Lup capability ABC composition.

Audits every resolved project import for the ``abc-capability`` shape
described in ``docs/architecture.md``: one narrow capability per ABC, no
concrete behavior, no multiple inheritance. The ``lup-devtools dev check
--antipatterns`` auditor runs :func:`audit_capabilities` across the tree; the
anti-pattern registry re-exports the rule id so deny messages name it.

The scope is capability seams, not every abstract base — a distinction
``docs/patterns.md`` already draws in prose and this rule reads off the base
list. A union whose subtypes answer for themselves is Closed By Construction
and is governed by ``own-model-dispatch``; it declares ``BaseModel`` beside
``ABC`` and is not judged here. Nothing else separates the two shapes
syntactically, which is why the declaration has to say which one it is.

The tree reading, name resolution, and suppression grammar this rule works
from live in :mod:`lup.codescan.project`, which it shares with
:mod:`lup.codescan.dispatch`.
"""

from lup.codescan.common import PythonSource
from lup.codescan.project import (
    ClassSymbol,
    RuleFinding,
    RuleViolation,
    audit_suppressions,
    build_symbol_index,
    descendants_of,
)

# lup: ignore[constant-declaration] — the rule's own identity, what a typed
# directive and every deny message name it by
RULE_ID = "abc-capability"

MODEL_BASES = {"pydantic.BaseModel", "pydantic_settings.BaseSettings"}
"""Roots whose project-defined descendants are variant unions, not capabilities."""


def capability_names(
    symbols: dict[str, ClassSymbol], model_bases: set[str] = MODEL_BASES
) -> set[str]:
    """Find direct and invalid inherited capability ABC declarations.

    A subclass that leaves one of its base capability's abstract operations
    unimplemented is still an ABC even when it does not repeat the
    ``@abstractmethod`` decorator.  The project index therefore computes the
    effective abstract member set instead of looking only at methods declared
    in the subclass body.

    A class that also descends from ``pydantic.BaseModel`` is a variant union
    rather than a capability, and is excluded. The two shapes want opposite
    things from a base: a capability holds no concrete behaviour, because
    shared behaviour belongs on the surface that composes it; a union's base
    carries declining answers on purpose, because that is what lets a walk
    reach a kind written after it. Reading the base list is what tells them
    apart — ``BaseModel`` and ``ABC`` together say *closed set of kinds*,
    ``ABC`` alone says *seam an implementation fills*.
    """
    effective_cache: dict[str, set[str]] = {}

    def effective_abstracts(name: str, visiting: set[str] | None = None) -> set[str]:
        cached = effective_cache.get(name)  # lup: ignore[dict-get]
        if cached is not None:
            return cached
        if name not in symbols:
            return set()
        active = set() if visiting is None else set(visiting)
        if name in active:
            return set()
        active.add(name)
        symbol = symbols[name]
        inherited = {
            member
            for base in symbol.bases
            if base in symbols
            for member in effective_abstracts(base, active)
        }
        implemented = set(symbol.concrete_callables)
        declared = set(symbol.abstract_methods) | set(symbol.abstract_properties)
        result = (inherited - implemented) | declared
        effective_cache[name] = result
        return result

    unions = descendants_of(symbols, model_bases)
    capabilities = {
        name
        for name, symbol in symbols.items()
        if ("abc.ABC" in symbol.bases or "ABC" in symbol.bases) and name not in unions
    }
    changed = True
    while changed:
        inherited = {
            name
            for name, symbol in symbols.items()
            if any(base in capabilities for base in symbol.bases)
            and effective_abstracts(name)
            and name not in unions
        }
        expanded = capabilities | inherited
        changed = expanded != capabilities
        capabilities = expanded
    return capabilities


def architecture_violations(
    symbols: dict[str, ClassSymbol], capabilities: set[str]
) -> list[RuleViolation]:
    """Evaluate every capability declaration and concrete implementation."""
    violations: list[RuleViolation] = []
    typing_bases = {"abc.ABC", "ABC", "typing.Generic", "Generic"}

    def is_implementation(name: str, seen: set[str] | None = None) -> bool:
        if name in capabilities or name not in symbols:
            return False
        visited = set() if seen is None else seen
        if name in visited:
            return False
        visited.add(name)
        return any(
            base in capabilities or is_implementation(base, visited)
            for base in symbols[name].bases
        )

    for name, symbol in symbols.items():
        if name in capabilities:
            method_count = len(symbol.abstract_methods)
            if method_count == 0 or method_count > 3:
                violations.append(
                    RuleViolation(
                        path=symbol.path,
                        line=symbol.line,
                        message=(
                            f"capability {symbol.name} has {method_count} abstract behavior "
                            "methods; expected one to three"
                        ),
                    )
                )
            for member in symbol.abstract_properties:
                violations.append(
                    RuleViolation(
                        path=symbol.path,
                        line=symbol.member_lines[member],
                        message=f"capability {symbol.name} declares abstract property {member}",
                    )
                )
            for member in symbol.concrete_callables:
                violations.append(
                    RuleViolation(
                        path=symbol.path,
                        line=symbol.member_lines[member],
                        message=f"capability {symbol.name} has concrete callable {member}",
                    )
                )
            capability_bases = [base for base in symbol.bases if base in capabilities]
            if capability_bases:
                violations.append(
                    RuleViolation(
                        path=symbol.path,
                        line=symbol.line,
                        message=(
                            f"capability {symbol.name} inherits capability "
                            f"{capability_bases[0].rsplit('.', 1)[-1]}"
                        ),
                    )
                )
            invalid_bases = [
                base
                for base in symbol.bases
                if base not in typing_bases and base not in capabilities
            ]
            if invalid_bases:
                violations.append(
                    RuleViolation(
                        path=symbol.path,
                        line=symbol.line,
                        message=f"capability {symbol.name} inherits reusable behavior",
                    )
                )
            continue

        direct_capabilities = [base for base in symbol.bases if base in capabilities]
        inherited_implementations = [
            base for base in symbol.bases if is_implementation(base)
        ]
        if len(direct_capabilities) > 1:
            violations.append(
                RuleViolation(
                    path=symbol.path,
                    line=symbol.line,
                    message=f"implementation {symbol.name} implements multiple capabilities",
                )
            )
        if direct_capabilities and len(symbol.bases) > 1:
            violations.append(
                RuleViolation(
                    path=symbol.path,
                    line=symbol.line,
                    message=f"implementation {symbol.name} inherits reusable behavior",
                )
            )
        if inherited_implementations:
            violations.append(
                RuleViolation(
                    path=symbol.path,
                    line=symbol.line,
                    message=f"implementation {symbol.name} inherits an implementation",
                )
            )
    return violations


def audit_capabilities(sources: list[PythonSource]) -> list[RuleFinding]:
    """Build the project index, enforce the rule, and audit its suppressions."""
    symbols = build_symbol_index(sources)
    violations = architecture_violations(symbols, capability_names(symbols))
    return audit_suppressions(sources, violations, RULE_ID)
