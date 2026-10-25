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
        steer:
            'Run programs with `lup.programs`: `run("git", "status", cwd=root)`, which starts them safely beside ' +
            'threads and raises on a status the caller doesn\'t accept; on an event loop, `await awaited(…)`, ' +
            'which holds no thread, or `started(…)` for one the caller talks to while it runs; or ' +
            '`detached(…)` for one that outlives its caller.',
        check(file) {
            for (const imported of file.importsOf(['subprocess', 'sh'])) {
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
                        from lup.programs import run


                        def status() -> str:
                            """Return the working tree's status."""
                            return run("git", "status").text()
                    `,
                },
                {
                    code: python`
                        import asyncio


                        async def status() -> bytes:
                            """Return the working tree's status."""
                            process = await asyncio.create_subprocess_exec(
                                "git", "status", stdout=asyncio.subprocess.PIPE
                            )
                            output, _ = await process.communicate()
                            return output
                    `,
                    rewritten: python`
                        from lup.programs import awaited


                        async def status() -> bytes:
                            """Return the working tree's status."""
                            return (await awaited("git", "status")).output
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
        steer:
            'Run programs with `lup.programs.run`, which takes the arguments as a list and raises when the ' +
            'program fails.',
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
                        from lup.programs import run


                        def fetch() -> None:
                            """Fetch the remote's commits."""
                            run("git", "fetch")
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

    // Data shapes (`docs/conventions.md`, *Data shapes*).

    dataclass: {
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

    // Names (`docs/conventions.md`, *Names*).

    'all-export': {
        mistake:
            "`__all__` outside a package's root makes a second public list, beside the one the package's root " +
            'declares.',
        steer: "Leave `__all__` to the package's root; elsewhere, import each name from the module that defines it.",
        check(file) {
            if (file.isPackageRoot) {
                return;
            }
            for (const assigned of file.moduleAssignments()) {
                if (assigned.name === '__all__') {
                    file.report(assigned.node, "this module isn't a package's root");
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        __all__ = ["greet"]


                        def greet() -> str:
                            """Return a greeting."""
                            return "hello"
                    `,
                    rewritten: python`
                        def greet() -> str:
                            """Return a greeting."""
                            return "hello"
                    `,
                },
            ],
            passes: [
                python`
                    import json


                    def exported() -> list[str]:
                        """List what \`json\` exports."""
                        return list(json.__all__)
                `,
            ],
        },
    },

    // Interfaces (`docs/conventions.md`, *Interfaces*).

    protocol: {
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

    // Dispatch (`docs/conventions.md`, *Dispatch*).

    elif: {
        mistake: 'An `elif` chain hides which value decides, arm after arm.',
        steer:
            "Decide on a value's structure with `match`; compare with guard clauses that return, one `if` " +
            'after another.',
        check(file) {
            for (const keyword of file.elifs()) {
                file.report(keyword, 'this is an `elif`');
            }
            for (const keyword of file.elseIfs()) {
                file.report(keyword, 'this `if` is all its `else` holds, an `elif` written out');
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            elif seconds < 3600:
                                return "m"
                            return "h"
                    `,
                    rewritten: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            if seconds < 3600:
                                return "m"
                            return "h"
                    `,
                },
                {
                    code: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                unit = "s"
                            else:
                                if seconds < 3600:
                                    unit = "m"
                                else:
                                    unit = "h"
                            return unit
                    `,
                    rewritten: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            if seconds < 3600:
                                return "m"
                            return "h"
                    `,
                },
            ],
            passes: [
                python`
                    def sign(number: int) -> int:
                        """Return the sign of a number."""
                        if number < 0:
                            return -1
                        return 1 if number > 0 else 0
                `,
            ],
        },
    },

    'wildcard-guard': {
        mistake: 'A guard on a pattern that matches anything is an `if` chain dressed as a `match`.',
        steer:
            'Write a pattern that binds what the guard reads (`case Lease(reason=str() as reason) if reason:`), ' +
            'or compare with guard clauses.',
        check(file) {
            for (const guarded of file.guardedCases()) {
                if (guarded.irrefutable) {
                    file.report(guarded.range, `\`${file.text(guarded.range)}\` guards a pattern that matches anything`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            match seconds:
                                case _ if seconds < 60:
                                    return "s"
                                case _:
                                    return "m"
                    `,
                    rewritten: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            return "m"
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class Lease(Model):
                        """A hold on a resource, and why it's held."""

                        reason: str


                    def why(lease: Lease | None) -> str:
                        """Say why a lease is held, if it is."""
                        match lease:
                            case Lease(reason=str() as reason) if reason:
                                return reason
                            case _:
                                return "unheld"
                `,
            ],
        },
    },

    'isinstance-chain': {
        mistake: 'A chain of `isinstance` tests on one value hides that it decides on its class, arm after arm.',
        steer: 'Decide with a `match` on the value, a class pattern each arm: `case int():`.',
        check(file) {
            for (const chain of file.isinstanceChains()) {
                const [first, ...rest] = chain;
                for (const arm of rest) {
                    file.report(arm.node, `\`${arm.subject}\` was narrowed by \`isinstance\` in an arm before, at \`${file.text(first.node)}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def size(value: int | str | list[int]) -> int:
                            """Return how big a value is."""
                            if isinstance(value, int):
                                return value
                            if isinstance(value, str):
                                return len(value)
                            return len(value)
                    `,
                    rewritten: python`
                        def size(value: int | str | list[int]) -> int:
                            """Return how big a value is."""
                            match value:
                                case int():
                                    return value
                                case _:
                                    return len(value)
                    `,
                },
            ],
            passes: [
                python`
                    def size(value: int | str) -> int:
                        """Return how big a value is."""
                        if isinstance(value, int):
                            return value
                        return len(value)
                `,
            ],
        },
    },

    // Parsing (`docs/conventions.md`, *Parsing*), continued.

    'string-strip': {
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

    // Truncation and comments (`docs/conventions.md`, *Truncation and comments*).

    'silent-truncation': {
        mistake: 'A sequence cut at a fixed bound to make it fit drops what lies past it, and nothing says so.',
        steer: 'Keep the whole value; where a format forces a limit, save the full copy, point at it, and say so in an `ignore`.',
        check(file) {
            for (const cut of file.cuts()) {
                // A bound a field sets is a setting, which a caller can change. A cut of
                // text is `string-slice`'s, and a cut serving a tool `fixed-tool-limit`'s.
                const text = cut.receiver !== undefined && file.isText(cut.receiver);
                if (cut.bound.source === 'field' || text || file.servedTool(cut.node) !== undefined) {
                    continue;
                }
                const what = cut.receiver ? `a \`${file.printType(cut.receiver)}\`` : 'an iterable';
                const bound =
                    cut.bound.source === 'literal' ? 'a literal bound' : `a constant bound, \`${cut.bound.text}\` (${cut.bound.value})`;
                file.report(cut.node, `\`${cut.text}\` cuts ${what} at ${bound}`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def shown(rows: list[str]) -> list[str]:
                            """Return the rows a report shows."""
                            return rows[:200]
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def shown(rows: list[str], saved: str) -> str:
                            """Return the report: every row, saved whole where the report points."""
                            Path(saved).write_text("\\n".join(rows))
                            return f"{len(rows)} rows, in {saved}"
                    `,
                },
                {
                    code: python`
                        from typing import ClassVar

                        from lup.types import Model


                        class Report(Model):
                            """A run's report."""

                            shown: ClassVar[int] = 200
                            rows: list[str]

                            def page(self) -> list[str]:
                                """Return the rows the report shows."""
                                return self.rows[: self.shown]
                    `,
                    rewritten: python`
                        from pathlib import Path

                        from lup.types import Model


                        class Report(Model):
                            """A run's report."""

                            rows: list[str]

                            def page(self, saved: str) -> str:
                                """Return the report: every row, saved whole where the report points."""
                                Path(saved).write_text("\\n".join(self.rows))
                                return f"{len(self.rows)} rows, in {saved}"
                    `,
                },
            ],
            passes: [
                python`
                    def body(rows: list[str]) -> list[str]:
                        """Return the rows after the header."""
                        return rows[1:]
                `,
                python`
                    def shown(rows: list[str], limit: int = 200) -> list[str]:
                        """Return the first \`limit\` rows: as many as the caller asks for."""
                        return rows[:limit]
                `,
            ],
        },
    },

    'fixed-tool-limit': {
        mistake:
            "A tool that stops its answer at a bound its caller can't set hands the agent part of what it asked for, " +
            'with no way to reach the rest.',
        steer:
            "Make the bound a field of the tool's input, defaulting to the value it has, and say in the answer when it " +
            'stopped short and how to reach the rest: a larger limit, or a narrower query. Where a format or an API ' +
            'forces the limit, keep it with an `ignore` that says so.',
        check(file) {
            const said = {
                literal: 'a literal',
                constant: 'a constant',
                field: 'a field of what the tool is bound to',
            };
            // A cut of text is `string-slice`'s.
            const cuts = file.cuts().filter((cut) => cut.receiver === undefined || !file.isText(cut.receiver));
            const capped = [
                ...cuts.map((cut) => ({ node: cut.node, bound: cut.bound, what: `\`${cut.text}\` stops at` })),
                ...file.limitsGiven().map((given) => ({ node: given.node, bound: given.bound, what: `\`${given.name}\` is given` })),
            ];
            for (const { node, bound, what } of capped) {
                const tool = file.servedTool(node);
                if (tool !== undefined) {
                    file.report(node, `${what} \`${bound.text}\`, ${said[bound.source]}, for the tool \`${tool}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pydantic import Field

                        import lup
                        from lup.types import Model


                        class Query(Model):
                            """A search of the notes."""

                            words: str = Field(description="The words a note holds.")


                        class Notes(Model):
                            """Notes an agent searches."""

                            notes: list[str]
                            shown: int = 50

                            @lup.tool
                            async def find_notes(self, query: Query) -> str:
                                """Find the notes holding some words."""
                                found = [note for note in self.notes if query.words in note]
                                return "\\n".join(found[: self.shown])
                    `,
                    rewritten: python`
                        from pydantic import Field, PositiveInt

                        import lup
                        from lup.types import Model


                        class Query(Model):
                            """A search of the notes."""

                            words: str = Field(description="The words a note holds.")
                            limit: PositiveInt = Field(default=50, description="How many notes to list at most.")


                        class Notes(Model):
                            """Notes an agent searches."""

                            notes: list[str]

                            @lup.tool
                            async def find_notes(self, query: Query) -> str:
                                """Find the notes holding some words."""
                                found = [note for note in self.notes if query.words in note]
                                shown = found[: query.limit]
                                more = len(found) - len(shown)
                                said = [f"{more} more match: a larger \`limit\` lists them."] if more else []
                                return "\\n".join([*shown, *said])
                    `,
                },
                {
                    code: python`
                        from pydantic import Field

                        import lup
                        from lup.programs import run
                        from lup.types import Model


                        class Query(Model):
                            """A search of the repository's issues."""

                            words: str = Field(description="What to search for, in GitHub's search syntax.")


                        @lup.tool
                        async def find_issues(query: Query) -> str:
                            """Search the repository's issues."""
                            return run("gh", "search", "issues", "--limit=100", "--", query.words).text()
                    `,
                    rewritten: python`
                        from pydantic import Field, PositiveInt

                        import lup
                        from lup.programs import run
                        from lup.types import Model


                        class Query(Model):
                            """A search of the repository's issues."""

                            words: str = Field(description="What to search for, in GitHub's search syntax.")
                            limit: PositiveInt = Field(default=100, description="How many issues to list at most.")


                        @lup.tool
                        async def find_issues(query: Query) -> str:
                            """Search the repository's issues."""
                            ran = run("gh", "search", "issues", f"--limit={query.limit}", "--", query.words)
                            found = ran.text().splitlines()
                            more = ["More may match: a larger \`limit\` lists them."] if len(found) == query.limit else []
                            return "\\n".join([*found, *more])
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class Notes(Model):
                        """Notes, read a page at a time."""

                        notes: list[str]
                        shown: int = 50

                        def page(self) -> list[str]:
                            """Return the first page of notes."""
                            return self.notes[: self.shown]
                `,
                python`
                    from pydantic import Field, PositiveInt

                    import lup
                    from lup.types import Model


                    class Query(Model):
                        """A search of the notes."""

                        words: str = Field(description="The words a note holds.")
                        limit: PositiveInt = Field(default=50, description="How many notes to list at most.")


                    def search(notes: list[str], words: str, limit: int) -> list[str]:
                        """Return the first \`limit\` notes holding \`words\`."""
                        return [note for note in notes if words in note][:limit]


                    class Notes(Model):
                        """Notes an agent searches."""

                        notes: list[str]

                        @lup.tool
                        async def find_notes(self, query: Query) -> str:
                            """Find the notes holding some words, \`limit\` at most."""
                            return "\\n".join(search(self.notes, query.words, query.limit))
                `,
            ],
        },
    },

    'historical-voice': {
        mistake: 'A comment or docstring telling how the code came to be means something only against a version the reader never sees.',
        steer:
            'Say what is: "the call waits", not "the call now waits"; "the parser", not "the new parser". ' +
            'History belongs in the commit message.',
        check(file) {
            // Each word is read beside its neighbours in its phrase, since most of them also
            // name a moment or a thing of the running code: "for now", "a new reply" and
            // "fixed for its life" tell nothing of the code's past.
            const always = ['previously', 'formerly', 'anymore'];
            // `now` names a moment of the running code after these, or before `that` or `on`.
            const moment = ['for', 'right', 'from', 'just', 'by', 'until'];
            // `new` and `newly` set a thing against what it replaced after these; after
            // `a` they name an instance the code makes.
            const against = ['the', 'this', 'these', 'our'];
            // `fixed` tells of a repair after these, or before what was repaired.
            const done = ['was', 'were', 'been', 'is', 'are', 'has', 'have', 'had', 'got', 'gets'];
            const repaired = ['a', 'an', 'the', 'this', 'that', 'these', 'those', 'its', 'their', 'bug', 'bugs'];
            for (const prose of file.prose()) {
                for (const phrase of file.phrases(prose)) {
                    phrase.forEach((word, index) => {
                        const before = phrase[index - 1]?.text ?? '';
                        const after = phrase[index + 1]?.text ?? '';
                        const said =
                            (always.includes(word.text) && word.text) ||
                            (word.text === 'no' && after === 'longer' && 'no longer') ||
                            (word.text === 'now' && !moment.includes(before) && !['that', 'on'].includes(after) && 'now') ||
                            (['new', 'newly'].includes(word.text) && against.includes(before) && word.text) ||
                            (word.text === 'fixed' && (done.includes(before) || repaired.includes(after)) && 'fixed');
                        if (said) {
                            file.report(word.range, `"${said}" tells how the code came to be`);
                        }
                    });
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import time


                        def pause(seconds: float) -> None:
                            """Pause before the next try, which now waits a second at least."""
                            time.sleep(max(seconds, 1))
                    `,
                    rewritten: python`
                        import time


                        def pause(seconds: float) -> None:
                            """Pause before the next try, for a second at least."""
                            time.sleep(max(seconds, 1))
                    `,
                },
                {
                    code: python`
                        def field(record: dict[str, str], name: str) -> str | None:
                            """Read one field of a record: a missing one no longer raises."""
                            return record.get(name)
                    `,
                    rewritten: python`
                        def field(record: dict[str, str], name: str) -> str | None:
                            """Read one field of a record: none where it's missing."""
                            return record.get(name)
                    `,
                },
                {
                    code: python`
                        def width(text: str) -> int:
                            """Count the columns a line takes, with the new parser."""
                            return len(text.expandtabs())
                    `,
                    rewritten: python`
                        def width(text: str) -> int:
                            """Count the columns a line takes, tabs expanded."""
                            return len(text.expandtabs())
                    `,
                },
                {
                    code: python`
                        def joined(lines: list[str]) -> str:
                            """Join lines, which fixed the trailing newline."""
                            return "\\n".join(lines)
                    `,
                    rewritten: python`
                        def joined(lines: list[str]) -> str:
                            """Join lines, with no newline after the last."""
                            return "\\n".join(lines)
                    `,
                },
            ],
            passes: [
                python`
                    def described(old: str, replacement: str) -> str:
                        """Describe an edit: its \`old_string\` and \`new_string\`, which "the new text" names."""
                        return f"{old} -> {replacement}"
                `,
                python`
                    def reply(draft: str) -> str:
                        """Send what's drafted as a new reply, from now on to every agent; for now, the draft is kept as written."""
                        return draft
                `,
                python`
                    def tools(names: list[str]) -> list[str]:
                        """List a thread's tools, fixed for its life: a fixed set, since right now the lock is held, and now that it is, nothing changes them."""
                        return sorted(names)
                `,
                python`
                    def lifted(held: list[str]) -> list[str]:
                        """Lift a hold, returning the findings it kept back until now."""
                        return held
                `,
            ],
        },
    },

    // Docstrings and comments (`docs/conventions.md`, *Docstrings and comments*).

    'docstring-code': {
        mistake: "reStructuredText's double backticks and Sphinx roles are a second way to mark code, beside Markdown's.",
        steer: 'Mark inline code with single backticks: `name`, `print`.',
        check(file) {
            for (const docstring of file.docstrings()) {
                for (const mark of file.codeMarks(docstring)) {
                    file.report(
                        mark.range,
                        mark.written === '``' ? 'this marks code with double backticks' : `\`${mark.written}\` is a Sphinx role`
                    );
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def greet(name: str) -> str:
                            """Return a greeting for \`\`name\`\`; see :func:\`print\`."""
                            return f"hello {name}"
                    `,
                    rewritten: python`
                        def greet(name: str) -> str:
                            """Return a greeting for \`name\`; see \`print\`."""
                            return f"hello {name}"
                    `,
                },
            ],
            passes: [
                python`
                    def greet(name: str) -> str:
                        """Return a greeting. Usage: \`greet("Ada")\`."""
                        return f"hello {name}"
                `,
            ],
        },
    },

    // Imports and boundaries (`docs/conventions.md`, *Imports and boundaries*).

    'runtime-mention': {
        mistake:
            'A runtime named outside its adapter builds a feature for one runtime above the seam, where the others ' +
            'quietly lack it.',
        steer:
            "Speak in lup's own words and capabilities (`runtime.inside()`); the runtime's spelling, and the " +
            'evidence behind a capability, belong in its adapter.',
        check(file) {
            for (const mention of file.mentionsOf(['claude', 'codex'])) {
                if (`.${file.moduleName}.`.includes(`.adapters.${mention.name}.`)) {
                    continue;
                }
                file.report(
                    mention.range,
                    mention.kind === 'name'
                        ? `\`${file.text(mention.range)}\` holds a runtime's name, \`${mention.name}\``
                        : `this ${mention.kind} names a runtime, \`${mention.name}\``
                );
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def asks_first(runtime: str) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return runtime == "claude"
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Runtime(ABC):
                            """One agent runtime, as lup sees it."""

                            @abstractmethod
                            def asks_before(self) -> bool:
                                """Say whether the runtime can ask the operator before a call runs."""


                        def asks_first(runtime: Runtime) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return runtime.asks_before()
                    `,
                },
            ],
            passes: [
                python`
                    def settings_home(name: str) -> str:
                        """Return where a runtime keeps its settings, by the name its adapter gives."""
                        return f".{name}"
                `,
            ],
        },
    },

    // Collections and loops (`docs/conventions.md`, *Collections and loops*), continued.

    'collection-loop': {
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

    // Constants (`docs/conventions.md`, *Constants*).

    'constant-home': {
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

    // Interfaces (`docs/conventions.md`, *Interfaces*), continued.

    'interface-shape': {
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
            ],
        },
    },

    // Dispatch (`docs/conventions.md`, *Dispatch*), continued.

    'own-model-dispatch': {
        mistake:
            'Choosing by which implementation of one of our ABCs you hold bypasses the seam the ABC is, and ' +
            'leaves the others to drift.',
        steer: 'Add a method to the ABC, which each implementation answers, and call it.',
        check(file) {
            for (const named of [...file.isinstanceClasses(), ...file.classPatterns()]) {
                const [implemented] = named.implements;
                if (implemented) {
                    file.report(named.node, `\`${file.text(named.node)}\` implements our ABC \`${implemented}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from abc import ABC, abstractmethod


                        class Runtime(ABC):
                            """An agent runtime."""

                            @abstractmethod
                            def name(self) -> str:
                                """Return the runtime's name."""


                        class Local(Runtime):
                            """A runtime on this machine."""

                            def name(self) -> str:
                                """Return the runtime's name."""
                                return "local"


                        def asks_first(runtime: Runtime) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return isinstance(runtime, Local)
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Runtime(ABC):
                            """An agent runtime."""

                            @abstractmethod
                            def name(self) -> str:
                                """Return the runtime's name."""

                            @abstractmethod
                            def asks_before(self) -> bool:
                                """Say whether the runtime asks before a call runs."""


                        class Local(Runtime):
                            """A runtime on this machine."""

                            def name(self) -> str:
                                """Return the runtime's name."""
                                return "local"

                            def asks_before(self) -> bool:
                                """Say whether the runtime asks before a call runs: it does."""
                                return True


                        def asks_first(runtime: Runtime) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return runtime.asks_before()
                    `,
                },
            ],
            passes: [
                python`
                    from abc import ABC, abstractmethod


                    class Runtime(ABC):
                        """An agent runtime."""

                        @abstractmethod
                        def name(self) -> str:
                            """Return the runtime's name."""


                    def named(value: Runtime | str) -> str:
                        """Return a runtime's name, or a name given as it is."""
                        return value.name() if isinstance(value, Runtime) else value
                `,
            ],
        },
    },

    // Errors (`docs/conventions.md`, *Errors*), continued.

    'error-root': {
        mistake: 'An exception outside its package\'s root error escapes a caller catching everything the package raises.',
        steer:
            "Derive it from the package's root error, named for the package (`LupDevError` in `lup_dev`), or from " +
            'an error below it.',
        check(file) {
            const root = file.packageRootError;
            for (const declared of file.classes()) {
                const name = declared.node.d.name.d.value;
                if (!declared.ancestors.includes('builtins.BaseException') || name === root) {
                    continue;
                }
                const rooted = declared.ancestors.some(
                    (ancestor) => ancestor.startsWith(`${file.packageName}.`) && ancestor.endsWith(`.${root}`)
                );
                if (!rooted) {
                    file.report(declared.node.d.name, `\`${name}\` doesn't descend from \`${root}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        class ParseError(ValueError):
                            """The text isn't in the format."""
                    `,
                    rewritten: python`
                        class ExampleError(Exception):
                            """Anything this package raises."""


                        class ParseError(ExampleError):
                            """The text isn't in the format."""
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class ErrorReport(Model):
                        """What went wrong, as a person reads it."""

                        summary: str
                `,
            ],
        },
    },

    'error-text': {
        mistake: "Deciding on an exception's message breaks quietly when the message is reworded.",
        steer: "Decide on the exception's type, or on its structured fields (`errno`, `status_code`).",
        check(file) {
            for (const used of file.exceptionTexts()) {
                file.report(used.node, `\`${used.text}\` decides on an exception's message`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pathlib import Path


                        def removed(path: str) -> bool:
                            """Remove a file, saying whether it was there."""
                            try:
                                Path(path).unlink()
                            except OSError as error:
                                if "No such file" in str(error):
                                    return False
                                raise
                            return True
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def removed(path: str) -> bool:
                            """Remove a file, saying whether it was there."""
                            try:
                                Path(path).unlink()
                            except FileNotFoundError:
                                return False
                            return True
                    `,
                },
            ],
            passes: [
                python`
                    def described(error: Exception) -> str:
                        """Describe an error for a person to read."""
                        return f"failed: {error}"
                `,
            ],
        },
    },

    // Names (`docs/conventions.md`, *Names*), continued.

    'private-name': {
        mistake: 'A leading underscore is a second kind of visibility, beside public, that a reviewer has to second-guess.',
        steer:
            'Make the name public, or nest a helper inside its only caller; inline a wrapper around one call. An ' +
            'unused parameter keeps its underscore.',
        check(file) {
            if (file.isPrivateModule) {
                file.report({ start: 0, length: 0 }, "the module's own name is private");
            }
            for (const binding of file.privateNames()) {
                file.report(binding.node, `\`${binding.name}\` is private`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def _cleaned(text: str) -> str:
                            return text.strip()


                        def words(text: str) -> list[str]:
                            """Split text into its words."""
                            return _cleaned(text).split()
                    `,
                    rewritten: python`
                        def words(text: str) -> list[str]:
                            """Split text into its words."""
                            return text.strip().split()
                    `,
                },
            ],
            passes: [
                python`
                    def count(values: list[int], _reason: str = "") -> int:
                        """Count the values; the reason is for the caller's records."""
                        return sum(1 for _ in values)
                `,
            ],
        },
    },
} satisfies Catalog;
