// Collections and loops: a collection is built in one expression.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const collections = {
    'collection-loop': {
        category: 'spelling',
        mistake: 'A collection created empty and filled in a loop spreads one value over several statements.',
        steer:
            'Build it with a comprehension, or, where the loop has control flow a comprehension can\'t hold, a ' +
            'nested function that `yield`s.',
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
            ],
        },
    },
} satisfies Catalog;
