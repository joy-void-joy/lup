// One library per job: two libraries for a job are two ways of doing it, which sessions split between.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const libraries = {
    subprocess: {
        category: 'design',
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
        category: 'design',
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
        category: 'design',
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
        category: 'design',
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
        category: 'design',
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
        category: 'design',
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
        category: 'design',
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
        category: 'design',
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
} satisfies Catalog;
