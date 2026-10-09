// Everything the engine reports about one file it has checked.

import * as AnalyzerNodeInfo from 'pyright/analyzer/analyzerNodeInfo';
import { Diagnostic, DiagnosticCategory } from 'pyright/common/diagnostic';
import { Uri } from 'pyright/common/uri/uri';
import { ParseFileResults } from 'pyright/parser/parser';

import { Rule } from './catalog';
import { readDirectives } from './directives';
import { File } from './file';
import { WarmProgram } from './program';
import { FileReport, Finding } from './protocol';
import { positionOf } from './spans';
import { surfaceOf } from './surface';

// The file's full report: pyright's errors and warnings, the selected rules' findings,
// its directives, its public surface and its imports.
export function fullReport(warm: WarmProgram, uri: Uri, reportedPath: string, rules: [string, Rule][]): FileReport {
    const diagnostics = warm.check(uri);
    const parse = warm.parseResults(uri);
    const program = warm.program;
    const reader = program.analyzerNodeInfoReader;
    const module = parse.parserOutput.parseTree;
    const info = AnalyzerNodeInfo.getFileInfo(module, reader);
    const file = new File(program, program.evaluator!, parse, reader, info);
    const byId = new Map(rules);
    for (const [id, rule] of rules) {
        file.checking(id);
        rule.check(file);
    }
    const lup: Finding[] = file.reported.map((reported) => {
        const rule = byId.get(reported.rule)!;
        return {
            path: reportedPath,
            span: reported.span,
            owner: 'lup',
            rule: reported.rule,
            message: `${reported.detail}. ${rule.mistake}`,
            steer: rule.steer,
        };
    });
    const isPackageRoot = info.fileUri.stripAllExtensions().fileName === '__init__';
    return {
        path: reportedPath,
        findings: [...pyrightFindings(parse, diagnostics, reportedPath), ...lup],
        directives: readDirectives(parse),
        surface: surfaceOf(module, program.evaluator!, reader, isPackageRoot),
        imports: [...new Set(file.importedModules().map((imported) => imported.module))].sort(),
    };
}

// A file's report for type errors only, as the importers pass needs: pyright's
// findings, and the directives that may keep them.
export function typeReport(warm: WarmProgram, uri: Uri, reportedPath: string): FileReport {
    const diagnostics = warm.check(uri);
    const parse = warm.parseResults(uri);
    return {
        path: reportedPath,
        findings: pyrightFindings(parse, diagnostics, reportedPath),
        directives: readDirectives(parse),
        surface: { exported: [], classes: [], signatures: [] },
        imports: [],
    };
}

// pyright's errors and warnings, as the pyright CLI reports them; hints (unused,
// unreachable, deprecated) are editor decorations.
function pyrightFindings(parse: ParseFileResults, diagnostics: Diagnostic[], reportedPath: string): Finding[] {
    const lines = parse.tokenizerOutput.lines;
    const offset = (line: number, character: number) => (lines.getItemAt(line)?.start ?? 0) + character;
    return diagnostics
        .filter((diagnostic) => [DiagnosticCategory.Error, DiagnosticCategory.Warning].includes(diagnostic.category))
        .map((diagnostic) => {
            const { start, end } = diagnostic.range;
            return {
                path: reportedPath,
                span: {
                    start: positionOf(parse, offset(start.line, start.character)),
                    end: positionOf(parse, offset(end.line, end.character)),
                },
                owner: 'pyright',
                // A diagnostic without a rule, a syntax error for one, is named by its
                // category, as pyright's own output does.
                rule:
                    diagnostic.getRule() ??
                    (diagnostic.category === DiagnosticCategory.Error ? 'error' : 'warning'),
                message: diagnostic.message,
                steer: '',
            };
        });
}
