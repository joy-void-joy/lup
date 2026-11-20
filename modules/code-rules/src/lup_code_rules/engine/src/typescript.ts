// A TypeScript file's `// lup:` comments, found with TypeScript's own parser, so a
// `//` inside a string, a template or a regular expression is never one. What each
// says after `lup:` is read by the client as a Python file's is, with the same
// grammar (`lup_code_rules/reading.py`).

import * as ts from 'typescript';

import { LupComment, ParsedSource } from './protocol';

export function lupComments(source: ParsedSource): LupComment[] {
    const kind = source.path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
    const file = ts.createSourceFile(source.path, source.content, ts.ScriptTarget.Latest, true, kind);
    const text = source.content;
    const comments = new Map<number, ts.CommentRange>();
    const tokens: ts.Node[] = [];
    const visit = (node: ts.Node) => {
        const ranges = [
            ...(ts.getLeadingCommentRanges(text, node.getFullStart()) ?? []),
            ...(ts.getTrailingCommentRanges(text, node.getEnd()) ?? []),
        ];
        for (const range of ranges) {
            comments.set(range.pos, range);
        }
        const children = node.getChildren(file);
        if (children.length === 0 && node.kind !== ts.SyntaxKind.EndOfFileToken) {
            tokens.push(node);
        }
        children.forEach(visit);
    };
    visit(file);
    const lineOf = (offset: number) => file.getLineAndCharacterOfPosition(offset).line + 1;
    const found: LupComment[] = [];
    for (const range of [...comments.values()].sort((a, b) => a.pos - b.pos)) {
        if (range.kind !== ts.SyntaxKind.SingleLineCommentTrivia) {
            continue;
        }
        const said = text.slice(range.pos + 2, range.end).trim();
        const marker = /^lup\s*:/.exec(said);
        if (!marker) {
            continue;
        }
        const position = file.getLineAndCharacterOfPosition(range.pos);
        const line = position.line + 1;
        const before = tokens.some((token) => token.getEnd() <= range.pos && lineOf(token.getEnd()) === line);
        const after = tokens
            .filter((token) => token.getStart(file) >= range.end)
            .map((token) => lineOf(token.getStart(file)))
            .reduce((first, each) => Math.min(first, each), Number.POSITIVE_INFINITY);
        found.push({
            line,
            column: position.character + 1,
            body: said.slice(marker[0].length).trim(),
            covers: before ? line : Number.isFinite(after) ? after : line + 1,
        });
    }
    return found;
}
