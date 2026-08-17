# lup: ignore[dict-str-payload, set-shape]
# The import alias table over the shared symbol index and the resolved-name sets
# it answers with are this AST rule's domain.
"""Project-wide AST enforcement against behaviour written inside a model.

A model is what a value *is*; an ABC is what can be done with one; a concrete
class implements the ABC and holds the model as its data. Three homes, and a
reader looking for any of the three knows which file to open. A `def` in a
model body collapses two of them into one, and the collapse spreads: a type
that answers questions grows the questions, until the declaration of what a
value holds is somewhere in the middle of the code that acts on it.

`feeds/` in the tacocast repository is the worked shape. `FeedCache` is a
model with no methods, `Feed` is an ABC with no data, and `RSSFeed` implements
`Feed` and holds a `FeedCache`. Nothing inherits both.

What the rule fires on is a `def` in the body of a project class descending
from `pydantic.BaseModel` or `pydantic_settings.BaseSettings`. A class this
repository does not declare is never reported, and neither is a `def` nested
inside a member, which belongs to the member rather than to the model.

**Schema declarations are exempt.** `@model_validator` and `@field_validator`
say what a valid instance *is*, in the one place that can refuse to build an
invalid one — `Skill.coherent_arguments` makes a required argument after an
optional one unconstructible, and `ConcernShape.offered_choices_carry_their_gates`
makes a question that asks for a gate it was never granted fail to validate.
Moving those out does not relocate behaviour, it deletes a guarantee and leaves
a caller to remember it. `@computed_field` is not exempt: it is a derived value
wearing a field's clothes, and the derivation is behaviour like any other.

The rule also closes a hole the capability rule could not see. Pydantic's
metaclass is an `ABCMeta`, so `@abstractmethod` binds on a model and a union
rooted at one is abstract without ever naming `ABC` — which is exactly how
seven unions in this library came to hold one abstract member and five concrete
ones while `abc-capability`, whose cap is three abstract and zero concrete,
never saw them. That the architecture's central dispatch is abstract at all
rests on an incidental property of a dependency. Once the seam is an ABC, the
rule that already has the right opinion about seams can reach it.
"""

import ast
from collections.abc import Collection

from lup.codescan.common import PythonSource
from lup.codescan.project import (
    RuleFinding,
    RuleViolation,
    audit_suppressions,
    build_symbol_index,
    declaration_line,
    descendants_of,
    has_decorator,
    imported_names,
)

# lup: defer[when the tree answers this rule, or the branch retires it]: this
# branch is NOT MERGEABLE while this rule ships unanswered. It judges the whole
# tree and the tree has not been converted: 277 findings across 71 files, of
# which 271 sit in files the integration branch has never touched — so they are
# this rule's own backlog rather than drift. Worst first: model_config.py 22,
# dev/worktree.py 18, resolver/models.py 15, gitlocks.py 14, realtime/relay.py
# 11. Answering one is a design change per site (declare the operation on an
# ABC, implement it on a concrete class holding the model), so a suppression
# sweep would ship the rule green and inert, which is the one outcome worth
# refusing. Either finish the conversion, or land the rule retired in this
# repository's own RuleSelection with this note moved to that retirement.
# lup: ignore[constant-declaration] — the rule's own identity, what a typed
# directive and every deny message name it by
RULE_ID = "model-method"

MODEL_BASES = {"pydantic.BaseModel", "pydantic_settings.BaseSettings"}
"""Roots whose project-defined descendants count as models we declare."""

SCHEMA_DECORATORS = ("model_validator", "field_validator")
"""Decorators that make a `def` a declaration of the schema, not an operation."""

# lup: ignore[constant-declaration] — the rule's own sentence, declared with what
# it detects rather than chosen per caller
REMEDY = (
    "declare the operation on an ABC and implement it on a concrete class that "
    "holds this model as its data, so the model stays what the value is"
)


def schema_declaration(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
    aliases: dict[str, str],
    schema_decorators: Collection[str] = SCHEMA_DECORATORS,
) -> bool:
    """Whether this member declares the model's schema rather than acting on it.

    Read off the decorator rather than off the name, and off its resolved
    terminal symbol rather than its spelling, so a validator reached through
    `from pydantic import model_validator` and one reached through
    `pydantic.model_validator` are the same exemption.
    """
    return any(
        has_decorator(node, decorator, module, aliases)
        for decorator in schema_decorators
    )


def model_method_violations(
    sources: list[PythonSource],
    models: set[str],
    schema_decorators: Collection[str] = SCHEMA_DECORATORS,
) -> list[RuleViolation]:
    """Find every member a model we declare defines in its own body."""

    def found():
        for source in sources:
            try:
                tree = ast.parse(source.text)
            except SyntaxError:
                continue
            aliases = imported_names(tree, source.module)
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if f"{source.module}.{node.name}" not in models:
                    continue
                for member in node.body:
                    if not isinstance(
                        member, ast.FunctionDef | ast.AsyncFunctionDef
                    ) or schema_declaration(
                        member, source.module, aliases, schema_decorators
                    ):
                        continue
                    yield RuleViolation(
                        path=source.path,
                        line=declaration_line(member),
                        message=(
                            f"{node.name}.{member.name} is behaviour inside "
                            f"{node.name}, a model we declare — {REMEDY}"
                        ),
                    )

    return list(found())


def audit_model_methods(
    sources: list[PythonSource],
    model_bases: set[str] = MODEL_BASES,
    schema_decorators: Collection[str] = SCHEMA_DECORATORS,
) -> list[RuleFinding]:
    """Build the project index, enforce the rule, and audit its suppressions.

    Both vocabularies reach a caller as defaults rather than as tables baked in
    here: a project whose records root somewhere other than pydantic, or whose
    schema is declared by another library's decorators, replaces the word and
    keeps the rule.
    """
    symbols = build_symbol_index(sources)
    violations = model_method_violations(
        sources, descendants_of(symbols, model_bases), schema_decorators
    )
    return audit_suppressions(sources, violations, RULE_ID)
