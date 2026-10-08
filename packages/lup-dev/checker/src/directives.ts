// The `# lup:` comments in a file, in the shapes `lup_dev/codescan/directives.py`
// reads (`docs/judging-writes.md`, *The `# lup:` directives*).
//
// pyright's tokenizer keeps every comment, attached to the token after it. A comment
// is a directive's when, tokenized, it starts with the name `lup` and a colon. What
// follows is parsed in place by pyright's own expression parser, so a directive is a
// call; anything that isn't one is a note. A call the grammar refuses is reported as
// malformed, never dropped, so a mistyped `ignore` can't sit there doing nothing.

import { convertOffsetToPosition } from 'pyright/common/positionUtils';
import { TextRange } from 'pyright/common/textRange';
import { ArgCategory, CallNode, ExpressionNode, ParseNodeType } from 'pyright/parser/parseNodes';
import { ParseFileResults, ParseOptions, Parser, ParseTextMode } from 'pyright/parser/parser';
import { Tokenizer } from 'pyright/parser/tokenizer';
import { Comment, IdentifierToken, StringTokenFlags, Token, TokenType } from 'pyright/parser/tokenizerTypes';

import { Directive } from './protocol';

const layout = [TokenType.Indent, TokenType.Dedent, TokenType.NewLine, TokenType.EndOfStream];
const names = ['ignore', 'defer'];
const ignoreForm = 'written as `ignore("<rule>", why="<reason>")`';
const deferForm = 'written as `defer(issue=12, why="…")` or `defer(when=condition, why="…")`';

export function readDirectives(parse: ParseFileResults): Directive[] {
    const tokens = parse.tokenizerOutput.tokens;
    const line = (offset: number) => convertOffsetToPosition(offset, parse.tokenizerOutput.lines).line + 1;
    const found: Directive[] = [];
    for (let index = 0; index < tokens.count; index++) {
        for (const comment of tokens.getItemAt(index).comments ?? []) {
            const body = lupBody(parse.text, comment);
            if (body === undefined) {
                continue;
            }
            const at = line(comment.start);
            found.push(read(parse, body, at, () => covered(parse, index, at)));
        }
    }
    return found;
}

// Where a comment's directive starts, after `lup:`, or none for another comment.
function lupBody(text: string, comment: Comment): TextRange | undefined {
    const tokens = new Tokenizer().tokenize(text, comment.start, comment.length).tokens;
    const significant: Token[] = [];
    for (let index = 0; index < tokens.count && significant.length < 3; index++) {
        const token = tokens.getItemAt(index);
        if (!layout.includes(token.type)) {
            significant.push(token);
        }
    }
    const [marker, colon, first] = significant;
    if (
        marker?.type !== TokenType.Identifier ||
        (marker as IdentifierToken).value !== 'lup' ||
        colon?.type !== TokenType.Colon
    ) {
        return undefined;
    }
    const end = TextRange.getEnd(comment);
    const start = first?.start ?? end;
    return { start, length: end - start };
}

// The line an `ignore` keeps: its own when it follows code there, or the next line
// holding code when it stands alone, so stacked ones keep the same line.
function covered(parse: ParseFileResults, attachedTo: number, commentLine: number): number {
    const tokens = parse.tokenizerOutput.tokens;
    const line = (offset: number) => convertOffsetToPosition(offset, parse.tokenizerOutput.lines).line + 1;
    const previous = attachedTo > 0 ? tokens.getItemAt(attachedTo - 1) : undefined;
    if (previous && !layout.includes(previous.type) && line(TextRange.getEnd(previous) - 1) === commentLine) {
        return commentLine;
    }
    for (let index = attachedTo; index < tokens.count; index++) {
        const token = tokens.getItemAt(index);
        if (token.type === TokenType.EndOfStream) {
            break;
        }
        if (!layout.includes(token.type)) {
            return line(token.start);
        }
    }
    return commentLine + 1;
}

function read(parse: ParseFileResults, body: TextRange, line: number, covers: () => number): Directive {
    const text = parse.text.substr(body.start, body.length).trim();
    const tokens = new Tokenizer().tokenize(parse.text, body.start, body.length).tokens;
    const first = tokens.count > 0 ? tokens.getItemAt(0) : undefined;
    const second = tokens.count > 1 ? tokens.getItemAt(1) : undefined;
    const callsSomething = first?.type === TokenType.Identifier && second?.type === TokenType.OpenParenthesis;
    const named = first?.type === TokenType.Identifier ? (first as IdentifierToken).value : undefined;
    if (!callsSomething) {
        if (named && names.includes(named)) {
            return malformed(line, text, `\`${named}\` is a call, ${named === 'ignore' ? ignoreForm : deferForm}`);
        }
        return { kind: 'note', line, text };
    }
    const parsed = new Parser().parseTextExpression(
        parse.text,
        body.start,
        body.length,
        new ParseOptions(),
        ParseTextMode.Expression
    );
    const call = parsed.parseTree;
    if (parsed.diagnostics.length > 0 || call?.nodeType !== ParseNodeType.Call) {
        return malformed(line, text, "it starts like a call but doesn't parse as one");
    }
    switch (named) {
        case 'ignore':
            return readIgnore(call, line, text, covers);
        case 'defer':
            return readDefer(call, line, text);
        default:
            return malformed(line, text, `\`${named}\` is no directive: lup's are \`ignore\` and \`defer\``);
    }
}

function readIgnore(call: CallNode, line: number, text: string, covers: () => number): Directive {
    const positional = call.d.args.filter((arg) => !arg.d.name);
    const keywords = call.d.args.filter((arg) => arg.d.name);
    const rule = positional.length === 1 ? stringValue(positional[0].d.valueExpr) : undefined;
    if (positional.length !== 1 || positional[0].d.argCategory !== ArgCategory.Simple || !rule) {
        return malformed(line, text, `\`ignore\` names one rule, as a string: it's ${ignoreForm}`);
    }
    const unknown = keywords.filter((arg) => arg.d.name!.d.value !== 'why');
    if (unknown.length > 0) {
        return malformed(line, text, `\`ignore\` takes only \`why\`: it's ${ignoreForm}`);
    }
    const why = keywords.length === 1 ? stringValue(keywords[0].d.valueExpr) : undefined;
    if (!why || why.trim() === '') {
        return malformed(line, text, `\`ignore\` needs its reason, \`why="…"\`: it's ${ignoreForm}`);
    }
    return { kind: 'ignore', line, covers: covers(), rule, why };
}

function readDefer(call: CallNode, line: number, text: string): Directive {
    if (call.d.args.some((arg) => !arg.d.name || arg.d.argCategory !== ArgCategory.Simple)) {
        return malformed(line, text, `\`defer\` takes keywords only: it's ${deferForm}`);
    }
    const given = new Map(call.d.args.map((arg) => [arg.d.name!.d.value, arg.d.valueExpr]));
    if (given.size !== call.d.args.length) {
        return malformed(line, text, `\`defer\` names a keyword twice: it's ${deferForm}`);
    }
    const unknown = [...given.keys()].filter((name) => !['why', 'issue', 'when'].includes(name));
    if (unknown.length > 0) {
        return malformed(line, text, `\`defer\` takes \`why\`, \`issue\` and \`when\`, not \`${unknown[0]}\``);
    }
    const why = given.has('why') ? stringValue(given.get('why')!) : undefined;
    if (!why || why.trim() === '') {
        return malformed(line, text, `\`defer\` needs what's left undone, \`why="…"\`: it's ${deferForm}`);
    }
    const issueNode = given.get('issue');
    const issue = issueNode ? integerValue(issueNode) ?? stringValue(issueNode) : undefined;
    if (issueNode && issue === undefined) {
        return malformed(line, text, '`issue` is a number, or a string such as `"owner/repo#7"`');
    }
    const whenNode = given.get('when');
    if (whenNode && whenNode.nodeType !== ParseNodeType.Name) {
        return malformed(line, text, '`when` is the bare name of a declared condition');
    }
    const when = whenNode?.nodeType === ParseNodeType.Name ? whenNode.d.value : undefined;
    if (issue === undefined && when === undefined) {
        return malformed(line, text, 'a defer needs an issue, a condition (`when=`), or both');
    }
    return { kind: 'defer', line, why, issue: issue ?? null, when: when ?? null };
}

function malformed(line: number, text: string, problem: string): Directive {
    return { kind: 'malformed', line, text, problem };
}

// A string literal's value, f-strings and bytes left out.
function stringValue(node: ExpressionNode): string | undefined {
    if (node.nodeType !== ParseNodeType.StringList) {
        return undefined;
    }
    let value = '';
    for (const part of node.d.strings) {
        if (part.nodeType !== ParseNodeType.String || (part.d.token.flags & StringTokenFlags.Bytes) !== 0) {
            return undefined;
        }
        value += part.d.value;
    }
    return value;
}

function integerValue(node: ExpressionNode): number | undefined {
    if (node.nodeType !== ParseNodeType.Number || !node.d.isInteger || node.d.isImaginary) {
        return undefined;
    }
    return Number(node.d.value);
}
