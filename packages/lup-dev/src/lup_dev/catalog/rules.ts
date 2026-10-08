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

    // Libraries per job (`docs/conventions.md`, *Libraries per job*).

    subprocess: {
        mistake:
            'A second library for running programs, beside the one the rest of the code uses, splits how ' +
            'commands are run, checked and reported.',
        steer: 'Run programs with `sh`: `sh.git("status")`, or `sh.Command(path)(…)` for one found by path.',
        check(file) {
            for (const imported of file.importsOf(['subprocess'])) {
                file.report(imported.node, `this import brings in \`${imported.module}\``);
            }
            const spawners = ['create_subprocess_exec', 'create_subprocess_shell'];
            for (const used of file.uses(spawners.map((name) => `asyncio.subprocess.${name}`))) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import subprocess


                        def status() -> str:
                            """Return the working tree's status."""
                            return subprocess.run(["git", "status"], capture_output=True, text=True).stdout
                    `,
                    rewritten: python`
                        import sh


                        def status() -> str:
                            """Return the working tree's status."""
                            return str(sh.git("status"))
                    `,
                },
            ],
            passes: [
                python`
                    import asyncio


                    async def pause() -> None:
                        """Give other tasks a turn."""
                        await asyncio.sleep(0)
                `,
            ],
        },
    },

    'os-shell': {
        mistake:
            "Running a program through the shell, or in place of this process, hides its arguments from the " +
            'reader and its failure from the caller.',
        steer: 'Run programs with `sh`, which takes the arguments as a list and raises when the program fails.',
        check(file) {
            const runners = ['system', 'popen', 'posix_spawn', 'posix_spawnp', 'startfile'];
            const execs = ['execl', 'execle', 'execlp', 'execlpe', 'execv', 'execve', 'execvp', 'execvpe'];
            const spawns = ['spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe'];
            for (const used of file.uses([...runners, ...execs, ...spawns].map((name) => `os.${name}`))) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import os


                        def fetch() -> int:
                            """Fetch the remote's commits."""
                            return os.system("git fetch")
                    `,
                    rewritten: python`
                        import sh


                        def fetch() -> None:
                            """Fetch the remote's commits."""
                            sh.git("fetch")
                    `,
                },
            ],
            passes: [
                python`
                    import os


                    def process() -> int:
                        """Return this process's id."""
                        return os.getpid()
                `,
            ],
        },
    },

    argparse: {
        mistake:
            'A second library for command lines, beside the one lup commands use, splits how options are ' +
            'declared, checked and documented.',
        steer: 'Declare the command line with `typer`.',
        check(file) {
            for (const imported of file.importsOf(['argparse', 'optparse', 'getopt'])) {
                file.report(imported.node, `this import brings in \`${imported.module}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import argparse


                        def main() -> None:
                            """Greet the name given."""
                            parser = argparse.ArgumentParser()
                            parser.add_argument("name")
                            print(f"hello {parser.parse_args().name}")
                    `,
                    rewritten: python`
                        import typer

                        app = typer.Typer()


                        @app.command()
                        def main(name: str) -> None:
                            """Greet \`name\`."""
                            typer.echo(f"hello {name}")
                    `,
                },
            ],
            passes: [
                python`
                    import typer


                    def ask() -> bool:
                        """Ask whether to go on."""
                        return typer.confirm("Go on?")
                `,
            ],
        },
    },

    'os-path': {
        mistake: 'Paths handled as strings lose what a path knows, and each place joins and splits them its own way.',
        steer: 'Handle paths with `pathlib`: `Path(root) / "docs"`, `path.suffix`, `path.parent`.',
        check(file) {
            for (const imported of file.importsOf(['os.path', 'posixpath', 'ntpath', 'genericpath'])) {
                file.report(imported.node, `this import brings in \`${imported.module}\``);
            }
            for (const used of file.uses(['os.path', 'posixpath', 'ntpath'])) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import os


                        def docs(root: str) -> str:
                            """Return where the docs are."""
                            return os.path.join(root, "docs")
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def docs(root: str) -> Path:
                            """Return where the docs are."""
                            return Path(root) / "docs"
                    `,
                },
                {
                    code: python`
                        from os.path import splitext


                        def stem(name: str) -> str:
                            """Return a file name without its extension."""
                            return splitext(name)[0]
                    `,
                    rewritten: python`
                        from pathlib import PurePath


                        def stem(name: str) -> str:
                            """Return a file name without its extension."""
                            return PurePath(name).stem
                    `,
                },
            ],
            passes: [
                python`
                    import os


                    def processors() -> int:
                        """Return how many processors there are."""
                        return os.cpu_count() or 1
                `,
            ],
        },
    },

    'os-file-ops': {
        mistake: 'Files handled through string paths, beside `pathlib`, split how files are found, written and removed.',
        steer: 'Handle files with `pathlib`: `path.unlink()`, `path.mkdir(parents=True)`, `path.iterdir()`.',
        check(file) {
            const operations = [
                'remove',
                'unlink',
                'rename',
                'renames',
                'replace',
                'mkdir',
                'makedirs',
                'rmdir',
                'removedirs',
                'listdir',
                'scandir',
                'walk',
                'stat',
                'lstat',
                'chmod',
                'lchmod',
                'symlink',
                'readlink',
                'link',
                'getcwd',
                'getcwdb',
            ];
            for (const used of file.uses(operations.map((name) => `os.${name}`))) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import os


                        def names(directory: str) -> list[str]:
                            """List the names in a directory."""
                            return os.listdir(directory)
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def names(directory: str) -> list[str]:
                            """List the names in a directory."""
                            return [entry.name for entry in Path(directory).iterdir()]
                    `,
                },
            ],
            passes: [
                python`
                    import os


                    def process() -> int:
                        """Return this process's id."""
                        return os.getpid()
                `,
            ],
        },
    },

    'os-environ': {
        mistake:
            "An environment variable read where it's used can't be found or listed, and a missing one fails " +
            'deep inside the code.',
        steer:
            "Read environment variables as fields of the package's settings model (`settings.py`, " +
            'pydantic-settings), validated once.',
        check(file) {
            const readers = [
                ...['environ', 'environb', 'getenv', 'getenvb'].map((name) => `os.${name}`),
                ...['load_dotenv', 'dotenv_values'].map((name) => `dotenv.main.${name}`),
            ];
            for (const used of file.uses(readers)) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import os


                        def editor() -> str:
                            """Return the editor the user chose."""
                            return os.getenv("EDITOR", "vi")
                    `,
                    rewritten: python`
                        from lup.types import Settings


                        class Environment(Settings):
                            """The environment variables read here, one field each."""

                            editor: str = "vi"


                        def editor() -> str:
                            """Return the editor the user chose."""
                            return Environment().editor
                    `,
                },
            ],
            passes: [
                python`
                    import os


                    def process() -> int:
                        """Return this process's id."""
                        return os.getpid()
                `,
            ],
        },
    },

    'rich-progress': {
        mistake: 'A second library for progress bars splits how long work shows its progress.',
        steer: 'Show progress with `tqdm`.',
        check(file) {
            for (const imported of file.importsOf(['rich.progress'])) {
                file.report(imported.node, `this import brings in \`${imported.module}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from rich.progress import track


                        def total(sizes: list[int]) -> int:
                            """Add up the sizes, showing progress."""
                            return sum(track(sizes))
                    `,
                    rewritten: python`
                        from tqdm import tqdm


                        def total(sizes: list[int]) -> int:
                            """Add up the sizes, showing progress."""
                            return sum(tqdm(sizes))
                    `,
                },
            ],
            passes: [
                python`
                    from rich.console import Console


                    def show(text: str) -> None:
                        """Print text with its markup."""
                        Console().print(text)
                `,
            ],
        },
    },

    'pdf-extraction': {
        mistake: "A text extractor's empty result reads as an empty document, so a scanned PDF passes as blank.",
        steer: 'Read the document whole, as a document a model reads, rather than the text a library extracts.',
        check(file) {
            const extractors = ['pypdf', 'PyPDF2', 'PyPDF4', 'pdfminer', 'pdfplumber', 'fitz', 'pymupdf', 'pdftotext'];
            for (const imported of file.importsOf(extractors)) {
                file.report(imported.node, `this import brings in \`${imported.module}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pypdf import PdfReader


                        def text(path: str) -> str:
                            """Return a PDF's text."""
                            return "".join(page.extract_text() for page in PdfReader(path).pages)
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def document(path: str) -> bytes:
                            """Return a PDF whole, for a model that reads documents."""
                            return Path(path).read_bytes()
                    `,
                },
            ],
            passes: [
                python`
                    from pathlib import Path


                    def size(path: str) -> int:
                        """Return a PDF's size in bytes."""
                        return Path(path).stat().st_size
                `,
            ],
        },
    },

    // Errors (`docs/conventions.md`, *Errors*).

    suppress: {
        mistake: 'An error swallowed by `suppress` leaves no trace of what failed, or why.',
        steer: 'Handle the error, log it, or let it rise; where a library can skip the case itself, let it.',
        check(file) {
            for (const used of file.uses(['contextlib.suppress'])) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from contextlib import suppress
                        from pathlib import Path


                        def remove(path: str) -> None:
                            """Remove a file, if it's there."""
                            with suppress(FileNotFoundError):
                                Path(path).unlink()
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def remove(path: str) -> None:
                            """Remove a file, if it's there."""
                            Path(path).unlink(missing_ok=True)
                    `,
                },
            ],
            passes: [
                python`
                    from contextlib import ExitStack


                    def stack() -> ExitStack:
                        """Return an empty stack of exits."""
                        return ExitStack()
                `,
            ],
        },
    },

    'bare-except': {
        mistake: 'A bare `except:` catches everything, `KeyboardInterrupt` and `SystemExit` included, and hides why.',
        steer: 'Catch `Exception` or something narrower, and handle, log or re-raise it.',
        check(file) {
            for (const clause of file.exceptClauses()) {
                if (!clause.d.typeExpr) {
                    file.report(clause.d.exceptToken, 'this `except:` names nothing to catch');
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except:
                                return 0
                    `,
                    rewritten: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except ValueError:
                                return 0
                    `,
                },
            ],
            passes: [
                python`
                    def number(text: str) -> int:
                        """Read a number, or zero."""
                        try:
                            return int(text)
                        except (ValueError, OverflowError):
                            return 0
                `,
            ],
        },
    },

    'except-baseexception': {
        mistake: 'Catching `BaseException` catches `KeyboardInterrupt` and `SystemExit` too, so nothing can stop the code.',
        steer: 'Catch `Exception` or something narrower, and handle, log or re-raise it.',
        check(file) {
            for (const clause of file.exceptClauses()) {
                for (const caught of file.caught(clause)) {
                    if (caught.class === 'builtins.BaseException') {
                        file.report(caught.node, 'this clause catches `BaseException`');
                    }
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except BaseException:
                                return 0
                    `,
                    rewritten: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except ValueError:
                                return 0
                    `,
                },
            ],
            passes: [
                python`
                    def wait() -> None:
                        """Wait until interrupted."""
                        try:
                            input()
                        except KeyboardInterrupt:
                            return
                `,
            ],
        },
    },

    'suppression-comment': {
        mistake: 'A second suppression syntax hides a finding without the operator ever being asked.',
        steer: 'Keep one finding with `# lup: ignore("<rule>", why="<reason>")`, which asks the operator.',
        check(file) {
            const markers = [
                'noqa',
                'type: ignore',
                'pyright: ignore',
                'pyright: basic',
                'pyright: standard',
                'pyright: report',
                'ruff: noqa',
                'ruff: disable',
            ];
            for (const comment of file.commentsStartingWith(markers)) {
                file.report(comment.range, `\`# ${comment.text}\` is a suppression comment`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def width() -> int:
                            """Return the width."""
                            return 1  # noqa: PLR2004
                    `,
                    rewritten: python`
                        def width() -> int:
                            """Return the width."""
                            return 1
                    `,
                },
                {
                    code: python`
                        def width() -> int:
                            """Return the width."""
                            return "1"  # type: ignore[return-value]
                    `,
                    rewritten: python`
                        def width() -> int:
                            """Return the width."""
                            return 1
                    `,
                },
            ],
            passes: [
                python`
                    def width() -> int:
                        """Return the width."""
                        # the type checker reads this
                        return 1
                `,
            ],
        },
    },

    // Types (`docs/conventions.md`, *Types*).

    'any-type': {
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
