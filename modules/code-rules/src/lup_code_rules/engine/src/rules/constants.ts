// Constants: a constant has a home, where a caller can change it.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const constants = {
    'constant-home': {
        category: 'design',
        mistake:
            'A constant outside its home is frozen where a caller can\'t change it, spread where nobody can ' +
            "find it, or kept as data pyright can't check its uses against.",
        steer:
            'A number or a duration becomes a default a caller can override, a parameter\'s or a field\'s, and a ' +
            "list a caller might change a field's default on the model that uses it; a closed set of options " +
            'becomes a `Literal` type, its members read with `typing.get_args`: ' +
            '`name in get_args(Format.__value__)` to test one, `list(get_args(Format.__value__))` to keep them; ' +
            'a fixed table from one vocabulary to another becomes a function that `match`es; ' +
            "a path goes in the package's `layout.py`, an " +
            "environment variable's name in its `settings.py`, and a runtime's wire spelling in its adapter, as a " +
            "field of the adapter's model or a `Literal`.",
        check(file) {
            const layout = `.${file.moduleName}`.endsWith('.layout');
            for (const constant of file.moduleConstants()) {
                if (constant.kind === 'number' || constant.kind === 'duration') {
                    file.report(constant.node, `\`${constant.name}\` holds a ${constant.kind} at module level`);
                }
                if (constant.kind === 'path' && !layout) {
                    file.report(constant.node, `\`${constant.name}\` holds a path outside the package's \`layout.py\``);
                }
                // `__all__` is Python's, read by its name; `layout.py` is the home of
                // paths and file names, which a collection there may hold as strings.
                if (constant.collection && constant.name !== '__all__' && !layout) {
                    file.report(
                        constant.node,
                        `\`${constant.name}\` holds a ${constant.collection} of plain literals at module level`
                    );
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import time

                        RETRIES = 3


                        def fetch() -> None:
                            """Try a few times."""
                            for _ in range(RETRIES):
                                time.sleep(0)
                    `,
                    rewritten: python`
                        import time


                        def fetch(retries: int = 3) -> None:
                            """Try a few times."""
                            for _ in range(retries):
                                time.sleep(0)
                    `,
                },
                {
                    code: python`
                        from lup.types import Model

                        RETRIED = [429, 502, 503]


                        class Retrying(Model):
                            """When a failed request is tried again."""

                            def transient(self, status: int) -> bool:
                                """Say whether a failure with this status may pass when tried again."""
                                return status in RETRIED
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Retrying(Model):
                            """When a failed request is tried again."""

                            statuses: list[int] = [429, 502, 503]

                            def transient(self, status: int) -> bool:
                                """Say whether a failure with this status may pass when tried again."""
                                return status in self.statuses
                    `,
                },
                {
                    code: python`
                        FORMATS = ["json", "toml"]


                        def known(name: str) -> bool:
                            """Say whether a configuration's format is one we read."""
                            return name in FORMATS
                    `,
                    rewritten: python`
                        from typing import Literal, get_args

                        type Format = Literal["json", "toml"]


                        def known(name: str) -> bool:
                            """Say whether a configuration's format is one we read."""
                            return name in get_args(Format.__value__)
                    `,
                },
                {
                    code: python`
                        SEVERITIES = ["low", "high", "critical"]


                        def worst(found: list[str]) -> str:
                            """Return the most severe of the severities found."""
                            return max(found, key=SEVERITIES.index)
                    `,
                    rewritten: python`
                        from typing import Literal, get_args

                        type Severity = Literal["low", "high", "critical"]


                        def worst(found: list[Severity]) -> Severity:
                            """Return the most severe of the severities found."""
                            order: list[Severity] = list(get_args(Severity.__value__))
                            return max(found, key=order.index)
                    `,
                },
                {
                    code: python`
                        SUFFIXES = {"json": ".json", "toml": ".toml"}


                        def suffix(kind: str) -> str:
                            """Return the suffix a configuration's file takes in a format."""
                            return SUFFIXES[kind]
                    `,
                    rewritten: python`
                        from typing import Literal

                        type Format = Literal["json", "toml"]


                        def suffix(kind: Format) -> str:
                            """Return the suffix a configuration's file takes in a format."""
                            match kind:
                                case "json":
                                    return ".json"
                                case "toml":
                                    return ".toml"
                    `,
                },
            ],
            passes: [
                python`
                    GREETING = "hello"


                    def greet() -> str:
                        """Return the greeting."""
                        return GREETING
                `,
                python`
                    __all__ = ["greet"]


                    def greet() -> str:
                        """Return a greeting."""
                        return "hello"
                `,
                python`
                    from lup.types import Model


                    class Tool(Model):
                        """A tool an agent may call."""

                        name: str


                    TOOLS = [Tool(name="read"), Tool(name="write")]
                `,
                python`
                    from typing import Literal

                    type Mode = Literal["fast", "slow"]
                `,
            ],
        },
    },
} satisfies Catalog;
