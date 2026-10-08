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
import { doForEachSubtype } from 'pyright/analyzer/typeUtils';
import { TextRange } from 'pyright/common/textRange';
import {
    ArgCategory,
    ArgumentNode,
    CallNode,
    CaseNode,
    ClassNode,
    ComprehensionNode,
    ExceptNode,
    ExpressionNode,
    FunctionNode,
    IfNode,
    ImportAsNode,
    ImportFromNode,
    IndexNode,
    LambdaNode,
    MemberAccessNode,
    NameNode,
    ParseNode,
    ParseNodeType,
    PatternClassNode,
    SetNode,
    SliceNode,
    StatementListNode,
    StatementNode,
    StringNode,
    SuiteNode,
    TypeParameterListNode,
} from 'pyright/parser/parseNodes';
import { ParseFileResults } from 'pyright/parser/parser';
import { OperatorType, StringTokenFlags } from 'pyright/parser/tokenizerTypes';

import { CommentPart, commentParts } from './comments';
import { codeMarks, comments, Mark, Mention, mentions, Prose, Word, wordsOf, written } from './prose';
import { ImportedModule, importedByImportAs, importedByImportFrom } from './imports';
import { Used, usesOf } from './references';
import { denotes, describeType, Meaning, resolve } from './semantics';
import {
    ancestorsOf,
    Binding,
    FilledLoop,
    filledLoops,
    isOurABC,
    isPrivate,
    ourABCsImplemented,
    privateBindings,
} from './structure';
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

export interface Call {
    node: CallNode;
    // The fully qualified name of what's called: `pydantic.fields.Field`.
    callee: string;
    // The argument given for a parameter, by keyword or, given one, by its position.
    argument(name: string, position?: number): ExpressionNode | undefined;
}

export interface Base {
    // The base as written: `BaseModel`, `Generic[T]`.
    node: ExpressionNode;
    // The fully qualified names it resolves to; for `Generic[T]`, those of `Generic`.
    names: string[];
}

export interface Keyword {
    node: ArgumentNode;
    name: string;
    value: ExpressionNode;
}

export interface Assigned {
    // The name assigned.
    node: NameNode;
    name: string;
    // What it's assigned, where it is: `x: int` declares without assigning.
    value: ExpressionNode | undefined;
}

export interface GuardedCase {
    node: CaseNode;
    // The pattern and its guard, as written: `case _ if seconds < 60` spans `_ if seconds < 60`.
    range: TextRange;
    // Whether the pattern matches anything, as a wildcard or a bare name does.
    irrefutable: boolean;
}

export interface Narrowing {
    // The `isinstance` call.
    node: CallNode;
    // What it narrows, as written.
    subject: string;
}

export interface DeclaredClass {
    node: ClassNode;
    // Its fully qualified name: `lup.types.Model`.
    fullName: string;
    // The bases its header lists, in order.
    bases: Base[];
    // The keywords its header gives: `frozen=True`, `metaclass=…`.
    keywords: Keyword[];
    // The names its body assigns directly, outside its methods.
    assigned: Assigned[];
    // The full names of its ancestors, nearest first.
    ancestors: string[];
    // Whether it lists `abc.ABC` among its own bases.
    listsABC: boolean;
    // The bases that are ABCs of the project, by their full names.
    ourABCBases: string[];
    // The methods its body defines, abstract and concrete.
    abstract: FunctionNode[];
    concrete: FunctionNode[];
}

export interface NamedClass {
    // Where the class is named: an `isinstance` argument, a class pattern.
    node: ExpressionNode;
    // The project's ABCs it implements, by their full names.
    implements: string[];
}

export interface Constant {
    node: NameNode;
    name: string;
    // What the constant holds, as its type says, where the rule reads that kind.
    kind: 'number' | 'duration' | 'path' | null;
}

export interface ExceptionText {
    // Where an exception's message decides something: `"x" in str(exc)`.
    node: ExpressionNode;
    text: string;
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
    // The slice's bounds and step, as written; none where left out.
    start: ExpressionNode | undefined;
    end: ExpressionNode | undefined;
    step: ExpressionNode | undefined;
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
    readonly classes: ClassNode[] = [];
    readonly ifs: IfNode[] = [];
    readonly cases: CaseNode[] = [];
    readonly docstrings: StringNode[] = [];
    // The nodes that own a scope or a block: functions, lambdas, comprehensions,
    // type parameter lists, and every suite.
    readonly scopes: ParseNode[] = [];
    readonly suites: SuiteNode[] = [];
    readonly patterns: PatternClassNode[] = [];

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
    override visitClass(node: ClassNode) {
        this.classes.push(node);
        this.scopes.push(node);
        return true;
    }
    override visitFunction(node: FunctionNode) {
        this.scopes.push(node);
        return true;
    }
    override visitLambda(node: LambdaNode) {
        this.scopes.push(node);
        return true;
    }
    override visitComprehension(node: ComprehensionNode) {
        this.scopes.push(node);
        return true;
    }
    override visitTypeParameterList(node: TypeParameterListNode) {
        this.scopes.push(node);
        return true;
    }
    override visitSuite(node: SuiteNode) {
        this.suites.push(node);
        return true;
    }
    override visitPatternClass(node: PatternClassNode) {
        this.patterns.push(node);
        return true;
    }
    override visitIf(node: IfNode) {
        this.ifs.push(node);
        return true;
    }
    override visitCase(node: CaseNode) {
        this.cases.push(node);
        return true;
    }
    // A string standing alone as a statement is a docstring: a module's, a class's,
    // a function's, or an attribute's after its assignment.
    override visitStatementList(node: StatementListNode) {
        const [only, ...more] = node.d.statements;
        if (only?.nodeType === ParseNodeType.StringList && more.length === 0) {
            for (const part of only.d.strings) {
                if (part.nodeType === ParseNodeType.String) {
                    this.docstrings.push(part);
                }
            }
        }
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

    // Whether the file is a package's root, its `__init__.py`.
    get isPackageRoot(): boolean {
        return this.info.fileUri.stripAllExtensions().fileName === '__init__';
    }

    // The fully qualified names an expression resolves to, through imports and
    // aliases: `typing.Any` for `Any`.
    namesOf(node: ExpressionNode): string[] {
        return resolve(this.program, this.evaluator, node);
    }

    // The file's module, by its dotted name.
    get moduleName(): string {
        return this.info.moduleName;
    }

    // The source text a node spans, as written.
    text(node: TextRange): string {
        return this.parse.text.substr(node.start, node.length);
    }

    // Every module the file's imports bring in, by its full name.
    importedModules(): ImportedModule[] {
        return this.nodes.imports.flatMap((node) =>
            node.nodeType === ParseNodeType.ImportAs
                ? importedByImportAs(node)
                : importedByImportFrom(node, this.info.moduleName, this.isPackageRoot, this.reader)
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

    // The calls of one of `names`, by what's called, through any import or alias:
    // `Field(default_factory=list)` for `pydantic.fields.Field`.
    callsTo(names: string[]): Call[] {
        return this.nodes.calls.flatMap((node) => {
            const callee = this.namesOf(node.d.leftExpr).find((name) => names.includes(name));
            if (!callee) {
                return [];
            }
            return [{ node, callee, argument: (name: string, position?: number) => argumentOf(node, name, position) }];
        });
    }

    // Every class the file defines, at any depth.
    classes(): DeclaredClass[] {
        return this.nodes.classes.map((node) => {
            const type = this.evaluator.getTypeOfClass(node)?.classType;
            const fullName = type?.shared.fullName ?? node.d.name.d.value;
            const bases = node.d.arguments
                .filter((arg) => !arg.d.name && arg.d.argCategory === ArgCategory.Simple)
                .map((arg) => {
                    const written = arg.d.valueExpr;
                    const named = written.nodeType === ParseNodeType.Index ? written.d.leftExpr : written;
                    return { node: written, names: this.namesOf(named) };
                });
            const keywords = node.d.arguments.flatMap((arg) =>
                arg.d.name ? [{ node: arg, name: arg.d.name.d.value, value: arg.d.valueExpr }] : []
            );
            const ourABCBases = (type?.shared.baseClasses ?? []).flatMap((base) =>
                isInstantiableClass(base) && isOurABC(this.program, base) ? [base.shared.fullName] : []
            );
            const methods = node.d.suite.d.statements.filter(
                (statement): statement is FunctionNode => statement.nodeType === ParseNodeType.Function
            );
            return {
                node,
                fullName,
                bases,
                keywords,
                assigned: assignedIn(node.d.suite.d.statements),
                ancestors: type ? ancestorsOf(type) : [],
                listsABC: bases.some((base) => base.names.includes('abc.ABC')),
                ourABCBases,
                abstract: methods.filter((method) => this.isAbstract(method)),
                concrete: methods.filter((method) => !this.isAbstract(method)),
            };
        });
    }

    // Whether a method is decorated `@abstractmethod`.
    private isAbstract(method: FunctionNode): boolean {
        return method.d.decorators.some((decorator) => this.namesOf(decorator.d.expr).includes('abc.abstractmethod'));
    }

    // The project's ABCs the class an expression names implements; none where it
    // names no class, or one that implements none.
    implementing(node: ExpressionNode): NamedClass {
        const type = this.evaluator.getType(node);
        const implemented = type && isInstantiableClass(type) ? ourABCsImplemented(this.program, type) : [];
        return { node, implements: implemented };
    }

    // The classes `isinstance` calls test against, one by one where they name a tuple.
    isinstanceClasses(): NamedClass[] {
        return this.callsTo(['builtins.isinstance']).flatMap((call) => {
            const tested = call.argument('class_or_tuple', 1);
            if (!tested) {
                return [];
            }
            const named = tested.nodeType === ParseNodeType.Tuple ? tested.d.items : [tested];
            return named.map((each) => this.implementing(each));
        });
    }

    // The classes `case` patterns match against: `case Claude():`.
    classPatterns(): NamedClass[] {
        return this.nodes.patterns.map((pattern) => this.implementing(pattern.d.className));
    }

    // The private names the file binds, at any scope, each where it's first bound.
    privateNames(): Binding[] {
        const scopes = [this.parse.parserOutput.parseTree, ...this.nodes.scopes];
        return privateBindings(scopes, this.reader, this.parse.parserOutput.parseTree);
    }

    // Whether the module's own name is private: `_helpers.py`.
    get isPrivateModule(): boolean {
        return isPrivate(this.info.fileUri.stripAllExtensions().fileName);
    }

    // The loops filling a collection their block created empty before them.
    collectionLoops(): FilledLoop[] {
        const blocks = [this.parse.parserOutput.parseTree.d.statements, ...this.nodes.suites.map((suite) => suite.d.statements)];
        return blocks.flatMap((statements) => filledLoops(statements, (node) => this.isEmptyCollection(node)));
    }

    // The module's constants: what it assigns at its top level, each with the kind
    // its type says it holds.
    moduleConstants(): Constant[] {
        return this.moduleAssignments().flatMap((assigned) => {
            if (!assigned.value) {
                return [];
            }
            return [{ node: assigned.node, name: assigned.name, kind: this.constantKind(assigned.node) }];
        });
    }

    private constantKind(node: NameNode): Constant['kind'] {
        const lineages = this.lineages(node);
        if (lineages.length === 0) {
            return null;
        }
        const all = (test: (lineage: string[]) => boolean) => lineages.every(test);
        if (all((lineage) => lineage.includes('datetime.timedelta'))) {
            return 'duration';
        }
        const numeric = (lineage: string[]) =>
            !lineage.includes('builtins.bool') && (lineage.includes('builtins.int') || lineage.includes('builtins.float'));
        if (all(numeric)) {
            return 'number';
        }
        if (all((lineage) => lineage.includes('pathlib.PurePath'))) {
            return 'path';
        }
        return null;
    }

    // For each member of an expression's type that's an instance of a class, the
    // class and its ancestors, by their full names.
    private lineages(node: ExpressionNode): string[][] {
        const type = this.evaluator.getType(node);
        if (!type) {
            return [];
        }
        const found: string[][] = [];
        let other = false;
        doForEachSubtype(type, (subtype) => {
            if (!isClassInstance(subtype)) {
                other = true;
                return;
            }
            found.push([subtype.shared.fullName, ...ancestorsOf(subtype)]);
        });
        return other ? [] : found;
    }

    // Whether pyright finds the expression to be an exception.
    isException(node: ExpressionNode): boolean {
        const lineages = this.lineages(node);
        return lineages.length > 0 && lineages.every((lineage) => lineage.includes('builtins.BaseException'));
    }

    // The places an exception's message decides something: its text (`str(exc)`,
    // `repr(exc)`, `exc.args`), as it is or through a method that keeps it text,
    // compared, tested for a part, or matched on.
    exceptionTexts(): ExceptionText[] {
        const texts = this.callsTo(['builtins.str', 'builtins.repr']).flatMap((call) => {
            const only = call.node.d.args.length === 1 ? call.node.d.args[0].d.valueExpr : undefined;
            return only && this.isException(only) ? [call.node as ExpressionNode] : [];
        });
        const args = this.nodes.references.filter(
            (node): node is MemberAccessNode =>
                node.nodeType === ParseNodeType.MemberAccess && node.d.member.d.value === 'args' && this.isException(node.d.leftExpr)
        );
        return [...texts, ...args].flatMap((text) => {
            const used = textUse(text);
            return deciding(used) ? [{ node: used, text: this.text(used) }] : [];
        });
    }

    // The root error of the file's package, by the name the conventions give it:
    // `LupDevError` for `lup_dev`.
    get packageRootError(): string {
        const [top] = this.moduleName.split('.');
        return `${top
            .split('_')
            .map((part) => part.charAt(0).toUpperCase() + part.substring(1))
            .join('')}Error`;
    }

    // The file's top-level package: `lup_dev` for `lup_dev.policy.judge`.
    get packageName(): string {
        const [top] = this.moduleName.split('.');
        return top;
    }

    // The names the module assigns at its top level.
    moduleAssignments(): Assigned[] {
        return assignedIn(this.parse.parserOutput.parseTree.d.statements);
    }

    // What a `lambda` returns; none for anything else.
    lambdaBody(node: ExpressionNode): ExpressionNode | undefined {
        return node.nodeType === ParseNodeType.Lambda ? node.d.expr : undefined;
    }

    // Whether an expression builds an empty list, dict or set: `[]`, `{}`, `list()`.
    isEmptyCollection(node: ExpressionNode): boolean {
        switch (node.nodeType) {
            case ParseNodeType.List:
                return node.d.items.length === 0;
            case ParseNodeType.Dictionary:
                return node.d.items.length === 0;
            case ParseNodeType.Call:
                return (
                    node.d.args.length === 0 &&
                    this.namesOf(node.d.leftExpr).some((name) => emptyBuilders.includes(name))
                );
            default:
                return false;
        }
    }

    // The `elif` keyword of every `elif`.
    elifs(): TextRange[] {
        return this.nodes.ifs.filter(isElif).map((node) => node.d.firstToken);
    }

    // The `if` keyword of every `if` that's all an `else` holds: an `elif` written
    // out.
    elseIfs(): TextRange[] {
        return this.nodes.ifs.filter(isElseIf).map((node) => node.d.firstToken);
    }

    // Every `case` with a guard: `case _ if seconds < 60:`.
    guardedCases(): GuardedCase[] {
        return this.nodes.cases.flatMap((node) => {
            const guard = node.d.guardExpr;
            if (!guard) {
                return [];
            }
            const range = TextRange.combine([node.d.pattern, guard])!;
            return [{ node, range, irrefutable: node.d.isIrrefutable }];
        });
    }

    // The `isinstance` tests narrowing one subject across the arms of one decision:
    // the `if` statements of one block and the `elif`s chained to them, each test a
    // bare `isinstance(subject, …)` or its negation. Each list holds two or more, in
    // the order written.
    isinstanceChains(): Narrowing[][] {
        const blocks = new Map<ParseNode, IfNode[]>();
        for (const node of this.nodes.ifs) {
            if (isElif(node) || isElseIf(node) || !node.parent) {
                continue;
            }
            blocks.set(node.parent, [...(blocks.get(node.parent) ?? []), node]);
        }
        return [...blocks.values()].flatMap((statements) => {
            const tests = statements.flatMap((statement) => armsOf(statement)).flatMap((test) => {
                const call = this.isinstanceCall(test);
                return call ? [call] : [];
            });
            const chains: { subject: ExpressionNode; arms: Narrowing[] }[] = [];
            for (const test of tests) {
                const subject = test.d.args[0].d.valueExpr;
                const arm = { node: test, subject: this.text(subject) };
                const chain = chains.find((each) => ParseTreeUtils.isMatchingExpression(each.subject, subject));
                if (chain) {
                    chain.arms.push(arm);
                    continue;
                }
                chains.push({ subject, arms: [arm] });
            }
            return chains.filter((chain) => chain.arms.length > 1).map((chain) => chain.arms);
        });
    }

    // The `isinstance(subject, …)` call a test is, alone or negated.
    private isinstanceCall(test: ExpressionNode): CallNode | undefined {
        const tested =
            test.nodeType === ParseNodeType.UnaryOperation && test.d.operator === OperatorType.Not ? test.d.expr : test;
        if (tested.nodeType !== ParseNodeType.Call || tested.d.args.length !== 2 || tested.d.args.some((arg) => arg.d.name)) {
            return undefined;
        }
        return this.namesOf(tested.d.leftExpr).includes('builtins.isinstance') ? tested : undefined;
    }

    // Every docstring, as written between its quotes.
    docstrings(): Prose[] {
        return this.nodes.docstrings.map(written);
    }

    // The file's prose: its comments and its docstrings.
    prose(): Prose[] {
        return [...comments(this.parse), ...this.docstrings()];
    }

    // The words of a piece of prose, leaving out code in backticks, text in double
    // quotes, and doctest examples.
    words(prose: Prose): Word[] {
        return wordsOf(prose);
    }

    // The reStructuredText marks in a piece of prose: double backticks, Sphinx roles.
    codeMarks(prose: Prose): Mark[] {
        return codeMarks(prose);
    }

    // Each name, string and comment holding one of `names`, in any case.
    mentionsOf(names: string[]): Mention[] {
        return mentions(this.parse, names);
    }

    // The integer an expression is written as, a negative one included; none for
    // anything else.
    integerLiteral(node: ExpressionNode | undefined): number | undefined {
        if (node?.nodeType === ParseNodeType.Number && node.d.isInteger && !node.d.isImaginary) {
            return Number(node.d.value);
        }
        if (node?.nodeType === ParseNodeType.UnaryOperation && node.d.operator === OperatorType.Subtract) {
            const magnitude = this.integerLiteral(node.d.expr);
            return magnitude === undefined ? undefined : -magnitude;
        }
        return undefined;
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
                    argument: (name: string, position: number) => argumentOf(node, name, position),
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
            const slice = only?.d.valueExpr;
            if (slice?.nodeType !== ParseNodeType.Slice) {
                return [];
            }
            return [{ node, receiver: node.d.leftExpr, text: this.text(node), ...boundsOf(slice) }];
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

const emptyBuilders = ['builtins.list', 'builtins.dict', 'builtins.set'];

// Methods that keep text text, and methods that test it for a part.
const keepsText = ['lower', 'upper', 'casefold', 'strip', 'lstrip', 'rstrip'];
const testsText = ['startswith', 'endswith', 'find', 'rfind', 'index', 'rindex', 'count', '__contains__'];

// What an exception's text is used as: itself, an item of it, or what a method
// keeping it text makes of it, `str(exc).lower()`.
function textUse(node: ExpressionNode): ExpressionNode {
    let current: ExpressionNode = node;
    for (;;) {
        const parent = current.parent;
        if (parent?.nodeType === ParseNodeType.Index && parent.d.leftExpr === current) {
            current = parent;
            continue;
        }
        const call = parent?.parent;
        const kept =
            parent?.nodeType === ParseNodeType.MemberAccess &&
            keepsText.includes(parent.d.member.d.value) &&
            call?.nodeType === ParseNodeType.Call &&
            call.d.leftExpr === parent;
        if (kept && call?.nodeType === ParseNodeType.Call) {
            current = call;
            continue;
        }
        return current;
    }
}

// Whether a piece of text decides something: compared, tested for a part, or
// matched on.
function deciding(node: ExpressionNode): boolean {
    const parent = node.parent;
    if (parent?.nodeType === ParseNodeType.BinaryOperation) {
        const comparing = [OperatorType.In, OperatorType.NotIn, OperatorType.Equals, OperatorType.NotEquals];
        return comparing.includes(parent.d.operator);
    }
    if (parent?.nodeType === ParseNodeType.MemberAccess && testsText.includes(parent.d.member.d.value)) {
        return parent.parent?.nodeType === ParseNodeType.Call;
    }
    return parent?.nodeType === ParseNodeType.Match && parent.d.expr === node;
}

function boundsOf(slice: SliceNode) {
    return { start: slice.d.startValue, end: slice.d.endValue, step: slice.d.stepValue };
}

// Whether an `if` is an `elif`: the `else` of the `if` before it.
function isElif(node: IfNode): boolean {
    return node.parent?.nodeType === ParseNodeType.If && node.parent.d.elseSuite === node;
}

// Whether an `if` is all an `else` holds, an `elif` written out.
function isElseIf(node: IfNode): boolean {
    const suite = node.parent;
    const owner = suite?.parent;
    return (
        suite?.nodeType === ParseNodeType.Suite &&
        owner?.nodeType === ParseNodeType.If &&
        owner.d.elseSuite === suite &&
        suite.d.statements.length === 1
    );
}

// The tests of an `if` and of the `elif`s chained to it, an `else` holding only an
// `if` counting as one.
function armsOf(node: IfNode): ExpressionNode[] {
    const next = node.d.elseSuite;
    if (next?.nodeType === ParseNodeType.If) {
        return [node.d.testExpr, ...armsOf(next)];
    }
    const [only, ...more] = next?.d.statements ?? [];
    if (only?.nodeType === ParseNodeType.If && more.length === 0) {
        return [node.d.testExpr, ...armsOf(only)];
    }
    return [node.d.testExpr];
}

// The argument a call gives for a parameter, by keyword or, given one, by its position.
function argumentOf(node: CallNode, name: string, position?: number): ExpressionNode | undefined {
    const keyword = node.d.args.find((arg) => arg.d.name?.d.value === name);
    if (keyword || position === undefined) {
        return keyword?.d.valueExpr;
    }
    const positional = node.d.args.filter((arg) => !arg.d.name && arg.d.argCategory === ArgCategory.Simple);
    return positional[position]?.d.valueExpr;
}

// The names a block's statements assign directly, not inside nested blocks:
// `x = 1`, `x: int = 1`, `x += 1`, and `x: int`, which declares without assigning.
function assignedIn(statements: StatementNode[]): Assigned[] {
    return statements.flatMap((statement) => {
        if (statement.nodeType !== ParseNodeType.StatementList) {
            return [];
        }
        return statement.d.statements.flatMap((simple): Assigned[] => {
            switch (simple.nodeType) {
                case ParseNodeType.Assignment: {
                    const target = simple.d.leftExpr;
                    const named = target.nodeType === ParseNodeType.TypeAnnotation ? target.d.valueExpr : target;
                    return named.nodeType === ParseNodeType.Name
                        ? [{ node: named, name: named.d.value, value: simple.d.rightExpr }]
                        : [];
                }
                case ParseNodeType.AugmentedAssignment: {
                    const target = simple.d.leftExpr;
                    return target.nodeType === ParseNodeType.Name
                        ? [{ node: target, name: target.d.value, value: simple.d.rightExpr }]
                        : [];
                }
                case ParseNodeType.TypeAnnotation: {
                    const target = simple.d.valueExpr;
                    return target.nodeType === ParseNodeType.Name
                        ? [{ node: target, name: target.d.value, value: undefined }]
                        : [];
                }
                default:
                    return [];
            }
        });
    });
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
