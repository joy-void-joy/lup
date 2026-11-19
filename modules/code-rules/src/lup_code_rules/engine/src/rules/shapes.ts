// Data shapes: a shape is a model, validated where it's declared.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const shapes = {
    'tuple-shape': {
        category: 'design',
        mistake:
            "A tuple's positions hide what each value means, and a second spelling of a sequence beside " +
            '`list[X]` is one more choice for each session to make.',
        steer:
            'Name each field with a model, or write a sequence as `list[X]`; where a library takes a tuple, ' +
            'keep it with an `ignore` that says so.',
        check(file) {
            for (const written of file.typesNaming(['builtins.tuple'])) {
                file.report(
                    written.node,
                    written.alias ? `\`${written.alias}\` is an alias of a tuple type` : `\`${written.text}\` is a tuple type`
                );
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def location(name: str) -> tuple[str, int]:
                            """Return the file and line that define \`name\`."""
                            return name, 1
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Location(Model):
                            """A file, and a line in it."""

                            path: str
                            line: int


                        def location(name: str) -> Location:
                            """Return the file and line that define \`name\`."""
                            return Location(path=name, line=1)
                    `,
                },
                {
                    code: python`
                        def total(sizes: tuple[int, ...]) -> int:
                            """Add up the sizes."""
                            return sum(sizes)
                    `,
                    rewritten: python`
                        def total(sizes: list[int]) -> int:
                            """Add up the sizes."""
                            return sum(sizes)
                    `,
                },
            ],
            passes: [
                python`
                    def is_tuple(value: object) -> bool:
                        """Say whether \`value\` is a tuple."""
                        return isinstance(value, tuple)
                `,
                python`
                    def frozen(sizes: list[int]) -> object:
                        """Return the sizes as a tuple, for hashing."""
                        return tuple(sizes)
                `,
            ],
        },
    },

    'set-shape': {
        category: 'design',
        mistake: 'A set keeps only membership, throwing away what a dict keyed by its members would record.',
        steer:
            'Use a dict keyed by the members, or a list of models; a set that truly records nothing, such as ' +
            'things already seen, takes an `ignore` that says so.',
        check(file) {
            const sets = ['builtins.set', 'builtins.frozenset', 'typing.AbstractSet', 'typing.MutableSet'];
            for (const written of file.typesNaming(sets)) {
                file.report(
                    written.node,
                    written.alias ? `\`${written.alias}\` is an alias of a set type` : `\`${written.text}\` is a set type`
                );
            }
            for (const built of file.builds(['builtins.set', 'builtins.frozenset'])) {
                file.report(built.node, `\`${built.text}\` builds a set`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def tools(calls: list[str]) -> set[str]:
                            """Return the tools named in \`calls\`."""
                            return set(calls)
                    `,
                    rewritten: python`
                        from collections import Counter


                        def tools(calls: list[str]) -> Counter[str]:
                            """Count the calls to each tool named in \`calls\`."""
                            return Counter(calls)
                    `,
                },
                {
                    code: python`
                        def allowed(tool: str) -> bool:
                            """Say whether \`tool\` may run."""
                            return tool in {"Read", "Grep"}
                    `,
                    rewritten: python`
                        def allowed(tool: str) -> bool:
                            """Say whether \`tool\` may run."""
                            return tool in ["Read", "Grep"]
                    `,
                },
            ],
            passes: [
                python`
                    def sizes(names: list[str]) -> dict[str, int]:
                        """Map each name to its length."""
                        return {name: len(name) for name in names}
                `,
            ],
        },
    },

    'dict-literal-key': {
        category: 'design',
        mistake: 'Reading a dict by literal keys treats it as a record whose schema hides in the places that read it.',
        steer: 'Validate the data once into a model, and read its fields.',
        check(file) {
            for (const read of file.itemReads()) {
                if (file.isStringLiteral(read.key) && file.isMapping(read.receiver)) {
                    file.report(read.node, `\`${read.text}\` reads a \`${file.printType(read.receiver)}\` by a literal key`);
                }
            }
            for (const call of file.methodCalls(['get', 'pop'])) {
                const key = call.argument('key', 0);
                if (key && file.isStringLiteral(key) && file.isMapping(call.receiver)) {
                    file.report(
                        call.node,
                        `\`.${call.method}(…)\` reads a \`${file.printType(call.receiver)}\` by a literal key`
                    );
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import json


                        def tool(payload: str) -> str:
                            """Return the tool a hook's payload names."""
                            data: dict[str, str] = json.loads(payload)
                            return data["tool_name"]
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Payload(Model):
                            """The part of a hook's payload read here."""

                            tool_name: str


                        def tool(payload: str) -> str:
                            """Return the tool a hook's payload names."""
                            return Payload.model_validate_json(payload).tool_name
                    `,
                },
                {
                    code: python`
                        def model(settings: dict[str, str]) -> str:
                            """Return the model the settings name."""
                            return settings.get("model", "default")
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Chosen(Model):
                            """The settings read here."""

                            model: str = "default"


                        def model(settings: dict[str, str]) -> str:
                            """Return the model the settings name."""
                            return Chosen.model_validate(settings).model
                    `,
                },
            ],
            passes: [
                python`
                    def price(prices: dict[str, int], item: str, first: list[int]) -> int:
                        """Look an item's price up in the table, and add the first extra."""
                        return prices[item] + first[0]
                `,
            ],
        },
    },

    dataclass: {
        category: 'design',
        mistake: 'A dataclass is a second way to declare a shape, beside pydantic models, and validates nothing.',
        steer: 'Declare the shape as a model deriving from `lup.types.Model`.',
        check(file) {
            const makers = ['dataclasses.dataclass', 'dataclasses.make_dataclass', 'pydantic.dataclasses.dataclass'];
            for (const used of file.uses(makers)) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from dataclasses import dataclass


                        @dataclass(frozen=True)
                        class Point:
                            """A point on the plane."""

                            x: int
                            y: int
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Point(Model):
                            """A point on the plane."""

                            x: int
                            y: int
                    `,
                },
            ],
            passes: [
                python`
                    from dataclasses import is_dataclass


                    def described(value: type) -> bool:
                        """Say whether a class from elsewhere is a dataclass."""
                        return is_dataclass(value)
                `,
            ],
        },
    },

    namedtuple: {
        category: 'design',
        mistake:
            'A named tuple is a second way to declare a shape, beside pydantic models, and still reads by ' +
            'position.',
        steer: 'Declare the shape as a model deriving from `lup.types.Model`.',
        check(file) {
            const makers = ['collections.namedtuple', 'typing.NamedTuple', 'typing_extensions.NamedTuple'];
            for (const used of file.uses(makers)) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from typing import NamedTuple


                        class Point(NamedTuple):
                            """A point on the plane."""

                            x: int
                            y: int
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Point(Model):
                            """A point on the plane."""

                            x: int
                            y: int
                    `,
                },
            ],
            passes: [
                python`
                    from typing import NewType

                    UserId = NewType("UserId", int)
                `,
            ],
        },
    },

    'model-config': {
        category: 'design',
        mistake: 'A `model_config` assignment reads like a field, though it configures the class.',
        steer: 'Configure the model with class keywords: `class Turn(Model, extra="forbid")`.',
        check(file) {
            for (const declared of file.classes()) {
                if (declared.fullName === 'lup.types.Settings') {
                    continue;
                }
                for (const assigned of declared.assigned) {
                    if (assigned.name === 'model_config') {
                        file.report(assigned.node, `\`${declared.node.d.name.d.value}\` assigns \`model_config\``);
                    }
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pydantic import ConfigDict

                        from lup.types import Model


                        class Turn(Model):
                            """One turn of a conversation."""

                            model_config = ConfigDict(extra="forbid")

                            text: str
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Turn(Model, extra="forbid"):
                            """One turn of a conversation."""

                            text: str
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class Turn(Model, extra="forbid"):
                        """One turn of a conversation, and the model that took it."""

                        text: str
                        model: str = "small"
                `,
            ],
        },
    },

    'default-factory': {
        category: 'design',
        mistake: 'A factory for an empty collection says in a call what a literal default says plainly.',
        steer: 'Default to the literal, `steps: list[Step] = []`, which pydantic copies for each instance.',
        check(file) {
            const empties = ['builtins.list', 'builtins.dict', 'builtins.set'];
            for (const call of file.callsTo(['pydantic.fields.Field'])) {
                const factory = call.argument('default_factory');
                if (!factory) {
                    continue;
                }
                const made = file.lambdaBody(factory);
                if (file.namesOf(factory).some((name) => empties.includes(name)) || (made && file.isEmptyCollection(made))) {
                    file.report(factory, `\`${file.text(factory)}\` builds an empty collection`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pydantic import Field

                        from lup.types import Model


                        class Plan(Model):
                            """The steps a run takes."""

                            steps: list[str] = Field(default_factory=list)
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Plan(Model):
                            """The steps a run takes."""

                            steps: list[str] = []
                    `,
                },
            ],
            passes: [
                python`
                    from datetime import UTC, datetime

                    from pydantic import Field

                    from lup.types import Model


                    class Stamp(Model):
                        """When something happened."""

                        at: datetime = Field(default_factory=lambda: datetime.now(UTC))
                `,
            ],
        },
    },

    'model-mutability': {
        category: 'design',
        mistake:
            "A model deriving straight from pydantic's base, or writing `frozen` itself, leaves whether it can " +
            'change to each model.',
        steer:
            'Derive from `lup.types.Model`, which is frozen, or from `lup.types.MutableModel` where values must ' +
            'change, or `lup.types.Settings`; never write `frozen`.',
        check(file) {
            const pydantic = ['pydantic.main.BaseModel', 'pydantic_settings.main.BaseSettings'];
            const lups = ['lup.types.Model', 'lup.types.MutableModel', 'lup.types.Settings'];
            for (const declared of file.classes()) {
                if (lups.includes(declared.fullName)) {
                    continue;
                }
                const name = declared.node.d.name.d.value;
                for (const base of declared.bases) {
                    const straight = base.names.find((each) => pydantic.includes(each));
                    if (straight) {
                        file.report(base.node, `\`${name}\` derives straight from \`${straight}\``);
                    }
                }
                for (const keyword of declared.keywords) {
                    if (keyword.name === 'frozen') {
                        file.report(keyword.node, `\`${name}\` writes \`frozen\` in its header`);
                    }
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pydantic import BaseModel


                        class Point(BaseModel, frozen=True):
                            """A point on the plane."""

                            x: int
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Point(Model):
                            """A point on the plane."""

                            x: int
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import MutableModel


                    class Tally(MutableModel):
                        """A count that goes up as things happen."""

                        seen: int = 0
                `,
            ],
        },
    },

    'typed-dict': {
        category: 'design',
        mistake: 'A `TypedDict` of our own is a second way to declare a shape, beside pydantic models, and validates nothing.',
        steer:
            'Declare the shape as a model deriving from `lup.types.Model`; a `TypedDict` appears only where a ' +
            "library's API is typed with one, and then it's the library's.",
        check(file) {
            const typedDicts = ['typing.TypedDict', 'typing_extensions.TypedDict'];
            for (const declared of file.classes()) {
                for (const base of declared.bases) {
                    if (base.names.some((each) => typedDicts.includes(each))) {
                        file.report(base.node, `\`${declared.node.d.name.d.value}\` is a \`TypedDict\``);
                    }
                }
            }
            for (const call of file.callsTo(typedDicts)) {
                file.report(call.node, 'this call declares a `TypedDict`');
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from typing import TypedDict


                        class Turn(TypedDict):
                            """One turn of a conversation."""

                            text: str
                    `,
                    rewritten: python`
                        from lup.types import Model


                        class Turn(Model):
                            """One turn of a conversation."""

                            text: str
                    `,
                },
            ],
            passes: [
                python`
                    from collections.abc import Mapping


                    def total(counts: Mapping[str, int]) -> int:
                        """Add up the counts in a mapping, whatever its keys."""
                        return sum(counts.values())
                `,
            ],
        },
    },
} satisfies Catalog;
