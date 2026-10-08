// lup's code rules: one entry per rule, keyed by its id, holding the mistake it
// prevents, where it steers, its check, and its examples (`docs/judging-writes.md`,
// *How a rule is declared*).
//
// A check reads pyright's tree and asks pyright's type evaluator, through the
// engine's helpers (`packages/lup-dev/checker/src/`), and reports where it found its
// case and what it saw there; the engine adds the mistake and the steer. Each check
// stays short: what checks share is a helper, outside this table.
//
// The examples are the rule's specification, which the engine's tests run, each as a
// module of a small package:
// - each of `flags` gets a finding from this rule and no other, and its `rewritten`,
//   the same code done the steer's way, passes every rule, ruff and pyright;
// - each of `passes`, a near miss, gets no finding from this rule.
// A rule needing a long example has a check or a steer that's too broad.

import type { Catalog } from 'checker/catalog';
import { python } from 'checker/examples';

export const rules = {
    regex: {
        mistake:
            'A regular expression matches the cases it was tried on and fails quietly on the rest, ' +
            'and the bugs it leaves are hard to find.',
        steer:
            "Read the text with its format's parser (`json`, `tomllib`, `csv`, `urllib.parse`, `shlex`, `ast`, " +
            '`packaging.version`), and give a grammar of our own a parser library.',
        check(file) {
            for (const imported of file.importsOf(['re', 'regex'])) {
                file.report(imported.node, `this import brings in \`${imported.module}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import re


                        def major(version: str) -> int:
                            """Return the major part of a version number."""
                            found = re.match("[0-9]+", version)
                            return int(found.group()) if found else 0
                    `,
                    rewritten: python`
                        from packaging.version import Version


                        def major(version: str) -> int:
                            """Return the major part of a version number."""
                            return Version(version).major
                    `,
                },
            ],
            passes: [
                python`
                    import reprlib


                    def shown(value: str) -> str:
                        """Show a value, shortened for a log line."""
                        return reprlib.repr(value)
                `,
            ],
        },
    },

    'tuple-shape': {
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

    'string-split': {
        mistake: 'Splitting structured text by hand matches the inputs it was tried on, and fails quietly on the rest.',
        steer:
            "Read the text with its format's parser: `shlex.split` for a command line, `urllib.parse` for a URL, " +
            '`email` for headers, `csv` for rows.',
        check(file) {
            for (const call of file.methodCalls(['split', 'rsplit'])) {
                const separator = call.argument('sep', 0);
                if (separator && !file.isNone(separator) && file.isText(call.receiver)) {
                    file.report(call.node, `\`.${call.method}(…)\` splits a \`${file.printType(call.receiver)}\``);
                }
            }
            for (const call of file.methodCalls(['partition', 'rpartition'])) {
                if (file.isText(call.receiver)) {
                    file.report(call.node, `\`.${call.method}(…)\` splits a \`${file.printType(call.receiver)}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def host(url: str) -> str:
                            """Return the host \`url\` names."""
                            return url.split("/")[2]
                    `,
                    rewritten: python`
                        from urllib.parse import urlsplit


                        def host(url: str) -> str:
                            """Return the host \`url\` names, or nothing when it names none."""
                            return urlsplit(url).hostname or ""
                    `,
                },
            ],
            passes: [
                python`
                    import shlex


                    def words(line: str) -> list[str]:
                        """Split a command line as a shell would, and a sentence on its spaces."""
                        return [*shlex.split(line), *line.split(), *line.split(None, 1)]
                `,
            ],
        },
    },

    'string-slice': {
        mistake: 'Taking text apart by position breaks quietly as soon as its layout shifts.',
        steer: "Read the text with its format's parser, which says what each part is.",
        check(file) {
            for (const slice of file.slices()) {
                if (file.isText(slice.receiver)) {
                    file.report(slice.node, `\`${slice.text}\` slices a \`${file.printType(slice.receiver)}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def branch(ref: str) -> str:
                            """Return the branch a git ref names."""
                            return ref[len("refs/heads/") :]
                    `,
                    rewritten: python`
                        from pathlib import PurePosixPath


                        def branch(ref: str) -> str:
                            """Return the branch a git ref names."""
                            return PurePosixPath(ref).relative_to("refs/heads").as_posix()
                    `,
                },
            ],
            passes: [
                python`
                    def rest(items: list[int], name: str) -> list[int]:
                        """Return all but the first item, and the length of \`name\`'s first letter."""
                        return [*items[1:], len(name[0])]
                `,
            ],
        },
    },

    'dict-literal-key': {
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
} satisfies Catalog;
