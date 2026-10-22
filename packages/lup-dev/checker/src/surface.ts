// What other code can depend on in one file, for the judge's public-API ask: a
// package root's names, and the public classes, functions and methods the module
// defines, each placed on the line its name is on, which the review marks
// (`docs/judging-writes.md`, *The public-API ask*).
//
// The same walk serves a checked file and one read from its parse alone
// (`parsed.ts`): what tells them apart is which binding the package root's names
// come from.

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { DeclarationType } from 'pyright/analyzer/declaration';
import { ModuleNode, ParseNode, ParseNodeType, StatementNode } from 'pyright/parser/parseNodes';
import { ParseFileResults } from 'pyright/parser/parser';

import { Placed, Surface } from './protocol';
import { positionOf } from './spans';

// The file's surface. `reader` holds the file's binding, which a package root's
// names are read from: the program's, or one made of the parse alone.
//
// A class or function is public where its name has no leading underscore, a
// dunder's (`__init__`) counting as public, and so is a method of a public class
// whose name is public. A private class takes its members with it. A function
// nested in another never counts, nor does a class defined inside a function. A
// name defined twice, an overload or one `def` in each branch of an `if`, is
// listed once, where it's first.
export function surfaceOf(
    parse: ParseFileResults,
    reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader,
    isPackageRoot: boolean
): Surface {
    const module = parse.parserOutput.parseTree;
    const classes: string[] = [];
    const functions: string[] = [];
    const places: Placed[] = [];
    const place = (kind: Placed['kind'], name: string, node: ParseNode) => {
        places.push({ kind, name, line: positionOf(parse, node.start).line });
    };
    const listed = (into: string[], kind: Placed['kind'], name: string, node: ParseNode) => {
        if (into.includes(name)) {
            return;
        }
        into.push(name);
        place(kind, name, node);
    };
    const visit = (statements: StatementNode[], prefix: string) => {
        for (const statement of statements) {
            switch (statement.nodeType) {
                case ParseNodeType.Class: {
                    const name = statement.d.name.d.value;
                    if (!isPublic(name)) {
                        break;
                    }
                    listed(classes, 'class', prefix + name, statement.d.name);
                    visit(statement.d.suite.d.statements, `${prefix}${name}.`);
                    break;
                }
                case ParseNodeType.Function: {
                    const name = statement.d.name.d.value;
                    if (isPublic(name)) {
                        listed(functions, 'function', prefix + name, statement.d.name);
                    }
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
    return { exported: exported.map((each) => each.name), classes, functions, places };
}

// Whether a name is one other code may depend on: no leading underscore, but for
// a dunder, which is a protocol's name rather than a private one.
function isPublic(name: string): boolean {
    return !name.startsWith('_') || (name.startsWith('__') && name.endsWith('__') && name.length > 4);
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
