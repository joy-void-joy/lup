"""What the rendered image must keep true, pinned where a change is visible.

Every assertion here corresponds to something that was measured against a real
container rather than reasoned about, and several correspond to a defect the
first draft shipped. A test that only restated the declaration would pass on
the broken version too.
"""

from pathlib import Path

import sh

from lup.harness.image import Docker, Image, Podman, detected_engine
from lup.harness.requirements import Manifest, Package, Requirement, Run
from lup.harness.requirements import LostCapability


def requirement(capability: str, install: list[Package]) -> Requirement:
    """An image-side requirement carrying packages, with the rest inert."""
    return Requirement(
        capability=capability,
        purpose="testing",
        where="image",
        exercise=Run(command=["true"]),
        absence=LostCapability(capability=capability),
        install=install,
    )


def test_nothing_in_the_rendered_image_fetches_code_it_does_not_verify() -> None:
    """The property the base image was chosen for, and the one easiest to lose.

    A single `curl | bash` puts an unreviewed remote script inside the build
    of the thing that is supposed to *be* the boundary. The first draft of
    this declaration had three.
    """
    rendered = Image().dockerfile(
        Manifest(
            requirements=[
                requirement("js", [Package(name="typescript", manager="bun")])
            ]
        )
    )
    assert "curl -" not in rendered and "| bash" not in rendered
    assert "| sh" not in rendered


def test_the_archive_is_pinned_before_anything_resolves_against_it() -> None:
    """A rolling distribution reproduces only if the snapshot precedes the install."""
    rendered = Image(snapshot="2026/01/02").dockerfile(Manifest())
    pin = rendered.index("archive.archlinux.org/repos/2026/01/02")
    assert pin < rendered.index("pacman -S --noconfirm --needed")


def test_a_registry_package_carries_its_pinned_version_into_the_install() -> None:
    """An unpinned registry name is a different build every time it is run."""
    rendered = Image().dockerfile(
        Manifest(
            requirements=[
                requirement(
                    "js", [Package(name="typescript", manager="bun", version="6.0.3")]
                )
            ]
        )
    )
    assert "bun add -g typescript@6.0.3" in rendered


def test_globally_installed_executables_are_reachable_by_directory() -> None:
    """Measured: linking the CLI by name left `tsc` installed and unreachable."""
    assert "ENV PATH=/root/.bun/bin:$PATH" in Image().dockerfile(Manifest())


def test_the_trust_seed_names_no_host_path() -> None:
    """A portable image cannot carry one machine's filesystem layout.

    Enumerating the sibling worktrees was tried and baked thirty-one paths in,
    several of which were not checkouts. The container's own working directory
    is the answer, and only the entrypoint can know it.
    """
    rendered = Image().dockerfile(Manifest())
    assert '"projects": {}' in rendered
    assert ".projects[$here]" in rendered


def test_a_script_package_still_renders_when_an_adopter_declares_one() -> None:
    """The hatch is refused by rule, not removed -- so it has to still work."""
    rendered = Image().dockerfile(
        Manifest(
            requirements=[
                requirement(
                    "odd",
                    [Package(name="odd", manager="script", command="make install")],
                )
            ]
        )
    )
    assert "RUN make install" in rendered


def test_a_script_package_must_say_how_it_installs() -> None:
    """Silently installing nothing produces an error naming the wrong thing."""
    try:
        Package(name="odd", manager="script")
    except ValueError as refusal:
        assert "names no command" in str(refusal)
    else:
        raise AssertionError("a script package with no command was accepted")


def test_the_registry_managers_are_installed_before_they_are_used() -> None:
    """A package declared for `uv` or `bun` cannot install if its tool is absent."""
    baseline = Image().baseline
    assert "uv" in baseline and "nodejs" in baseline


def test_docker_is_never_handed_podmans_identity_flag() -> None:
    """Measured: Docker 29.7.2 refuses `--userns=keep-id` outright.

    It exits with `--userns: invalid USER mode` before the daemon is reached,
    so a launcher that spelled podman's requirement unconditionally could not
    start a session under Docker at all. The first draft of `run_arguments`
    did exactly that.
    """
    started = Image().run_arguments(Path("/checkout"), 1000, 1000, Docker())
    assert "--userns=keep-id" not in started
    assert started[:2] == ["--user", "1000:1000"]


def test_podman_keeps_the_host_id_rather_than_remapping_it() -> None:
    """Without this, a bind mount lands owned by a subuid the host cannot read.

    Podman maps the invoking user into its subuid range by default, so files
    the container writes into the mounted checkout come back owned by
    something like 100999 rather than by the operator.
    """
    started = Image().run_arguments(Path("/checkout"), 1000, 1000, Podman())
    assert "--userns=keep-id" in started


def test_an_engine_is_identified_by_what_it_reports_not_by_its_name() -> None:
    """The `podman-docker` package installs a `docker` that is really podman.

    Trusting the path's spelling would hand it Docker's arguments and lose
    the identity mapping, so detection asks the client who it is.
    """

    def shim(_name: str) -> object:
        """A client at the name `docker` that reports itself as podman."""

        def answer(_flag: str) -> str:
            return "podman version 6.1.0"

        return answer

    original = sh.Command
    sh.Command = shim
    try:
        found = detected_engine(("docker",))
    finally:
        sh.Command = original
    assert found is not None
    assert found == Podman(binary="docker")
    assert found.identity_arguments(1000, 1000)[-1] == "--userns=keep-id"
