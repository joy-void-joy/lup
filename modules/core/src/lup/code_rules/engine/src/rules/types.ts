// Types: a type says what the value is.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const types = {
    'any-type': {
        category: 'design',
        mistake: '`Any` turns type checking off for everything it touches.',
        steer: 'Give the real type, a type parameter, or `JsonValue` or `JsonObject` for JSON whose schema lives elsewhere.',
        check(file) {
            for (const used of file.uses(['typing.Any', 'typing_extensions.Any'])) {
                file.report(used.node, used.renamed ? `\`Any\` is imported as \`${used.renamed}\`` : 'this is `Any`');
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from typing import Any


                        def size(value: Any) -> int:
                            """Return the size of \`value\`."""
                            return len(value)
                    `,
                    rewritten: python`
                        def size(value: str | list[str]) -> int:
                            """Return the size of \`value\`."""
                            return len(value)
                    `,
                },
            ],
            passes: [
                python`
                    def anything(values: list[bool]) -> bool:
                        """Say whether any value holds."""
                        return any(values)
                `,
            ],
        },
    },

    cast: {
        category: 'design',
        mistake: '`cast` asserts a type without checking it, so a wrong one passes silently.',
        steer: 'Narrow with `isinstance` or `match`, or validate with a model, so the type is checked.',
        check(file) {
            for (const used of file.uses(['typing.cast', 'typing_extensions.cast'])) {
                file.report(used.node, 'this is `cast`');
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from typing import cast


                        def text(value: str | int) -> str:
                            """Return \`value\`, which callers pass as text."""
                            return cast("str", value)
                    `,
                    rewritten: python`
                        def text(value: str | int) -> str:
                            """Return \`value\` as text."""
                            return value if isinstance(value, str) else str(value)
                    `,
                },
            ],
            passes: [
                python`
                    def unsigned(data: bytes) -> list[int]:
                        """Read bytes as unsigned numbers."""
                        return memoryview(data).cast("B").tolist()
                `,
            ],
        },
    },

    'bare-object': {
        category: 'design',
        mistake: '`object` as a type says nothing about the value, so every use needs a check the type could have done.',
        steer: 'Give the real type, a type parameter, or `JsonValue` or `JsonObject` for JSON whose schema lives elsewhere.',
        check(file) {
            for (const written of file.typesNaming(['builtins.object'])) {
                if (!file.inDunderParameter(written.node)) {
                    file.report(
                        written.node,
                        written.alias ? `\`${written.alias}\` is an alias of \`object\`` : 'this type is `object`'
                    );
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def first(values: list[object]) -> object:
                            """Return the first of \`values\`."""
                            return values[0]
                    `,
                    rewritten: python`
                        def first[T](values: list[T]) -> T:
                            """Return the first of \`values\`."""
                            return values[0]
                    `,
                },
            ],
            passes: [
                python`
                    class Point:
                        """A point, equal to another at the same place."""

                        def __init__(self, x: int) -> None:
                            """Place the point."""
                            self.x = x

                        def __eq__(self, other: object) -> bool:
                            """Say whether \`other\` is a point at the same place."""
                            return isinstance(other, Point) and other.x == self.x

                        def __hash__(self) -> int:
                            """Hash the point by its place."""
                            return hash(self.x)
                `,
            ],
        },
    },
} satisfies Catalog;
