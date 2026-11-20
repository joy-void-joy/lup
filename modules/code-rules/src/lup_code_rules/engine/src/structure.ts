// The structural questions the rules ask: where a class stands among the project's
// classes (its ancestors, the ABCs it implements), which private names a file
// binds, and which loops fill a collection created empty before them.

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { DeclarationType } from 'pyright/analyzer/declaration';
import { ParseTreeWalker } from 'pyright/analyzer/parseTreeWalker';
import { Program } from 'pyright/analyzer/program';
import { isUserCode } from 'pyright/analyzer/sourceFileInfoUtils';
import { ClassType, isClass, isInstantiableClass } from 'pyright/analyzer/types';
import { TextRange } from 'pyright/common/textRange';
import {
    ExpressionNode,
    ForNode,
    NameNode,
    ParseNode,
    ParseNodeType,
    StatementNode,
    WhileNode,
} from 'pyright/parser/parseNodes';

// The full names of a class's ancestors, nearest first, itself left out.
export function ancestorsOf(type: ClassType): string[] {
    return type.shared.mro.slice(1).flatMap((ancestor) => (isClass(ancestor) ? [ancestor.shared.fullName] : []));
}

function declaredInProject(program: Program, type: ClassType): boolean {
    const uri = type.shared.declaration?.uri;
    const info = uri ? program.getSourceFileInfo(uri) : undefined;
    return info !== undefined && isUserCode(info);
}

// Whether a class is one of the project's ABCs: declared in the project, with
// `abc.ABC` among its own bases.
export function isOurABC(program: Program, type: ClassType): boolean {
    const listsABC = type.shared.baseClasses.some(
        (base) => isInstantiableClass(base) && base.shared.fullName === 'abc.ABC'
    );
    return listsABC && declaredInProject(program, type);
}

// The project's ABCs a class implements, by their full names: its ancestors that
// are ABCs of the project, itself left out.
export function ourABCsImplemented(program: Program, type: ClassType): string[] {
    return type.shared.mro
        .slice(1)
        .flatMap((ancestor) =>
            isInstantiableClass(ancestor) && isOurABC(program, ancestor) ? [ancestor.shared.fullName] : []
        );
}

export interface Binding {
    // The name where it's first bound.
    node: NameNode;
    name: string;
}

// Whether a name is private: a leading underscore, a dunder and `_` alone aside.
export function isPrivate(name: string): boolean {
    const dunder = name.startsWith('__') && name.endsWith('__') && name.length > 4;
    return name.startsWith('_') && name !== '_' && !dunder;
}

// The name a declaration binds, where it binds one in this file's text.
function boundName(declaration: { type: DeclarationType; node: ParseNode }): NameNode | undefined {
    const node = declaration.node;
    switch (node.nodeType) {
        case ParseNodeType.Name:
            return node;
        case ParseNodeType.Class:
        case ParseNodeType.Function:
        case ParseNodeType.TypeParameter:
            return node.d.name;
        case ParseNodeType.ImportFromAs:
            return node.d.alias ?? node.d.name;
        case ParseNodeType.ImportAs:
            return node.d.alias;
        default:
            return undefined;
    }
}

// The module a node belongs to.
function moduleOf(node: ParseNode): ParseNode {
    let current = node;
    while (current.parent) {
        current = current.parent;
    }
    return current;
}

// The private names the scopes of a file bind, each once, where it's first bound:
// classes, functions, variables (an instance's attributes included), imports and
// type parameters. A parameter keeps its underscore: that marks it unused. A
// declaration counts where its node is in `module`: an import's declaration names
// the imported module's file, not this one.
export function privateBindings(
    scopes: ParseNode[],
    reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader,
    module: ParseNode
): Binding[] {
    const bound = [
        DeclarationType.Variable,
        DeclarationType.Function,
        DeclarationType.Class,
        DeclarationType.Alias,
        DeclarationType.TypeParam,
    ];
    const seen = new Set<NameNode>();
    return scopes.flatMap((node) => {
        const scope = AnalyzerNodeInfo.getScope(node, reader);
        return [...(scope?.symbolTable.entries() ?? [])].flatMap(([name, symbol]): Binding[] => {
            if (!isPrivate(name)) {
                return [];
            }
            const [first] = symbol
                .getDeclarations()
                .filter((declaration) => bound.includes(declaration.type) && moduleOf(declaration.node) === module)
                .flatMap((declaration) => {
                    const named = boundName(declaration);
                    return named ? [named] : [];
                })
                .sort((one, other) => one.start - other.start);
            if (!first || seen.has(first)) {
                return [];
            }
            seen.add(first);
            return [{ node: first, name }];
        });
    });
}

export interface FilledLoop {
    // The loop, from its keyword to the end of its header.
    header: TextRange;
    // The collection it fills, as named.
    name: string;
    // Where the collection was created empty.
    created: NameNode;
}

// The methods filling a collection with one entry: a list's, a set's.
const fillers = ['append', 'add'];

// The collection a loop fills, by its name among `names`, where filling it is all the
// loop does: a `for`, with no `else`, whose body is one `rows.append(…)`, `seen.add(…)`
// or `table[key] = …`, alone or under one `if` with no `else`, the collection read
// nowhere else in the loop. A loop doing more, a fold carrying state from one
// iteration to the next among them, fills none here: a comprehension holds only that.
function soleFill(loop: ForNode | WhileNode, names: string[]): string | undefined {
    if (loop.nodeType !== ParseNodeType.For || loop.d.elseSuite) {
        return undefined;
    }
    const [statement, ...more] = loop.d.forSuite.d.statements;
    const guarded = statement?.nodeType === ParseNodeType.If && more.length === 0 && !statement.d.elseSuite;
    const body = guarded ? statement.d.ifSuite.d.statements : loop.d.forSuite.d.statements;
    const [only, ...rest] = body;
    if (only?.nodeType !== ParseNodeType.StatementList || rest.length > 0 || only.d.statements.length !== 1) {
        return undefined;
    }
    const filled = filledBy(only.d.statements[0]);
    if (!filled || !names.includes(filled.d.value)) {
        return undefined;
    }
    const reads = new Reads(filled.d.value);
    reads.walk(loop);
    return reads.count === 1 ? filled.d.value : undefined;
}

// The collection a simple statement fills with one entry, as named: the list or set
// it calls `append` or `add` on, or the dict it assigns an item of.
function filledBy(statement: ParseNode): NameNode | undefined {
    if (statement.nodeType === ParseNodeType.Call) {
        const callee = statement.d.leftExpr;
        const filling = callee.nodeType === ParseNodeType.MemberAccess && fillers.includes(callee.d.member.d.value);
        return filling && callee.d.leftExpr.nodeType === ParseNodeType.Name ? callee.d.leftExpr : undefined;
    }
    if (statement.nodeType !== ParseNodeType.Assignment || statement.d.leftExpr.nodeType !== ParseNodeType.Index) {
        return undefined;
    }
    const item = statement.d.leftExpr;
    const [key, ...more] = item.d.items;
    const single = key !== undefined && more.length === 0 && key.d.valueExpr.nodeType !== ParseNodeType.Slice;
    return single && item.d.leftExpr.nodeType === ParseNodeType.Name ? item.d.leftExpr : undefined;
}

// How many times a name is read within a node.
class Reads extends ParseTreeWalker {
    count = 0;

    constructor(private readonly name: string) {
        super();
    }

    override visitName(node: NameNode) {
        if (node.d.value === this.name) {
            this.count += 1;
        }
        return true;
    }
}

// The outermost loops inside a statement, nested functions and classes left out.
class Loops extends ParseTreeWalker {
    readonly loops: (ForNode | WhileNode)[] = [];

    override visitFor(node: ForNode) {
        this.loops.push(node);
        return false;
    }
    override visitWhile(node: WhileNode) {
        this.loops.push(node);
        return false;
    }
    override visitFunction() {
        return false;
    }
    override visitClass() {
        return false;
    }
    override visitLambda() {
        return false;
    }
}

function headerOf(loop: ForNode | WhileNode): TextRange {
    const last = loop.nodeType === ParseNodeType.For ? loop.d.iterableExpr : loop.d.testExpr;
    return { start: loop.start, length: TextRange.getEnd(last) - loop.start };
}

// The loops of a block that fill a collection the block created empty before them,
// and do nothing else (`soleFill`): `rows = []`, then `for …: rows.append(…)`, the
// loop at any depth below.
export function filledLoops(statements: StatementNode[], isEmpty: (node: ExpressionNode) => boolean): FilledLoop[] {
    const created = new Map<string, NameNode>();
    const found: FilledLoop[] = [];
    for (const statement of statements) {
        const walker = new Loops();
        walker.walk(statement);
        for (const loop of walker.loops) {
            const name = soleFill(loop, [...created.keys()]);
            if (name !== undefined) {
                found.push({ header: headerOf(loop), name, created: created.get(name)! });
            }
        }
        if (statement.nodeType !== ParseNodeType.StatementList) {
            continue;
        }
        for (const simple of statement.d.statements) {
            if (simple.nodeType !== ParseNodeType.Assignment) {
                continue;
            }
            const written = simple.d.leftExpr;
            const target = written.nodeType === ParseNodeType.TypeAnnotation ? written.d.valueExpr : written;
            if (target.nodeType !== ParseNodeType.Name) {
                continue;
            }
            if (isEmpty(simple.d.rightExpr)) {
                created.set(target.d.value, target);
                continue;
            }
            created.delete(target.d.value);
        }
    }
    return found;
}
