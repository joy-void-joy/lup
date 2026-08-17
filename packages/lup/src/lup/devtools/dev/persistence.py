# lup: ignore[set-shape, empty-collection, dict-str-payload]
# Reachability sets over the shared symbol index are this walk's domain, and the
# alias table it resolves names through is the engine's own shape.
"""Which declared models can reach disk, and which sites could not be named.

Whether a value may be converted from a model into a plain object turns on one
question: does anything write it out or read it back? Pydantic can only
reconstruct a model, so a class that reaches a file has to stay one.

Answering that by searching for pydantic's own method names does not work here,
and the way it fails is the reason this exists. Almost nothing calls
``model_dump_json`` at the site that matters — a write goes through
:func:`lup.channels.models.publish_atomic`, or through a ``Stream`` opened over
a ``TypeAdapter`` — and the class at risk is usually not the one named at the
call at all. Nothing anywhere asks to serialize a ``SkillInvocation``; it
reaches disk because a resolver's state holds a spec that holds three of them.
Only following field types finds that.

So this walk starts at the calls that persist, takes the model each one names,
and closes over every model reachable through their fields — a model held by a
persisted model is itself persisted, and so is every subclass of one, since a
field annotated with a base accepts any of them.

Where an argument cannot be named — a variable, or the result of a helper —
the site is **reported rather than skipped**. A walk that quietly resolved
nothing would answer "safe to convert" for everything, which is the one wrong
answer that costs anything.
"""

import ast
from collections.abc import Collection
from pathlib import Path

import typer
from pydantic import BaseModel

from lup.codescan.common import PythonSource, module_name
from lup.codescan.project import (
    ClassSymbol,
    build_symbol_index,
    descendants_of,
    imported_names,
    resolve_name,
)
from lup.devtools.dev.antipatterns import scanned_files, scanned_roots
from lup.devtools.project import DevProject
from lup.devtools.utils import output_json

MODEL_BASES = {"pydantic.BaseModel", "pydantic_settings.BaseSettings"}
"""Roots whose project-defined descendants count as models we declare."""

SINK_CALLS = ("publish_atomic", "write_model")
"""Helpers that serialize whatever model they are handed."""

ADAPTER_CALLS = ("TypeAdapter",)
"""Constructors that bind a type to a serializer, naming it outright."""

VALIDATE_METHODS = ("model_validate", "model_validate_json")
"""Class methods that rebuild a model, called on the class itself."""

DUMP_METHODS = ("model_dump", "model_dump_json")
"""Methods that write a model out, called on an instance rather than a class.

An instance names no class, so these can only ever be reported unresolved —
which is the point. `source_digest` hashes a whole harness through one of
these, and a walk that watched only for the class-side spellings called that
tree unpersisted.
"""


class UnresolvedSink(BaseModel, frozen=True):
    """One persistence call whose model this walk could not name.

    Not a defect in the call — a variable or a helper's result is ordinary
    code. It is the walk saying where its own answer stops, so a reader knows
    which sites they still have to judge for themselves.
    """

    path: Path
    line: int
    call: str
    argument: str


class PersistenceSites(BaseModel, frozen=True):
    """What one sweep of the persistence calls could and could not name."""

    named: list[str]
    """Models a persistence call names outright."""

    unresolved: list[UnresolvedSink]


class PersistenceReport(BaseModel, frozen=True):
    """Every model that reaches disk, and every site left unresolved."""

    roots: list[str]
    """Models named directly at a persistence call."""

    reached: list[str]
    """Every model a root reaches through fields, subclasses included."""

    unresolved: list[UnresolvedSink]


def annotation_names(node: ast.expr) -> list[str]:
    """Every name an annotation mentions, containers descended into.

    ``list[TextPart]`` mentions both, and it is the member that matters: a
    field holding a list of models persists the models, not the list.
    """
    return [
        child.id if isinstance(child, ast.Name) else child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Name | ast.Attribute)
    ]


def field_edges(sources: list[PythonSource], models: set[str]) -> dict[str, list[str]]:
    """For each model, every model its own field annotations mention."""
    edges: dict[str, list[str]] = {}
    for source in sources:
        try:
            tree = ast.parse(source.text)
        except SyntaxError:
            continue
        aliases = imported_names(tree, source.module)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            qualified = f"{source.module}.{node.name}"
            if qualified not in models:
                continue
            edges[qualified] = sorted(
                {
                    resolved
                    for member in node.body
                    if isinstance(member, ast.AnnAssign)
                    for name in annotation_names(member.annotation)
                    if (resolved := resolve_name(name, source.module, aliases))
                    in models
                }
            )
    return edges


def named_model(node: ast.expr, module: str, aliases: dict[str, str]) -> str | None:
    """The model a persistence argument names, where it names one outright."""
    match node:
        case ast.Call(func=ast.Name(id=name)) | ast.Name(id=name):
            return resolve_name(name, module, aliases)
    return None


def persistence_sites(
    sources: list[PythonSource],
    models: set[str],
    sink_calls: Collection[str] = SINK_CALLS,
    adapter_calls: Collection[str] = ADAPTER_CALLS,
) -> PersistenceSites:
    """Every model named at a persistence call, and every call left unnamed.

    Which helpers persist is this repository's vocabulary rather than a fact
    about pydantic, so both reach a caller as defaults: a project whose writes
    go through its own helper replaces the word and keeps the walk.
    """
    named: set[str] = set()
    unresolved: list[UnresolvedSink] = []
    for source in sources:
        try:
            tree = ast.parse(source.text)
        except SyntaxError:
            continue
        aliases = imported_names(tree, source.module)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            match node.func:
                case ast.Name(id=call) if call in adapter_calls and node.args:
                    subject = named_model(node.args[0], source.module, aliases)
                    written = ast.unparse(node.args[0])
                case ast.Name(id=call) if call in sink_calls and node.args:
                    subject = named_model(node.args[-1], source.module, aliases)
                    written = ast.unparse(node.args[-1])
                case ast.Attribute(value=ast.Name(id=holder), attr=call) if (
                    call in VALIDATE_METHODS
                ):
                    subject = resolve_name(holder, source.module, aliases)
                    written = holder
                case ast.Attribute(value=receiver, attr=call) if call in DUMP_METHODS:
                    written = ast.unparse(receiver)
                    subject = resolve_name(written, source.module, aliases)
                case _:
                    continue
            if subject in models:
                named.add(subject)
            elif call not in VALIDATE_METHODS:
                unresolved.append(
                    UnresolvedSink(
                        path=source.path,
                        line=node.lineno,
                        call=call,
                        argument=written,
                    )
                )
    return PersistenceSites(named=sorted(named), unresolved=unresolved)


def reachable(
    roots: set[str], edges: dict[str, list[str]], symbols: dict[str, ClassSymbol]
) -> set[str]:
    """Every model a root reaches through fields, with subclasses included.

    Subclasses come along because a field annotated with a base accepts any of
    them, so any subclass may be the value actually written.
    """
    reached = set(roots)
    while True:
        through_fields = {
            target for name in reached if name in edges for target in edges[name]
        }
        widened = reached | through_fields | descendants_of(symbols, reached)
        if widened == reached:
            return reached
        reached = widened


def persistence_report(sources: list[PythonSource]) -> PersistenceReport:
    """Name every model that can reach disk, and every site left unresolved."""
    symbols = build_symbol_index(sources)
    models = descendants_of(symbols, MODEL_BASES)
    sites = persistence_sites(sources, models)
    return PersistenceReport(
        roots=sites.named,
        reached=sorted(
            reachable(set(sites.named), field_edges(sources, models), symbols)
        ),
        unresolved=sites.unresolved,
    )


def report_persistence(project: DevProject, as_json: bool) -> None:
    """Print which models reach disk, and where the walk could not tell."""
    sources = [
        PythonSource(
            path=item.path,
            module=module_name(item.path, scanned_roots(project)),
            text=item.text,
        )
        for item in scanned_files(project)
        if item.path.suffix.lower() in {".py", ".pyi"}
    ]
    report = persistence_report(sources)
    if as_json:
        output_json(report.model_dump(mode="json"))
        return
    typer.echo(f"{len(report.reached)} model(s) reach disk")
    for name in report.reached:
        typer.echo(f"  {name}{' (named at a call)' if name in report.roots else ''}")
    if not report.unresolved:
        return
    typer.echo(f"\n{len(report.unresolved)} call(s) this walk could not name")
    for site in report.unresolved:
        typer.echo(f"  {site.path}:{site.line} {site.call}(… {site.argument})")
