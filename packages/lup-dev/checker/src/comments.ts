// The comments in a file, as pyright's tokenizer keeps them, each attached to the
// token after it. A comment holding another `#` (`# type: ignore  # noqa`) is read as
// one comment per part, since each part is written as a comment of its own.

import { TextRange } from 'pyright/common/textRange';
import { ParseFileResults } from 'pyright/parser/parser';

export interface CommentPart {
    // Where the part sits, from its `#`.
    range: TextRange;
    // What follows its `#`, with the whitespace around it trimmed.
    text: string;
}

export function commentParts(parse: ParseFileResults): CommentPart[] {
    const tokens = parse.tokenizerOutput.tokens;
    const parts: CommentPart[] = [];
    for (let index = 0; index < tokens.count; index++) {
        for (const comment of tokens.getItemAt(index).comments ?? []) {
            // The comment's text runs after its `#`, which sits just before it.
            const start = comment.start - 1;
            const written = parse.text.substr(start, comment.length + 1);
            let from = 0;
            while (from < written.length) {
                const next = written.indexOf('#', from + 1);
                const end = next === -1 ? written.length : next;
                parts.push({
                    range: { start: start + from, length: end - from },
                    text: written.substring(from + 1, end).trim(),
                });
                from = end;
            }
        }
    }
    return parts;
}
