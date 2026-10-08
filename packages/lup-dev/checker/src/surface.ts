// What other code can depend on in one file, for the judge's public-API ask: a
// package root's names, every class the module defines, and each function's and
// method's signature (`docs/judging-writes.md`, *The public-API ask*).

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { DeclarationType } from 'pyright/analyzer/declaration';
import { TypeEvaluator } from 'pyright/analyzer/typeEvaluatorTypes';
import {
    ClassNode,
    ExpressionNode,
    FunctionNode,
    ModuleNode,
    ParamCategory,
    ParameterNode,
    ParseNodeType,
    StatementNode,
} from 'pyright/parser/parseNodes';

import { Parameter, ParameterKind, Signature, Surface } from './protocol';

export function surfaceOf(
    module: ModuleNode,
    evaluator: TypeEvaluator,
    reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader,
    isPackageRoot: boolean
): Surface {
    const classes: string[] = [];
    const signatures: Signature[] = [];
    const visit = (statements: StatementNode[], prefix: string) => {
        for (const statement of statements) {
            switch (statement.nodeType) {
                case ParseNodeType.Class:
                    classes.push(prefix + statement.d.name.d.value);
                    visit(statement.d.suite.d.statements, `${prefix}${statement.d.name.d.value}.`);
                    break;
                case ParseNodeType.Function:
                    signatures.push(signatureOf(statement, prefix, evaluator));
                    break;
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
    return { exported: isPackageRoot ? exportedBy(module, reader) : [], classes, signatures };
}

// The names a package's root binds: its `__all__` when it declares one, otherwise
// every name it binds itself.
function exportedBy(module: ModuleNode, reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader): string[] {
    const declared = AnalyzerNodeInfo.getDunderAllInfo(module, reader);
    if (declared) {
        return [...new Set(declared.names)].sort();
    }
    const scope = AnalyzerNodeInfo.getScope(module, reader);
    const bound: string[] = [];
    scope?.symbolTable.forEach((symbol, name) => {
        if (symbol.getDeclarations().some((declaration) => declaration.type !== DeclarationType.Intrinsic)) {
            bound.push(name);
        }
    });
    return bound.sort();
}

function signatureOf(node: FunctionNode, prefix: string, evaluator: TypeEvaluator): Signature {
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
                annotation: printed(parameter.d.annotation ?? parameter.d.annotationComment, evaluator),
                has_default: parameter.d.defaultValue !== undefined,
            };
            return [written];
        }),
        returns: printed(node.d.returnAnnotation, evaluator),
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

// A declared type as pyright prints it, or nothing where none is declared.
function printed(annotation: ExpressionNode | undefined, evaluator: TypeEvaluator): string {
    return annotation ? evaluator.printType(evaluator.getTypeOfAnnotation(annotation)) : '';
}
