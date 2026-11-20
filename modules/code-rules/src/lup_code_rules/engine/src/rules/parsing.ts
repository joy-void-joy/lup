// Parsing: text is read with its format's parser, never taken apart by hand.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const parsing = {
    regex: {
        category: 'design',
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

    'string-split': {
        category: 'design',
        mistake: 'Splitting structured text by hand matches the inputs it was tried on, and fails quietly on the rest.',
        steer:
            "Read the text with its format's parser: `shlex.split` for a command line, `urllib.parse` for a URL, " +
            '`email` for headers, `csv` for rows.',
        check(file) {
            // Records ended by NUL, as git's `-z` output is, are parsed whole by a split
            // on it.
            const nul = '\0';
            for (const call of file.methodCalls(['split', 'rsplit'])) {
                const separator = call.argument('sep', 0);
                const parsed = file.literalText(separator) === nul;
                if (separator && !file.isNone(separator) && !parsed && file.isText(call.receiver)) {
                    file.report(call.node, `\`.${call.method}(…)\` splits a \`${file.printType(call.receiver)}\``);
                }
            }
            for (const call of file.methodCalls(['partition', 'rpartition'])) {
                if (file.literalText(call.argument('sep', 0)) !== nul && file.isText(call.receiver)) {
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
                python`
                    from lup.programs import run


                    def changed() -> list[str]:
                        """Return the paths git says changed, from its output of paths each ended by NUL."""
                        return run("git", "diff", "--name-only", "-z").text().split("\\0")


                    def untracked() -> list[bytes]:
                        """Return the paths git doesn't track, as git writes them."""
                        return run("git", "ls-files", "--others", "-z").output.split(b"\\0")
                `,
            ],
        },
    },

    'string-slice': {
        category: 'design',
        mistake: 'Taking text apart by position breaks quietly as soon as its layout shifts.',
        steer: "Read the text with its format's parser, which says what each part is.",
        check(file) {
            // A head or a tail kept at a size is truncation, `silent-truncation`'s, and
            // `fixed-tool-limit`'s in a tool.
            const sized = new Set(file.sizedSlices().map((slice) => slice.node));
            for (const slice of file.slices()) {
                if (file.isText(slice.receiver) && !sized.has(slice.node)) {
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
                python`
                    def notification(sender: str, body: str, width: int) -> str:
                        """Return the notification of a message: who sent it, and how its text starts and ends."""
                        return f"{sender}: {body[:200]} ... {body[-50:]}, {body[:width]}"
                `,
            ],
        },
    },

    'string-strip': {
        category: 'design',
        mistake: 'Stripping given characters off text takes it apart by hand, and fails quietly on the input it wasn\'t tried on.',
        steer: "Read the text with its format's parser; `.strip()` with no argument, which trims whitespace, is fine.",
        check(file) {
            for (const call of file.methodCalls(['strip', 'lstrip', 'rstrip'])) {
                const chars = call.argument('chars', 0);
                if (chars && !file.isNone(chars) && file.isText(call.receiver)) {
                    file.report(call.node, `\`.${call.method}(…)\` strips given characters off a \`${file.printType(call.receiver)}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def release(tag: str) -> str:
                            """Return the release a tag names: \`1.2\` for \`v1.2\`."""
                            return tag.lstrip("v")
                    `,
                    rewritten: python`
                        from packaging.version import Version


                        def release(tag: str) -> str:
                            """Return the release a tag names: \`1.2\` for \`v1.2\`."""
                            return str(Version(tag))
                    `,
                },
            ],
            passes: [
                python`
                    def tidy(line: str) -> str:
                        """Trim the whitespace around a line."""
                        return line.strip()
                `,
            ],
        },
    },

    'string-replace': {
        category: 'design',
        mistake: 'Rewriting text by replacing pieces of it edits a format by hand, and fails quietly on the input it wasn\'t tried on.',
        steer: "Build or rewrite the text with its format's own tools: `urllib.parse.quote`, `shlex.join`, `json.dumps`.",
        check(file) {
            for (const call of file.methodCalls(['replace'])) {
                if (file.isText(call.receiver)) {
                    file.report(call.node, `\`.replace(…)\` rewrites a \`${file.printType(call.receiver)}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def escaped(url: str) -> str:
                            """Return a URL with its spaces escaped."""
                            return url.replace(" ", "%20")
                    `,
                    rewritten: python`
                        from urllib.parse import quote


                        def escaped(url: str) -> str:
                            """Return a URL with its spaces escaped."""
                            return quote(url, safe=":/?=&")
                    `,
                },
            ],
            passes: [
                python`
                    from datetime import datetime


                    def midnight(moment: datetime) -> datetime:
                        """Return the start of a moment's day."""
                        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
                `,
            ],
        },
    },
} satisfies Catalog;
