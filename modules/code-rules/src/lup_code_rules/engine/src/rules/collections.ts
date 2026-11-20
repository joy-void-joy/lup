// Collections and loops: a collection is built in one expression.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const collections = {
    'collection-loop': {
        category: 'spelling',
        mistake: 'A collection created empty and filled in a loop spreads one value over several statements.',
        steer: "Build it with a comprehension, the loop's `if` its condition.",
        check(file) {
            for (const loop of file.collectionLoops()) {
                file.report(loop.header, `this loop fills \`${loop.name}\`, created empty before it`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def squares(numbers: list[int]) -> list[int]:
                            """Return the square of each number."""
                            squared: list[int] = []
                            for number in numbers:
                                squared.append(number * number)
                            return squared
                    `,
                    rewritten: python`
                        def squares(numbers: list[int]) -> list[int]:
                            """Return the square of each number."""
                            return [number * number for number in numbers]
                    `,
                },
                {
                    code: python`
                        def lengths(words: list[str]) -> dict[str, int]:
                            """Map each word that isn't empty to its length."""
                            found: dict[str, int] = {}
                            for word in words:
                                if word:
                                    found[word] = len(word)
                            return found
                    `,
                    rewritten: python`
                        def lengths(words: list[str]) -> dict[str, int]:
                            """Map each word that isn't empty to its length."""
                            return {word: len(word) for word in words if word}
                    `,
                },
            ],
            passes: [
                python`
                    def merged(counts: dict[str, int], extra: dict[str, int]) -> dict[str, int]:
                        """Add the extra counts to a copy of the counts."""
                        total = dict(counts)
                        for key, value in extra.items():
                            total[key] = total.get(key, 0) + value
                        return total
                `,
                python`
                    def running(numbers: list[int]) -> list[int]:
                        """Return the running total after each number."""
                        totals: list[int] = []
                        total = 0
                        for number in numbers:
                            total += number
                            totals.append(total)
                        return totals
                `,
                python`
                    def distinct(names: list[str]) -> list[str]:
                        """Return the names, each once, in the order first seen."""
                        kept: list[str] = []
                        for name in names:
                            if name not in kept:
                                kept.append(name)
                        return kept
                `,
            ],
        },
    },
} satisfies Catalog;
