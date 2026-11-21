// The modules an import statement brings in, by their full names, the way
// import-linter counts them: `import a.b` imports `a.b`; `from a import b` imports
// `a.b` when `b` is a submodule and `a` otherwise; a relative import is resolved
// against the importing module.

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { ImportAsNode, ImportFromNode, ModuleNameNode, ParseNode } from 'pyright/parser/parseNodes';

export interface ImportedModule {
    // The full name of the module imported.
    module: string;
    // Where it's named: the module's name, or the name a `from` import takes.
    node: ParseNode;
}

export function importedByImportAs(node: ImportAsNode): ImportedModule[] {
    return [{ module: absoluteName(node.d.module, ''), node: node.d.module }];
}

export function importedByImportFrom(
    node: ImportFromNode,
    importingModule: string,
    isPackageRoot: boolean,
    reader: AnalyzerNodeInfo.AnalyzerNodeInfoReader
): ImportedModule[] {
    const base = absoluteName(node.d.module, packageOf(importingModule, isPackageRoot));
    if (node.d.isWildcardImport || node.d.imports.length === 0) {
        return [{ module: base, node: node.d.module }];
    }
    const submodules = AnalyzerNodeInfo.getImportInfo(node.d.module, reader)?.filteredImplicitImports;
    return node.d.imports.map((name) =>
        submodules?.has(name.d.name.d.value)
            ? { module: `${base}.${name.d.name.d.value}`, node: name }
            : { module: base, node: node.d.module }
    );
}

// The package a relative import starts from: the module itself for a package's
// `__init__`, its parent otherwise.
function packageOf(moduleName: string, isPackageRoot: boolean): string {
    if (isPackageRoot) {
        return moduleName;
    }
    return moduleName.split('.').slice(0, -1).join('.');
}

function absoluteName(node: ModuleNameNode, importingPackage: string): string {
    const parts = node.d.nameParts.map((part) => part.d.value);
    if (node.d.leadingDots === 0) {
        return parts.join('.');
    }
    const packageParts = importingPackage === '' ? [] : importingPackage.split('.');
    const kept = packageParts.slice(0, packageParts.length - (node.d.leadingDots - 1));
    return [...kept, ...parts].join('.');
}
