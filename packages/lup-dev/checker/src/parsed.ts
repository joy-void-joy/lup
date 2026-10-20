// A file read from its parse alone, with no project loaded and no types: what an
// approval's first reading needs, which comes before the type check that would
// hold it up (`Trust.read`, `lup_dev/launch/trust.py`; `docs/trust.md`). It's
// the file's `# lup:` directives, read as a check reads them, and
// its public surface, each annotation as written and a package root's names from
// a binding of the file alone. No rule runs, and no import is resolved: an import
// binds its names all the same, but a package root's `from x import *`, or an
// `__all__` extended with another module's, adds nothing to its names here.

import * as path from 'path';

import { AnalyzerFileInfo } from 'pyright/analyzer/analyzerFileInfo';
import {
    AnalyzerNodeInfoContextImpl,
    AnalyzerNodeInfoReader,
    createAnalyzerNodeInfoAccessor,
} from 'pyright/analyzer/analyzerNodeInfo';
import { Binder } from 'pyright/analyzer/binder';
import { ImportType } from 'pyright/analyzer/importResult';
import { Scope, ScopeType } from 'pyright/analyzer/scope';
import { IPythonMode } from 'pyright/analyzer/sourceFile';
import { ConfigOptions } from 'pyright/common/configOptions';
import { DiagnosticSink, TextRangeDiagnosticSink } from 'pyright/common/diagnosticSink';
import { Uri } from 'pyright/common/uri/uri';
import { ParseFileResults, ParseOptions, Parser } from 'pyright/parser/parser';

import { readDirectives } from './directives';
import { FileReport, ParsedSource } from './protocol';
import { asWritten, surfaceOf } from './surface';

// A file is named by the path it's given, never looked up on disk.
const named = { isCaseSensitive: () => true };

export function parsedReport(source: ParsedSource): FileReport {
    const suffix = path.extname(source.path);
    const options = new ParseOptions();
    options.isStubFile = suffix === '.pyi';
    const parse = new Parser().parseSourceFile(source.content, options, new DiagnosticSink());
    const isPackageRoot = path.basename(source.path, suffix) === '__init__';
    return {
        path: source.path,
        findings: [],
        directives: readDirectives(parse),
        surface: surfaceOf(parse, asWritten, bound(parse, source.path, options.isStubFile), isPackageRoot),
        imports: [],
    };
}

// The file's binding, as pyright's binder makes it, of its parse alone: each
// import unresolved, and no builtins.
function bound(parse: ParseFileResults, file: string, isStubFile: boolean): AnalyzerNodeInfoReader {
    const tree = parse.parserOutput.parseTree;
    const context = new AnalyzerNodeInfoContextImpl();
    const session = context.beginWrite(tree);
    const info = createAnalyzerNodeInfoAccessor(session, session);
    const configuration = new ConfigOptions(Uri.file(path.sep, named));
    const fileInfo: AnalyzerFileInfo = {
        importLookup: () => undefined,
        futureImports: parse.parserOutput.futureImports,
        // A scope of its own, empty: without one, the binder takes the file for the
        // builtins module itself.
        builtinsScope: new Scope(ScopeType.Builtin),
        diagnosticSink: new TextRangeDiagnosticSink(parse.tokenizerOutput.lines),
        executionEnvironment: configuration.getDefaultExecEnvironment(),
        diagnosticRuleSet: configuration.diagnosticRuleSet,
        lines: parse.tokenizerOutput.lines,
        typingSymbolAliases: parse.parserOutput.typingSymbolAliases,
        definedConstants: new Map(),
        fileId: file,
        // Its name tells the binder a package root, as on disk.
        fileUri: Uri.file(path.resolve(path.sep, file), named),
        moduleName: '',
        isStubFile,
        isTypingStubFile: false,
        isTypingExtensionsStubFile: false,
        isTypeshedStubFile: false,
        isBuiltInStubFile: false,
        isInPyTypedPackage: false,
        ipythonMode: IPythonMode.None,
        accessedSymbolSet: new Set(),
    };
    info.setFileInfo(tree, fileInfo);
    // The binder reads each import's resolution, which a program sets as it parses.
    for (const imported of parse.parserOutput.importedModules) {
        info.setImportInfo(imported.nameNode, {
            importName: '',
            isRelative: imported.leadingDots > 0,
            isImportFound: false,
            isPartlyResolved: false,
            isNamespacePackage: false,
            isInitFilePresent: false,
            isStubPackage: false,
            importType: ImportType.Local,
            resolvedUris: [],
            isStubFile: false,
            isNativeLib: false,
        });
    }
    new Binder(fileInfo, /* moduleSymbolOnly */ false, /* cellChainIndex */ undefined, info).bindModule(tree);
    context.publish(session);
    return context;
}
