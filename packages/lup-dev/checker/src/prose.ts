// The prose in a file, its comments and docstrings, read as words: code in backticks,
// text in double quotes and doctest examples are left out, since they're quoted
// rather than said. No grammar is parsed: the scan only tells prose from what it
// quotes.

import { TextRange } from 'pyright/common/textRange';
import { ParseFileResults } from 'pyright/parser/parser';
import { StringNode } from 'pyright/parser/parseNodes';
import { Token, TokenType } from 'pyright/parser/tokenizerTypes';

import { commentParts } from './comments';

export interface Prose {
    // Where the text sits in the file.
    range: TextRange;
    text: string;
}

export interface Word {
    range: TextRange;
    // The word in lower case.
    text: string;
}

export interface Mark {
    range: TextRange;
    // The mark as written: `` `` `` or `:func:`.
    written: string;
}

// A string's text as written between its quotes.
export function written(node: StringNode): Prose {
    const token = node.d.token;
    const start = token.start + token.prefixLength + token.quoteMarkLength;
    return { range: { start, length: token.escapedValue.length }, text: token.escapedValue };
}

// Each comment, or part of one after another `#`, as prose.
export function comments(parse: ParseFileResults): Prose[] {
    return commentParts(parse).map((part) => ({
        range: { start: part.range.start + 1, length: part.range.length - 1 },
        text: parse.text.substr(part.range.start + 1, part.range.length - 1),
    }));
}

function isLetter(char: string): boolean {
    return char.toLowerCase() !== char.toUpperCase();
}

// The words of a piece of prose, outside backticks, double quotes and doctests.
export function wordsOf(prose: Prose): Word[] {
    const text = prose.text;
    const words: Word[] = [];
    let index = 0;
    let lineStart = true;
    let inDoctest = false;
    while (index < text.length) {
        const char = text[index];
        if (char === '\n') {
            index++;
            lineStart = true;
            continue;
        }
        if (lineStart) {
            lineStart = false;
            let first = index;
            while (first < text.length && (text[first] === ' ' || text[first] === '\t')) {
                first++;
            }
            const blank = first >= text.length || text[first] === '\n';
            // A doctest runs from its `>>>` to the next blank line.
            inDoctest = text.startsWith('>>>', first) || (inDoctest && !blank);
            if (inDoctest) {
                const end = text.indexOf('\n', first);
                index = end === -1 ? text.length : end;
                continue;
            }
        }
        if (char === '`') {
            let run = 0;
            while (text[index + run] === '`') {
                run++;
            }
            const fence = '`'.repeat(run);
            let close = text.indexOf(fence, index + run);
            // Only a run as long as the opening one closes it.
            while (close !== -1 && text[close + run] === '`') {
                close = text.indexOf(fence, close + run + 1);
            }
            index = close === -1 ? text.length : close + run;
            continue;
        }
        if (char === '"' || char === '“') {
            const closing = char === '"' ? '"' : '”';
            const close = text.indexOf(closing, index + 1);
            index = close === -1 ? text.length : close + 1;
            continue;
        }
        if (isLetter(char)) {
            let end = index;
            // A letter run, an apostrophe or a hyphen inside it included: `don't`, and
            // a compound such as `fixed-width`, which is read whole.
            const joins = (at: number) => (text[at] === "'" || text[at] === '-') && isLetter(text[at + 1] ?? '');
            while (end < text.length && (isLetter(text[end]) || joins(end))) {
                end++;
            }
            words.push({
                range: { start: prose.range.start + index, length: end - index },
                text: text.substring(index, end).toLowerCase(),
            });
            index = end;
            continue;
        }
        index++;
    }
    return words;
}

function isRoleChar(char: string): boolean {
    return isLetter(char) || (char >= '0' && char <= '9') || '_-.:'.includes(char);
}

// The reStructuredText marks in a docstring: code between double backticks, and a
// Sphinx role before a backtick (`:func:`). Each span of code is passed over whole,
// so what it holds is never read as a mark; a run of three or more backticks is a
// fence, which isn't one.
export function codeMarks(prose: Prose): Mark[] {
    const text = prose.text;
    const marks: Mark[] = [];
    let index = 0;
    while (index < text.length) {
        if (text[index] !== '`') {
            index++;
            continue;
        }
        let run = 0;
        while (text[index + run] === '`') {
            run++;
        }
        let first = index;
        while (first > 0 && isRoleChar(text[first - 1])) {
            first--;
        }
        const role = text.substring(first, index);
        const isRole = role.length > 2 && role.startsWith(':') && role.endsWith(':') && [...role].some(isLetter);
        if (isRole) {
            marks.push({ range: { start: prose.range.start + first, length: role.length }, written: role });
        }
        const fence = '`'.repeat(run);
        let close = text.indexOf(fence, index + run);
        // Only a run as long as the opening one closes it.
        while (close !== -1 && text[close + run] === '`') {
            close = text.indexOf(fence, close + run + 1);
        }
        const end = close === -1 ? index + run : close + run;
        if (run === 2) {
            marks.push({ range: { start: prose.range.start + index, length: end - index }, written: '``' });
        }
        index = end;
    }
    return marks;
}

export interface Mention {
    range: TextRange;
    // The name mentioned, as listed: `claude`.
    name: string;
    // What holds the mention.
    kind: 'name' | 'string' | 'comment';
}

// Each place `names` occur in `range` of the file's text, in any case.
function occurrences(parse: ParseFileResults, range: TextRange, names: string[], kind: Mention['kind']): Mention[] {
    const lowered = parse.text.substr(range.start, range.length).toLowerCase();
    return names.flatMap((name) => {
        const found: Mention[] = [];
        let at = lowered.indexOf(name.toLowerCase());
        while (at !== -1) {
            found.push({ range: { start: range.start + at, length: name.length }, name, kind });
            at = lowered.indexOf(name.toLowerCase(), at + name.length);
        }
        return found;
    });
}

// Each mention of one of `names`, in any case: in an identifier, once for the
// whole name; in a string, part of an f-string or a comment, at each place it
// occurs, so a mention deep in a docstring is reported on its own line.
export function mentions(parse: ParseFileResults, names: string[]): Mention[] {
    const tokens = parse.tokenizerOutput.tokens;
    const found: Mention[] = [];
    for (let index = 0; index < tokens.count; index++) {
        const token: Token = tokens.getItemAt(index);
        for (const comment of token.comments ?? []) {
            found.push(...occurrences(parse, comment, names, 'comment'));
        }
        if (token.type === TokenType.Identifier) {
            const [first] = occurrences(parse, token, names, 'name');
            if (first) {
                found.push({ ...first, range: token });
            }
        }
        if (isString(token)) {
            found.push(...occurrences(parse, token, names, 'string'));
        }
    }
    return found;
}

function isString(token: Token): boolean {
    return token.type === TokenType.String || token.type === TokenType.FStringMiddle;
}
