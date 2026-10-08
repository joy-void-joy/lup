// Where a node is, as the Python side counts: lines and columns from 1, columns in
// code points (pyright counts JavaScript string units, which differ past the Basic
// Multilingual Plane). pyright's range for a parenthesized expression covers its
// parentheses, which can start it a line early; a span leaves them out, as Python's
// own `ast` does.

import { convertOffsetToPosition } from 'pyright/common/positionUtils';
import { TextRange } from 'pyright/common/textRange';
import { ParseFileResults } from 'pyright/parser/parser';
import { TokenType } from 'pyright/parser/tokenizerTypes';

import { Position, Span } from './protocol';

export function spanOf(parse: ParseFileResults, range: TextRange): Span {
    const inner = withoutParentheses(parse, range);
    return {
        start: positionOf(parse, inner.start),
        end: positionOf(parse, TextRange.getEnd(inner)),
    };
}

export function positionOf(parse: ParseFileResults, offset: number): Position {
    const lines = parse.tokenizerOutput.lines;
    const position = convertOffsetToPosition(offset, lines);
    const lineStart = lines.getItemAt(position.line)?.start ?? 0;
    const before = parse.text.substring(lineStart, lineStart + position.character);
    return { line: position.line + 1, column: Array.from(before).length + 1 };
}

// The range without the pairs of parentheses wrapping it whole.
function withoutParentheses(parse: ParseFileResults, range: TextRange): TextRange {
    const tokens = parse.tokenizerOutput.tokens;
    if (range.length === 0) {
        return range;
    }
    let first = tokens.getItemAtPosition(range.start);
    let last = tokens.getItemAtPosition(TextRange.getEnd(range) - 1);
    while (
        first < last &&
        tokens.getItemAt(first).type === TokenType.OpenParenthesis &&
        tokens.getItemAt(last).type === TokenType.CloseParenthesis &&
        pairs(parse, first, last)
    ) {
        first += 1;
        last -= 1;
    }
    const start = tokens.getItemAt(first).start;
    return { start, length: TextRange.getEnd(tokens.getItemAt(last)) - start };
}

// Whether the parenthesis at token `first` is closed by the one at `last`, rather
// than earlier: `(a)(b)` starts and ends with parentheses that aren't a pair.
function pairs(parse: ParseFileResults, first: number, last: number): boolean {
    const tokens = parse.tokenizerOutput.tokens;
    let depth = 0;
    for (let index = first; index <= last; index++) {
        const type = tokens.getItemAt(index).type;
        depth += type === TokenType.OpenParenthesis ? 1 : type === TokenType.CloseParenthesis ? -1 : 0;
        if (depth === 0 && index < last) {
            return false;
        }
    }
    return depth === 0;
}
