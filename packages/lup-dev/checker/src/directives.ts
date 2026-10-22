// The `# lup:` comments in a file, in the shapes `lup_dev/codescan/directives.py`
// reads (`docs/judging-writes.md`, *The `# lup:` directives*).
//
// pyright's tokenizer keeps every comment, attached to the token after it. A comment
// is a directive's when, tokenized, it starts with the name `lup` and a colon. What
// follows is parsed in place by pyright's own expression parser, so a directive is a
// call: `ignore`, `defer` or `note`. Anything else is a note as written: free text,
// or a call of another name. An `ignore` or a `defer` the grammar refuses is
// reported as malformed, never dropped, so a mistyped one can't sit there doing
// nothing; so is a call of another name passing a deferral's `issue` or `when`,
// whose tracking would vanish unseen as a note. A note can't be wrong: a `note`
// that isn't one string is a note as written.

import { convertOffsetToPosition } from 'pyright/common/positionUtils';
import { TextRange } from 'pyright/common/textRange';
import { ArgCategory, CallNode, ExpressionNode, ParseNodeType } from 'pyright/parser/parseNodes';
import { ParseFileResults, ParseOptions, Parser, ParseTextMode } from 'pyright/parser/parser';
import { Tokenizer } from 'pyright/parser/tokenizer';
import { Comment, IdentifierToken, StringTokenFlags, Token, TokenType } from 'pyright/parser/tokenizerTypes';

import { Directive } from './protocol';

const layout = [TokenType.Indent, TokenType.Dedent, TokenType.NewLine, TokenType.EndOfStream];
const ignoreForm = 'written as `ignore("<rule>", why="<reason>")`, with `issue=12` where it waits on that issue';
const deferForm = 'written as `defer(issue=12, why="…")` or `defer(when=condition, why="…")`';
const issueForm = '`issue` is a number, or a string such as `"owner/repo#7"`';
const tracking = ['issue', 'when'];

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
    if (first?.type !== TokenType.Identifier || second?.type !== TokenType.OpenParenthesis) {
        return { kind: 'note', line, text };
    }
    const named = (first as IdentifierToken).value;
    const parsed = new Parser().parseTextExpression(
        parse.text,
        body.start,
        body.length,
        new ParseOptions(),
        ParseTextMode.Expression
    );
    const tree = parsed.parseTree;
    const call =
        parsed.diagnostics.length === 0 &&
        tree?.nodeType === ParseNodeType.Call &&
        tree.d.leftExpr.nodeType === ParseNodeType.Name
            ? tree
            : undefined;
    const unparsed = `\`${named}\` doesn't parse as a call: it's ${named === 'ignore' ? ignoreForm : deferForm}`;
    switch (named) {
        case 'ignore':
            return call ? readIgnore(call, line, text, covers) : malformed(line, text, unparsed);
        case 'defer':
            return call ? readDefer(call, line, text) : malformed(line, text, unparsed);
        case 'note':
            return { kind: 'note', line, text: (call && noteText(call)) || text };
        default:
            if (call?.d.args.some((arg) => arg.d.name && tracking.includes(arg.d.name.d.value))) {
                const problem =
                    `\`${named}\` is no directive, yet passes \`issue\` or \`when\`, which track a \`defer\` ` +
                    "or an `ignore`: lup's calls are `ignore`, `defer` and `note`";
                return malformed(line, text, problem);
            }
            return { kind: 'note', line, text };
    }
}

// What a `note("…")` says: its one string, or none where it's written otherwise.
function noteText(call: CallNode): string | undefined {
    const [only] = call.d.args;
    if (call.d.args.length !== 1 || only.d.name || only.d.argCategory !== ArgCategory.Simple) {
        return undefined;
    }
    const value = stringValue(only.d.valueExpr)?.trim();
    return value || undefined;
}

function readIgnore(call: CallNode, line: number, text: string, covers: () => number): Directive {
    const positional = call.d.args.filter((arg) => !arg.d.name);
    const rule = positional.length === 1 ? stringValue(positional[0].d.valueExpr) : undefined;
    if (positional.length !== 1 || positional[0].d.argCategory !== ArgCategory.Simple || !rule) {
        return malformed(line, text, `\`ignore\` names one rule, as a string: it's ${ignoreForm}`);
    }
    const keywords = call.d.args.filter((arg) => arg.d.name);
    const given = new Map(keywords.map((arg) => [arg.d.name!.d.value, arg.d.valueExpr]));
    if (given.size !== keywords.length) {
        return malformed(line, text, `\`ignore\` names a keyword twice: it's ${ignoreForm}`);
    }
    const unknown = [...given.keys()].filter((name) => !['why', 'issue'].includes(name));
    if (unknown.length > 0) {
        return malformed(line, text, `\`ignore\` takes \`why\` and \`issue\`, not \`${unknown[0]}\``);
    }
    const why = given.has('why') ? stringValue(given.get('why')!) : undefined;
    if (!why || why.trim() === '') {
        return malformed(line, text, `\`ignore\` needs its reason, \`why="…"\`: it's ${ignoreForm}`);
    }
    const issueNode = given.get('issue');
    const issue = issueNode ? issueValue(issueNode) : undefined;
    if (issueNode && issue === undefined) {
        return malformed(line, text, issueForm);
    }
    return { kind: 'ignore', line, covers: covers(), rule, why, issue: issue ?? null };
}

function readDefer(call: CallNode, line: number, text: string): Directive {
    if (call.d.args.some((arg) => !arg.d.name || arg.d.argCategory !== ArgCategory.Simple)) {
        return malformed(line, text, `\`defer\` takes keywords only: it's ${deferForm}`);
    }
    const given = new Map(call.d.args.map((arg) => [arg.d.name!.d.value, arg.d.valueExpr]));
    if (given.size !== call.d.args.length) {
        return malformed(line, text, `\`defer\` names a keyword twice: it's ${deferForm}`);
    }
    const unknown = [...given.keys()].filter((name) => !['why', ...tracking].includes(name));
    if (unknown.length > 0) {
        return malformed(line, text, `\`defer\` takes \`why\`, \`issue\` and \`when\`, not \`${unknown[0]}\``);
    }
    const why = given.has('why') ? stringValue(given.get('why')!) : undefined;
    if (!why || why.trim() === '') {
        return malformed(line, text, `\`defer\` needs what's left undone, \`why="…"\`: it's ${deferForm}`);
    }
    const issueNode = given.get('issue');
    const issue = issueNode ? issueValue(issueNode) : undefined;
    if (issueNode && issue === undefined) {
        return malformed(line, text, issueForm);
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

// An `issue`'s value: a number here, or a string such as `"owner/repo#7"`.
function issueValue(node: ExpressionNode): number | string | undefined {
    return integerValue(node) ?? stringValue(node);
}

function integerValue(node: ExpressionNode): number | undefined {
    if (node.nodeType !== ParseNodeType.Number || !node.d.isInteger || node.d.isImaginary) {
        return undefined;
    }
    return Number(node.d.value);
}
