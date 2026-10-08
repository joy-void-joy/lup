// What a name in the code refers to, by the fully qualified name it resolves to
// through imports and aliases: `typing.Any` for `Any` after `from typing import Any`.

import { Program } from 'pyright/analyzer/program';
import { TypeEvaluator } from 'pyright/analyzer/typeEvaluatorTypes';
import { isModule } from 'pyright/analyzer/types';
import { ImportFromNode, MemberAccessNode, NameNode, ParseNodeType } from 'pyright/parser/parseNodes';

import { resolve } from './semantics';

export interface Used {
    node: NameNode | MemberAccessNode | ImportFromNode['d']['imports'][number];
    // The fully qualified name it resolves to.
    name: string;
    // The name it's imported as, where an import renames it.
    renamed: string | null;
}

// A name that refers to something, as opposed to one being bound by a definition,
// imported, or naming a keyword argument.
export function isReference(node: NameNode): boolean {
    const parent = node.parent;
    if (!parent) {
        return false;
    }
    switch (parent.nodeType) {
        case ParseNodeType.Class:
        case ParseNodeType.Function:
        case ParseNodeType.Parameter:
        case ParseNodeType.TypeParameter:
        case ParseNodeType.TypeAlias:
        case ParseNodeType.Argument:
            return parent.d.name !== node;
        case ParseNodeType.ImportAs:
        case ParseNodeType.ImportFromAs:
        case ParseNodeType.ModuleName:
        case ParseNodeType.Global:
        case ParseNodeType.Nonlocal:
            return false;
        default:
            return true;
    }
}

// The uses of `names` among `references`, and the imports renaming one of them.
// A module is used where it's reached through its parent (`os.path`); named on
// its own, it was refused at its import.
export function usesOf(
    program: Program,
    evaluator: TypeEvaluator,
    references: (NameNode | MemberAccessNode)[],
    imports: ImportFromNode[],
    names: string[]
): Used[] {
    const wanted = new Set(names);
    const lastNames = new Set(names.map((name) => name.split('.').pop()!));
    const matching = (node: NameNode | MemberAccessNode) => resolve(program, evaluator, node).find((name) => wanted.has(name));
    const used = references.flatMap((node): Used[] => {
        const own = node.nodeType === ParseNodeType.Name ? node : node.d.member;
        if (!lastNames.has(own.d.value)) {
            return [];
        }
        if (node.nodeType === ParseNodeType.Name) {
            const type = evaluator.getType(node);
            if (!isReference(node) || (type && isModule(type))) {
                return [];
            }
        }
        const name = matching(node);
        return name ? [{ node, name, renamed: null }] : [];
    });
    const renamed = imports.flatMap((statement) =>
        statement.d.imports.flatMap((imported): Used[] => {
            const alias = imported.d.alias;
            if (!alias || alias.d.value === imported.d.name.d.value) {
                return [];
            }
            const type = evaluator.getType(alias);
            if (type && isModule(type)) {
                return [];
            }
            const name = resolve(program, evaluator, alias).find((each) => wanted.has(each));
            return name ? [{ node: imported, name, renamed: alias.d.value }] : [];
        })
    );
    return [...used, ...renamed];
}
