// What other code can depend on in one file, for the judge's public-API ask: a
// package root's names, every class the module defines, and each function's and
// method's signature, each placed on the line its name is on, which the review
// marks (`docs/judging-writes.md`, *The public-API ask*).
//
// The same walk serves a checked file and one read from its parse alone
// (`parsed.ts`): what tells them apart is how an annotation is said, the type it
// declares as pyright prints it or the annotation as written, and which binding
// the package root's names come from.

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { DeclarationType } from 'pyright/analyzer/declaration';
import { printExpression } from 'pyright/analyzer/parseTreeUtils';
import { TypeEvaluator } from 'pyright/analyzer/typeEvaluatorTypes';
import {
    ClassNode,
    ExpressionNode,
    FunctionNode,
    ModuleNode,
    ParamCategory,
    ParameterNode,
    ParseNode,
    ParseNodeType,
    StatementNode,
} from 'pyright/parser/parseNodes';
import { ParseFileResults } from 'pyright/parser/parser';

import { Parameter, ParameterKind, Placed, Signature, Surface } from './protocol';
import { positionOf } from './spans';

// How an annotation is said in a signature.
export type Printer = (annotation: ExpressionNode) => string;

// The type an annotation declares, as pyright prints it: a checked file's.
export function byType(evaluator: TypeEvaluator): Printer {
    return (annotation) => evaluator.printType(evaluator.getTypeOfAnnotation(annotation));
}

// The annotation as written, through pyright's own printer of expressions, so
// spacing and line breaks inside it don't count: a file read from its parse alone.
export const asWritten: Printer = (annotation) => printExpression(annotation);

// The file's surface. `reader` holds the file's binding, which a package root's
// names are read from: the program's, or one made of the parse alone.
export function surfaceOf(
    parse: ParseFileResults,
    print: Printer,
    reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader,
    isPackageRoot: boolean
): Surface {
    const module = parse.parserOutput.parseTree;
    const classes: string[] = [];
    const signatures: Signature[] = [];
    const places: Placed[] = [];
    const place = (kind: Placed['kind'], name: string, node: ParseNode) => {
        places.push({ kind, name, line: positionOf(parse, node.start).line });
    };
    const visit = (statements: StatementNode[], prefix: string) => {
        for (const statement of statements) {
            switch (statement.nodeType) {
                case ParseNodeType.Class:
                    classes.push(prefix + statement.d.name.d.value);
                    place('class', prefix + statement.d.name.d.value, statement.d.name);
                    visit(statement.d.suite.d.statements, `${prefix}${statement.d.name.d.value}.`);
                    break;
                case ParseNodeType.Function: {
                    const signature = signatureOf(statement, prefix, print);
                    signatures.push(signature);
                    place('signature', signature.name, statement.d.name);
                    break;
                }
                case ParseNodeType.If:
                    visit(statement.d.ifSuite.d.statements, prefix);
                    if (statement.d.elseSuite) {
                        visit(
                            statement.d.elseSuite.nodeType === ParseNodeType.Suite
                                ? statement.d.elseSuite.d.statements
                                : [statement.d.elseSuite],
                            prefix
                        );
                    }
                    break;
                case ParseNodeType.Try:
                    visit(statement.d.trySuite.d.statements, prefix);
                    break;
                default:
                    break;
            }
        }
    };
    visit(module.d.statements, '');
    const exported = isPackageRoot ? exportedBy(module, reader) : [];
    for (const each of exported) {
        if (each.node) {
            place('export', each.name, each.node);
        }
    }
    return { exported: exported.map((each) => each.name), classes, signatures, places };
}

// A name a package's root exports, and the node naming it there: none for a name
// `__all__` takes from another module's, which no string of its own names.
interface Exported {
    name: string;
    node: ParseNode | undefined;
}

// The names a package's root binds: its `__all__` when it declares one, each at its
// first entry there, otherwise every name it binds itself, each at its first binding.
function exportedBy(module: ModuleNode, reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader): Exported[] {
    const declared = AnalyzerNodeInfo.getDunderAllInfo(module, reader);
    if (declared) {
        return [...new Set(declared.names)].sort().map((name) => ({
            name,
            node: declared.stringNodes.find((node) => node.d.value === name),
        }));
    }
    const scope = AnalyzerNodeInfo.getScope(module, reader);
    const bound: Exported[] = [];
    scope?.symbolTable.forEach((symbol, name) => {
        const binding = symbol
            .getDeclarations()
            .find((declaration) => declaration.type !== DeclarationType.Intrinsic);
        if (binding) {
            bound.push({ name, node: binding.node });
        }
    });
    return bound.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

function signatureOf(node: FunctionNode, prefix: string, print: Printer): Signature {
    const kinds = parameterKinds(node.d.params);
    return {
        name: prefix + node.d.name.d.value,
        parameters: node.d.params.flatMap((parameter, index) => {
            const kind = kinds[index];
            if (!parameter.d.name || !kind) {
                return [];
            }
            const written: Parameter = {
                name: parameter.d.name.d.value,
                kind,
                annotation: printed(parameter.d.annotation ?? parameter.d.annotationComment, print),
                has_default: parameter.d.defaultValue !== undefined,
            };
            return [written];
        }),
        returns: printed(node.d.returnAnnotation, print),
    };
}

// Each parameter's kind as callers see it, or none for the `/` and `*` separators.
function parameterKinds(parameters: ParameterNode[]): (ParameterKind | undefined)[] {
    const slash = parameters.findIndex(
        (parameter) => parameter.d.category === ParamCategory.Simple && !parameter.d.name
    );
    let keywordOnly = false;
    return parameters.map((parameter, index) => {
        switch (parameter.d.category) {
            case ParamCategory.ArgsList:
                keywordOnly = true;
                return parameter.d.name ? 'variadic' : undefined;
            case ParamCategory.KwargsDict:
                return 'variadic-keyword';
            default:
                if (!parameter.d.name) {
                    return undefined;
                }
                if (keywordOnly) {
                    return 'keyword-only';
                }
                return index < slash ? 'positional-only' : 'positional-or-keyword';
        }
    });
}

// An annotation as `print` says it, or nothing where none is declared.
function printed(annotation: ExpressionNode | undefined, print: Printer): string {
    return annotation ? print(annotation) : '';
}
