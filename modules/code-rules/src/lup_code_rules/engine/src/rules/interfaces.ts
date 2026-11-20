// Interfaces: an interface is a lean ABC its implementations inherit.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const interfaces = {
    protocol: {
        category: 'design',
        mistake:
            'A `Protocol` is a second way to declare an interface, beside an ABC, matched by shape and checked ' +
            'only by pyright.',
        steer:
            "Declare the interface as an ABC its implementations inherit; for a shape we don't own, keep the " +
            '`Protocol` with an `ignore` saying so.',
        check(file) {
            const protocols = ['typing.Protocol', 'typing_extensions.Protocol'];
            for (const declared of file.classes()) {
                for (const base of declared.bases) {
                    if (base.names.some((each) => protocols.includes(each))) {
                        file.report(base.node, `\`${declared.node.d.name.d.value}\` is a \`Protocol\``);
                    }
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from typing import Protocol


                        class Greeter(Protocol):
                            """Something that greets."""

                            def greet(self) -> str:
                                """Return a greeting."""
                                ...
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Greeter(ABC):
                            """Something that greets."""

                            @abstractmethod
                            def greet(self) -> str:
                                """Return a greeting."""
                    `,
                },
            ],
            passes: [
                python`
                    from collections.abc import Iterable


                    def total(values: Iterable[int]) -> int:
                        """Add up \`values\`."""
                        return sum(values)
                `,
            ],
        },
    },

    'interface-shape': {
        category: 'design',
        mistake:
            'An interface whose shape drifts, abstract without saying so, large, carrying behaviour or ' +
            'implemented twice in one class, stops being one seam an implementation fills.',
        steer:
            'Name `ABC` in the bases of a class with abstract methods; keep an ABC to one to three abstract ' +
            'methods and no concrete behaviour, which lives in a plain class or function composed over it; ' +
            'implement one of our ABCs per class.',
        check(file) {
            for (const declared of file.classes()) {
                const name = declared.node.d.name.d.value;
                if (declared.abstract.length > 0 && !declared.listsABC) {
                    file.report(declared.node.d.name, `\`${name}\` declares abstract methods without \`ABC\` in its bases`);
                }
                if (declared.ourABCBases.length > 1) {
                    const listed = declared.ourABCBases.map((base) => `\`${base}\``).join(' and ');
                    file.report(declared.node.d.name, `\`${name}\` inherits two of our ABCs, ${listed}`);
                }
                if (!declared.listsABC) {
                    continue;
                }
                const count = declared.abstract.length;
                if (count === 0 || count > 3) {
                    file.report(declared.node.d.name, `\`${name}\` is an ABC with ${count} abstract methods`);
                }
                for (const method of declared.concrete) {
                    file.report(method.d.name, `\`${name}.${method.d.name.d.value}\` is concrete behaviour in an ABC`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from abc import abstractmethod

                        from lup.types import Model


                        class Shape(Model):
                            """A shape that knows its area."""

                            @abstractmethod
                            def area(self) -> float:
                                """Return the shape's area."""
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod

                        from lup.types import Model


                        class Shape(Model, ABC):
                            """A shape that knows its area."""

                            @abstractmethod
                            def area(self) -> float:
                                """Return the shape's area."""
                    `,
                },
                {
                    code: python`
                        from abc import ABC, abstractmethod


                        class Shape(ABC):
                            """A shape that knows its area."""

                            @abstractmethod
                            def area(self) -> float:
                                """Return the shape's area."""

                            def described(self) -> str:
                                """Describe the shape by its area."""
                                return f"area {self.area()}"
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Shape(ABC):
                            """A shape that knows its area."""

                            @abstractmethod
                            def area(self) -> float:
                                """Return the shape's area."""


                        def described(shape: Shape) -> str:
                            """Describe a shape by its area."""
                            return f"area {shape.area()}"
                    `,
                },
                {
                    code: python`
                        from abc import ABC, abstractmethod


                        class Reader(ABC):
                            """Something that reads."""

                            @abstractmethod
                            def read(self) -> str:
                                """Return what was read."""


                        class Writer(ABC):
                            """Something that writes."""

                            @abstractmethod
                            def write(self, text: str) -> int:
                                """Write \`text\`, returning how much was written."""


                        class Store(Reader, Writer):
                            """A store, read and written."""

                            def read(self) -> str:
                                """Return the store's text."""
                                return ""

                            def write(self, text: str) -> int:
                                """Write \`text\` to the store."""
                                return len(text)
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Reader(ABC):
                            """Something that reads."""

                            @abstractmethod
                            def read(self) -> str:
                                """Return what was read."""


                        class Writer(ABC):
                            """Something that writes."""

                            @abstractmethod
                            def write(self, text: str) -> int:
                                """Write \`text\`, returning how much was written."""


                        class StoreReader(Reader):
                            """A store, read."""

                            def read(self) -> str:
                                """Return the store's text."""
                                return ""


                        class StoreWriter(Writer):
                            """A store, written."""

                            def write(self, text: str) -> int:
                                """Write \`text\` to the store."""
                                return len(text)
                    `,
                },
            ],
            passes: [
                python`
                    from abc import ABC, abstractmethod


                    class Shape(ABC):
                        """A shape that knows its area."""

                        @abstractmethod
                        def area(self) -> float:
                            """Return the shape's area."""


                    class Square(Shape):
                        """A square, by its side."""

                        def __init__(self, side: float) -> None:
                            """Make a square of \`side\`."""
                            self.side = side

                        def area(self) -> float:
                            """Return the square's area."""
                            return self.side * self.side
                `,
                python`
                    from abc import ABC, abstractmethod
                    from typing import overload

                    from lup.types import Model


                    class Asker(ABC):
                        """Something that answers a prompt, in words or as a model."""

                        @overload
                        def ask(self, prompt: str) -> str: ...
                        @overload
                        def ask[O: Model](self, prompt: str, output: type[O]) -> O: ...
                        @abstractmethod
                        def ask[O: Model](self, prompt: str, output: type[O] | None = None) -> str | O:
                            """Answer \`prompt\`, as \`output\` where it's given."""
                `,
            ],
        },
    },
} satisfies Catalog;
