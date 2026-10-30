// What the page says on one row: the top bar's words, the line under the review, and what's said after a key, each
// in a sentence, its whole a key away (`g<`, the panel of what was said whole; `docs/dashboard.md`, *The keys*). A line
// that wrapped pushed the review down, and one listing forty numbers said nothing a count doesn't. Pure.

/** A run of two or more citations of items or their parts, `@51, @58 and @69` or `@51 @58`: counted where a line says it. */
const RUN = /@\d+(?:\.\d+(?:[–-]\d+)?)?(?:(?:,\s*|\s+and\s+|\s+)@\d+(?:\.\d+(?:[–-]\d+)?)?)+/g;

/** Say `text` with each run of two or more citations counted, `@51, @58 and @69` as `3 items`, the rest as it is. */
export function countedRuns(text: string): string {
    return text.replace(RUN, (run) => `${run.match(/@\d+/g)?.length ?? 0} items`);
}

/**
 * Say `text` on one line: each run of two or more citations counted (`countedRuns`), and its first sentence alone,
 * ending where a full stop is followed by more; what's left out is in its whole, which `g<` shows.
 */
export function brief(text: string): string {
    const counted = countedRuns(text);
    const end = /[.!?](?=\s+\S)/.exec(counted);
    const first = end === null ? counted : counted.slice(0, end.index + 1);
    return first.replace(/\s+/g, " ").trim();
}

/** Say whether `brief` leaves anything of `text` out but its spacing: a count in place of numbers, or a sentence after the first. */
export function shortened(text: string): boolean {
    return brief(text) !== text.replace(/\s+/g, " ").trim();
}

/**
 * Say the parts of a reply, or what sending it did, on one line, between `between`: each run of numbers counted
 * (`countedRuns`), and two or more threads marked alike, `@reader read` and `@auth read`, as `2 threads read`, said where
 * the first of them was.
 */
export function partsSaid(parts: readonly string[], between: string = " · "): string {
    const alike = (part: string) => /^@[^\s@]+ (\w+)$/.exec(part)?.[1];
    const threads = new Map<string, number>();
    for (const part of parts) {
        const how = alike(part);
        if (how !== undefined) {
            threads.set(how, (threads.get(how) ?? 0) + 1);
        }
    }
    const said = new Set<string>();
    return parts
        .flatMap((part) => {
            const how = alike(part);
            const count = how === undefined ? 0 : (threads.get(how) ?? 0);
            if (how === undefined || count < 2) {
                return [countedRuns(part)];
            }
            if (said.has(how)) {
                return [];
            }
            said.add(how);
            return [`${count} threads ${how}`];
        })
        .join(between);
}
