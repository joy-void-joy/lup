// What a rule's check asks of the file it checks (`lup_dev/catalog/rules.ts`). Each
// helper walks pyright's tree once per kind of node and asks pyright's type evaluator
// live, so the checks in the table stay short.

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { AnalyzerFileInfo } from 'pyright/analyzer/analyzerFileInfo';
import * as ParseTreeUtils from 'pyright/analyzer/parseTreeUtils';
import { ParseTreeWalker } from 'pyright/analyzer/parseTreeWalker';
import { Program } from 'pyright/analyzer/program';
import { TypeEvaluator } from 'pyright/analyzer/typeEvaluatorTypes';
import { isClassInstance, isInstantiableClass } from 'pyright/analyzer/types';
import { TextRange } from 'pyright/common/textRange';
import {
    ArgCategory,
    CallNode,
    ExceptNode,
    ExpressionNode,
    ImportAsNode,
    ImportFromNode,
    IndexNode,
    MemberAccessNode,
    NameNode,
    ParseNode,
    ParseNodeType,
    SetNode,
} from 'pyright/parser/parseNodes';
import { ParseFileResults } from 'pyright/parser/parser';
import { StringTokenFlags } from 'pyright/parser/tokenizerTypes';

import { CommentPart, commentParts } from './comments';
import { ImportedModule, importedByImportAs, importedByImportFrom } from './imports';
import { Used, usesOf } from './references';
import { denotes, describeType, Meaning, resolve } from './semantics';
import { spanOf } from './spans';
import { Span } from './protocol';

const text = ['builtins.str', 'builtins.bytes'];

export interface Reported {
    rule: string;
    span: Span;
    detail: string;
}

export interface MethodCall {
    node: CallNode;
    method: string;
    receiver: ExpressionNode;
    // The argument given for a parameter, by keyword or by its position.
    argument(name: string, position: number): ExpressionNode | undefined;
}

export interface WrittenType {
    node: ExpressionNode;
    // The expression as written: `tuple[int, str]`.
    text: string;
    // The alias it names, when it names one defined outside the project.
    alias: string | null;
}

export interface Built {
    node: ExpressionNode;
    text: string;
}

export interface Sliced {
    node: IndexNode;
    receiver: ExpressionNode;
    text: string;
}

export interface Caught {
    // The class as written in the clause.
    node: ExpressionNode;
    // The class's fully qualified name, or none where it isn't a class.
    class: string | null;
}

export interface ItemRead {
    node: IndexNode;
    receiver: ExpressionNode;
    key: ExpressionNode;
    text: string;
}

// Every node of the kinds the helpers read, gathered in one walk, string
// annotations included.
class Gathered extends ParseTreeWalker {
    readonly calls: CallNode[] = [];
    readonly subscripts: IndexNode[] = [];
    readonly references: (NameNode | MemberAccessNode)[] = [];
    readonly sets: SetNode[] = [];
    readonly imports: (ImportAsNode | ImportFromNode)[] = [];
    readonly excepts: ExceptNode[] = [];

    override visitCall(node: CallNode) {
        this.calls.push(node);
        return true;
    }
    override visitIndex(node: IndexNode) {
        this.subscripts.push(node);
        return true;
    }
    override visitName(node: NameNode) {
        this.references.push(node);
        return true;
    }
    override visitMemberAccess(node: MemberAccessNode) {
        this.references.push(node);
        // The member's name belongs to this access; only the left side holds
        // references of its own.
        this.walk(node.d.leftExpr);
        return false;
    }
    override visitSet(node: SetNode) {
        this.sets.push(node);
        return true;
    }
    override visitImportAs(node: ImportAsNode) {
        this.imports.push(node);
        return true;
    }
    override visitImportFrom(node: ImportFromNode) {
        this.imports.push(node);
        return true;
    }
    override visitExcept(node: ExceptNode) {
        this.excepts.push(node);
        return true;
    }
}

export class File {
    readonly reported: Reported[] = [];
    private rule = '';
    private gathered: Gathered | undefined;

    constructor(
        readonly program: Program,
        readonly evaluator: TypeEvaluator,
        readonly parse: ParseFileResults,
        readonly reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader,
        readonly info: AnalyzerFileInfo
    ) {}

    // Which rule's check is running, so its reports carry its id.
    checking(rule: string) {
        this.rule = rule;
    }

    report(node: TextRange, detail: string) {
        this.reported.push({ rule: this.rule, span: spanOf(this.parse, node), detail });
    }

    private get nodes(): Gathered {
        if (!this.gathered) {
            this.gathered = new Gathered(this.reader);
            this.gathered.walk(this.parse.parserOutput.parseTree);
        }
        return this.gathered;
    }

    // The source text a node spans, as written.
    text(node: TextRange): string {
        return this.parse.text.substr(node.start, node.length);
    }

    // Every module the file's imports bring in, by its full name.
    importedModules(): ImportedModule[] {
        const isPackageRoot = this.info.fileUri.stripAllExtensions().fileName === '__init__';
        return this.nodes.imports.flatMap((node) =>
            node.nodeType === ParseNodeType.ImportAs
                ? importedByImportAs(node)
                : importedByImportFrom(node, this.info.moduleName, isPackageRoot, this.reader)
        );
    }

    // The imports that bring in one of `modules`, or a submodule of one.
    importsOf(modules: string[]): ImportedModule[] {
        return this.importedModules().filter(({ module }) =>
            modules.some((wanted) => module === wanted || module.startsWith(`${wanted}.`))
        );
    }

    // The uses of the names in `names`, fully qualified, through any import or alias:
    // each reference resolving to one, and each import renaming one.
    uses(names: string[]): Used[] {
        const fromImports = this.nodes.imports.filter(
            (node): node is ImportFromNode => node.nodeType === ParseNodeType.ImportFrom
        );
        return usesOf(this.program, this.evaluator, this.nodes.references, fromImports, names);
    }

    // Every `except` clause.
    exceptClauses(): ExceptNode[] {
        return this.nodes.excepts;
    }

    // The classes an `except` clause names, one by one where it names a tuple.
    caught(clause: ExceptNode): Caught[] {
        const written = clause.d.typeExpr;
        if (!written) {
            return [];
        }
        const named = written.nodeType === ParseNodeType.Tuple ? written.d.items : [written];
        return named.map((node) => {
            const type = this.evaluator.getType(node);
            return { node, class: type && isInstantiableClass(type) ? type.shared.fullName : null };
        });
    }

    // Whether a node sits in the annotation of a dunder method's parameter, where
    // Python's own protocols fix the type: `__eq__(self, other: object)`.
    inDunderParameter(node: ParseNode): boolean {
        const parameter = ParseTreeUtils.getParentNodeOfType(node, ParseNodeType.Parameter);
        if (!parameter || parameter.nodeType !== ParseNodeType.Parameter || !parameter.d.annotation) {
            return false;
        }
        if (!TextRange.containsRange(parameter.d.annotation, node)) {
            return false;
        }
        const method = parameter.parent;
        if (method?.nodeType !== ParseNodeType.Function) {
            return false;
        }
        const name = method.d.name.d.value;
        return name.startsWith('__') && name.endsWith('__');
    }

    // The comments, or the parts of one after another `#`, starting with one of
    // `markers` in any case: `noqa`, `type: ignore`.
    commentsStartingWith(markers: string[]): CommentPart[] {
        const lowered = markers.map((marker) => marker.toLowerCase());
        return commentParts(this.parse).filter((part) =>
            lowered.some((marker) => part.text.toLowerCase().startsWith(marker))
        );
    }

    // The calls of one of `methods` on any receiver: `text.split(",")`.
    methodCalls(methods: string[]): MethodCall[] {
        return this.nodes.calls.flatMap((node) => {
            const callee = node.d.leftExpr;
            if (callee.nodeType !== ParseNodeType.MemberAccess || !methods.includes(callee.d.member.d.value)) {
                return [];
            }
            return [
                {
                    node,
                    method: callee.d.member.d.value,
                    receiver: callee.d.leftExpr,
                    argument(name: string, position: number) {
                        const keyword = node.d.args.find((arg) => arg.d.name?.d.value === name);
                        if (keyword) {
                            return keyword.d.valueExpr;
                        }
                        const positional = node.d.args.filter(
                            (arg) => !arg.d.name && arg.d.argCategory === ArgCategory.Simple
                        );
                        return positional[position]?.d.valueExpr;
                    },
                },
            ];
        });
    }

    // Whether pyright finds the expression to be text: a `str` or `bytes`, a union
    // with one, or a value declared `Any`; never one it can't infer.
    isText(node: ExpressionNode): boolean {
        return describeType(this.evaluator, node, text).some(
            (member) => member.kind === 'any' || member.assignableTo.length > 0
        );
    }

    isNone(node: ExpressionNode): boolean {
        return describeType(this.evaluator, node, []).every((member) => member.kind === 'none');
    }

    // Whether pyright finds the expression to be a mapping; a `TypedDict` read by its
    // keys is already the typed shape, so it isn't one here.
    isMapping(node: ExpressionNode): boolean {
        return describeType(this.evaluator, node, ['typing.Mapping']).some(
            (member) => member.assignableTo.length > 0 && !member.typedDict
        );
    }

    // Whether the expression is a `str` literal, f-strings and bytes left out.
    isStringLiteral(node: ExpressionNode): boolean {
        return (
            node.nodeType === ParseNodeType.StringList &&
            node.d.strings.every(
                (part) =>
                    part.nodeType === ParseNodeType.String && (part.d.token.flags & StringTokenFlags.Bytes) === 0
            )
        );
    }

    // The type expressions naming one of `classes`: `tuple[int, str]`, `Tuple`, a bare
    // `tuple`, or an alias of one defined outside the project. An alias the project
    // defines isn't one here: it's found where it's defined, by what it's written as.
    typesNaming(classes: string[]): WrittenType[] {
        const named = (meaning: Meaning) => meaning.class !== null && classes.includes(meaning.class);
        const external = (meaning: Meaning) => meaning.alias !== null && !meaning.alias.inProject;
        const subscripted = this.nodes.subscripts.flatMap((node) => {
            const meaning = this.denotes(node.d.leftExpr);
            if (!named(meaning) || meaning.hasTypeArgs || (meaning.alias && !external(meaning))) {
                return [];
            }
            return [{ node, text: this.text(node), alias: meaning.alias?.name ?? null }];
        });
        const bare = this.typeExpressionNames().flatMap((node) => {
            const meaning = this.denotes(node);
            if (!named(meaning) || (meaning.alias && !external(meaning))) {
                return [];
            }
            return [{ node, text: this.text(node), alias: meaning.alias?.name ?? null }];
        });
        return [...subscripted, ...bare];
    }

    // The expressions building a value of one of `classes`: its literal, its
    // comprehension, or a call to the class itself.
    builds(classes: string[]): Built[] {
        const displays = this.nodes.sets.filter((node) => {
            const type = this.evaluator.getType(node);
            return type !== undefined && isClassInstance(type) && classes.includes(type.shared.fullName);
        });
        const calls = this.nodes.calls.filter((node) => {
            const callee = this.evaluator.getType(node.d.leftExpr);
            return callee !== undefined && isInstantiableClass(callee) && classes.includes(callee.shared.fullName);
        });
        return [...displays, ...calls].map((node) => ({ node, text: this.text(node) }));
    }

    // Every slice: `text[1:]`.
    slices(): Sliced[] {
        return this.nodes.subscripts.flatMap((node) => {
            const only = node.d.items.length === 1 && !node.d.trailingComma ? node.d.items[0] : undefined;
            if (only?.d.valueExpr.nodeType !== ParseNodeType.Slice) {
                return [];
            }
            return [{ node, receiver: node.d.leftExpr, text: this.text(node) }];
        });
    }

    // Every item read by a single key, as opposed to assigned or deleted:
    // `payload["name"]`.
    itemReads(): ItemRead[] {
        return this.nodes.subscripts.flatMap((node) => {
            const only = node.d.items.length === 1 && !node.d.trailingComma ? node.d.items[0] : undefined;
            if (!only || only.d.name || only.d.argCategory !== ArgCategory.Simple) {
                return [];
            }
            if (only.d.valueExpr.nodeType === ParseNodeType.Slice || isWritten(node)) {
                return [];
            }
            return [{ node, receiver: node.d.leftExpr, key: only.d.valueExpr, text: this.text(node) }];
        });
    }

    printType(node: ExpressionNode): string {
        const type = this.evaluator.getType(node);
        return type ? this.evaluator.printType(type) : 'an unknown type';
    }

    private denotes(node: ExpressionNode): Meaning {
        return denotes(this.program, this.evaluator, node);
    }

    // The names and attributes where Python reads a type, other than the subscripted
    // part of `X[...]`.
    private typeExpressionNames(): (NameNode | MemberAccessNode)[] {
        return this.nodes.references.filter((node) => {
            const parent = node.parent;
            if (parent?.nodeType === ParseNodeType.Index && parent.d.leftExpr === node) {
                return false;
            }
            return this.isTypeExpression(node);
        });
    }

    // Whether a node sits where Python reads a type: an annotation, a type alias's
    // value (`type X = …`, `X: TypeAlias = …`), or a type argument in either.
    private isTypeExpression(node: ParseNode): boolean {
        if (ParseTreeUtils.isWithinTypeAnnotation(node, /* requireQuotedAnnotation */ false, this.reader)) {
            return true;
        }
        for (let current: ParseNode = node; current.parent; current = current.parent) {
            const parent: ParseNode = current.parent;
            if (parent.nodeType === ParseNodeType.TypeAlias && parent.d.expr === current) {
                return true;
            }
            if (
                parent.nodeType === ParseNodeType.Assignment &&
                parent.d.rightExpr === current &&
                parent.d.leftExpr.nodeType === ParseNodeType.TypeAnnotation &&
                resolve(this.program, this.evaluator, parent.d.leftExpr.d.annotation).includes('typing.TypeAlias')
            ) {
                return true;
            }
        }
        return false;
    }
}

// Whether a subscript is assigned or deleted, alone or inside a destructuring
// target, rather than read.
function isWritten(node: IndexNode): boolean {
    let current: ParseNode = node;
    while (
        current.parent &&
        (current.parent.nodeType === ParseNodeType.Tuple ||
            current.parent.nodeType === ParseNodeType.List ||
            current.parent.nodeType === ParseNodeType.Unpack)
    ) {
        current = current.parent;
    }
    const parent = current.parent;
    switch (parent?.nodeType) {
        case ParseNodeType.Assignment:
            return parent.d.leftExpr === current;
        case ParseNodeType.TypeAnnotation:
            return parent.d.valueExpr === current;
        case ParseNodeType.Del:
            return true;
        case ParseNodeType.For:
        case ParseNodeType.ComprehensionFor:
            return parent.d.targetExpr === current;
        case ParseNodeType.WithItem:
            return parent.d.target === current;
        default:
            return false;
    }
}
