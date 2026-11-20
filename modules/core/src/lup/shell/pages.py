"""The dashboard as the machine serves it: whether and where (`Dashboarding`), and its page, built in a container (`Pages`).

The page isn't in git, nor are its types, which are generated from what the
core says it sends (`lup.environment.shell.server.described`): the machine
builds it from the source of the commit it runs. Building it runs
`pnpm install`, which runs packages' own code, so it runs behind a
container's walls (`Containers`), on Arch Linux's image with node and pnpm from
the archive every project's image comes from: the source copied into a
directory of this part's, mounted with pnpm's store and the directory the page
is written to, and nothing else of the machine's. A page is kept under a digest
of everything it's built from, its source's files, what the core sends, the
image and the steps, so it's built once for each, and a commit that leaves the
page alone serves the page already built.
"""

import hashlib
import shlex
import shutil
from pathlib import Path

from pydantic import Field

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine
from lup.doors.parts import Data, Finished, Part
from lup.hosting.containers import Bind, Containers, Image, Once, Spec
from lup.hosting.projects import Base
from lup.hosting.trees import emptied
from lup.running.plan import Name
from lup.types import Model


class Dashboarding(Model):
    """Whether the machine serves the dashboard, and on which of localhost's ports."""

    serve: bool = True
    port: int = 8770
    """Beside the second lup's dashboard, which holds 8766 and 8767."""


class PageSource(Model):
    """A page to build: its source, and what the core says it sends."""

    source: Path
    """The page's source, by its absolute path: its `package.json`, lockfile,
    configuration and code, as git holds them."""
    described: str
    """What the page reads from the core, as JSON Schema, which its types are
    generated from (`page/package.json`'s `generated`)."""


class BuiltPage(Model):
    """A page built: the directory holding its `index.html` and its assets."""

    path: Path


class Inside(Model):
    """Where a build's directories are in its container."""

    page: Path = Path("/var/lup/page")
    """The source, copied, which the build installs into and generates in."""
    cache: Path = Path("/var/lup/cache")
    """pnpm's store and home, kept from one build to the next."""
    out: Path = Path("/var/lup/out")
    """Where the page is written."""


class Making(Model):
    """Everything a page is built from, whose digest names it."""

    definition: str
    steps: list[list[str]]
    described: str
    files: dict[str, str]
    """Each of the source's files, by its path within it, as the digest of its
    bytes."""


class Pages(Part, machine=True, shared=True):
    """The machine's part building the dashboard's page in a container, once for each source."""

    pages: Data
    """Each page built, a directory under its digest, and each build's log."""
    cache: Data
    """pnpm's store of packages and its home, kept from one build to the next."""
    base: Base = Field(default_factory=lambda: Base(packages=["nodejs", "pnpm"]))
    """The image building it: Arch Linux's, pinned, with node and pnpm."""
    inside: Inside = Field(default_factory=Inside)
    project: Name = "dashboard"
    """What the image and its containers are labelled for: the dashboard,
    no project's."""

    def steps(self) -> list[list[str]]:
        """Return what a build runs, each in a container of its own: pnpm installing what the lockfile holds, the types generated, and vite writing the page."""
        return [
            [
                "pnpm",
                "install",
                "--frozen-lockfile",
                f"--store-dir={self.inside.cache / 'store'}",
            ],
            ["pnpm", "run", "--silent", "generated"],
            [
                "pnpm",
                "exec",
                "vite",
                "build",
                f"--outDir={self.inside.out}",
                "--emptyOutDir",
            ],
        ]

    def image(self) -> Image:
        """Return the image building a page."""
        return Image(
            base=self.base.image,
            definition=self.base.definition(),
            project=self.project,
        )

    def digest(self, asked: PageSource) -> str:
        """Return the digest of everything a page is built from: its source's files, what the core sends, the image and the steps."""
        files = sorted(each for each in asked.source.rglob("*") if each.is_file())
        making = Making(
            definition=self.base.definition(),
            steps=self.steps(),
            described=asked.described,
            files={
                each.relative_to(asked.source).as_posix(): hashlib.sha256(
                    each.read_bytes()
                ).hexdigest()
                for each in files
            },
        )
        return hashlib.sha256(making.model_dump_json().encode()).hexdigest()

    @lup.service
    async def page(self, asked: PageSource, by: Machine) -> BuiltPage:
        """Build the page `asked` names where it isn't built yet, and say where it is.

        Each step runs in a container of its own, what it prints kept in the
        build's log. Raise `RefusedError` where its source isn't an absolute
        path or holds no `package.json`, where a step fails, saying which and where its log is,
        or where the build writes no `index.html`; `ContainerError` where podman
        can't build the image or run a step.
        """
        del by
        if not asked.source.is_absolute():
            message = (
                f"a page is built from its source's absolute path, not {asked.source}"
            )
            raise RefusedError(message)
        if not (asked.source / "package.json").is_file():
            message = f"{asked.source} holds no page to build: it has no package.json"
            raise RefusedError(message)
        digest = self.digest(asked)
        built = self.pages.path / digest
        if (built / "index.html").is_file():
            return BuiltPage(path=built)
        image = self.image()
        await Containers.built(image)
        work = emptied(self.pages.path / f"{digest}.work")
        out = emptied(self.pages.path / f"{digest}.partial")
        shutil.copytree(asked.source, work, symlinks=True, dirs_exist_ok=True)
        (work / "schema.json").write_text(asked.described)
        log = self.pages.path / f"{digest}.log"
        log.write_bytes(b"")
        binds = [
            Bind(source=work, target=self.inside.page, read_only=False),
            Bind(
                source=self.cache.path.resolve(),
                target=self.inside.cache,
                read_only=False,
            ),
            Bind(source=out, target=self.inside.out, read_only=False),
        ]
        try:
            for step in self.steps():
                finished = await Containers.ran(
                    Once(
                        spec=Spec(
                            name=f"lup-page-{digest}",
                            image=image,
                            command=step,
                            workdir=self.inside.page,
                            binds=binds,
                            env={"HOME": str(self.inside.cache / "home")},
                        )
                    )
                )
                logged(log, step, finished)
                if finished.status != 0:
                    message = (
                        f"the dashboard's page didn't build: `{shlex.join(step)}` "
                        f"ended with status {finished.status}, what it said in {log}"
                    )
                    raise RefusedError(message)
            if not (out / "index.html").is_file():
                message = f"the dashboard's page built without an index.html: what the build said is in {log}"
                raise RefusedError(message)
            out.rename(built)
        finally:
            shutil.rmtree(work)
            if out.exists():
                shutil.rmtree(out)
        return BuiltPage(path=built)


def logged(log: Path, step: list[str], finished: Finished) -> None:
    """Append to `log` the step run and everything it printed and said, whole."""
    with log.open("ab") as appending:
        appending.write(f"$ {shlex.join(step)}\n".encode())
        appending.write(finished.output)
        appending.write(finished.error)
        appending.write(f"[status {finished.status}]\n".encode())
