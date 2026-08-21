"""What the rendered image must keep true, pinned where a change is visible.

Every assertion here corresponds to something that was measured against a real
container rather than reasoned about, and several correspond to a defect the
first draft shipped. A test that only restated the declaration would pass on
the broken version too.
"""

from pathlib import Path

from lup.harness.image import Docker, Image, Podman, detected_client
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
    assert "ENV PATH=/opt/bun/bin:$PATH" in Image().dockerfile(Manifest())


def test_the_registry_root_is_reachable_by_the_user_the_session_runs_as() -> None:
    """The build installs as root and the session runs as the host's uid.

    Root's home is mode 750, so a global toolchain installed there is
    installed into a directory the session cannot enter -- and the failure is
    reported by whatever tried to run the tool, never by the layer that
    misplaced it. Outside any home directory, and handed over with the rest.
    """
    rendered = Image().dockerfile(Manifest())
    assert "/root/.bun" not in rendered
    assert "chown -R $UID:$GID /opt/lup/venv /opt/bun" in rendered


def test_the_registry_root_is_declared_before_anything_installs_into_it() -> None:
    """An install layer above the variable installs somewhere else entirely."""
    rendered = Image().dockerfile(
        Manifest(
            requirements=[
                requirement("js", [Package(name="typescript", manager="bun")])
            ]
        )
    )
    assert rendered.index("ENV BUN_INSTALL=/opt/bun") < rendered.index("bun add -g")


def test_the_package_manager_that_installs_is_the_one_with_a_cache() -> None:
    """A cache volume for a tool the image never installs is a mount for nothing.

    Both registries here are `bun` and `uv`; the baseline carries `nodejs` and
    not `npm`, so nothing in this image has ever run npm. Caching for it while
    the manager that does the installing re-fetched every package was the
    accretion this declaration now has to answer for.
    """
    cached = {cache.variable for cache in Image().caches}
    assert "BUN_INSTALL_CACHE_DIR" in cached
    assert "npm_config_cache" not in cached


def test_every_cache_volume_says_what_needed_it() -> None:
    """The counter-pressure, applied first to the declaration that carries it."""
    assert all(cache.because for cache in Image().caches)


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


def test_a_session_mounts_the_checkout_at_its_own_absolute_path() -> None:
    """A linked worktree's `.git` is a file holding an absolute `gitdir:` pointer.

    Mounted anywhere else, the tree inside the container is a checkout
    pointing at a path that does not exist, and every git command fails
    naming the repository rather than the mount.
    """
    started = Image().session_arguments(
        tag="lup-agent:x",
        checkout=Path("/home/u/repo"),
        uid=1000,
        gid=1000,
        writable={Path("/home/u/repo"): "/home/u/repo"},
        read_only={},
        state_volume="lup-cfg-x",
        config_home_env="CLAUDE_CONFIG_DIR",
    )
    assert "-v" in started
    assert "/home/u/repo:/home/u/repo:rw" in started
    assert started[-1] == "lup-agent:x"


def test_the_config_home_is_container_private_and_carries_across_launches() -> None:
    """A clean config home discards the workspace's declared permissions.

    Measured: an unseeded home reports `Ignoring N permissions.allow entries`
    and continues, so the policy is off with nothing having failed. The
    volume is what stops that happening on every launch.
    """
    image = Image()
    started = image.session_arguments(
        tag="t",
        checkout=Path("/c"),
        uid=1,
        gid=1,
        writable={},
        read_only={},
        state_volume="lup-cfg-x",
        config_home_env="CODEX_HOME",
    )
    assert f"lup-cfg-x:{image.config_home}" in started
    # The variable is the runtime's own word, taken from its login declaration
    # rather than spelled here: Codex reads a different one, and a container
    # started with Claude's would leave it pointed at the host's home.
    assert f"CODEX_HOME={image.config_home}" in started


def test_the_credential_crosses_as_one_read_only_file_outside_the_config_home() -> None:
    """The config home holds every project's session state; the login is one file.

    Offered beside the config home rather than over it. Mounted at the path
    the CLI keeps a login, read-only, it looked right and was not: that file
    is written back both when a sign-in completes and when an expiring token
    renews, so the mount refused both, and it shadowed the config volume's
    own copy so a login made inside vanished at the next launch.
    """
    image = Image()
    started = image.session_arguments(
        tag="t",
        checkout=Path("/c"),
        uid=1,
        gid=1,
        writable={},
        read_only={},
        state_volume="v",
        config_home_env="CLAUDE_CONFIG_DIR",
        credential=Path("/home/u/.claude/.credentials.json"),
    )
    assert f"/home/u/.claude/.credentials.json:{image.credential_seed}:ro" in started
    assert image.credential_seed.startswith(f"{image.config_home}/") is False
    # The filename is the runtime's own word, and one image starts every
    # runtime the harness declares, so the entrypoint is told rather than
    # assuming Claude Code's.
    assert "LUP_CREDENTIAL_NAME=.credentials.json" in started


def test_the_entrypoint_seeds_a_login_only_into_a_config_home_without_one() -> None:
    """Both directions have to be safe, and only this order makes them so.

    Copying unconditionally would overwrite a login made inside with the
    host's at every launch, which is the feature undone. Writing back to the
    host's file would let a contained agent rotate the credential every host
    session depends on. Copying once, into an empty home, is neither.
    """
    entrypoint = Image().dockerfile(Manifest())
    assert '[ ! -f "$config/$LUP_CREDENTIAL_NAME" ]' in entrypoint
    assert 'cp "$seed" "$config/$LUP_CREDENTIAL_NAME"' in entrypoint


def test_the_entrypoint_reads_the_config_home_the_image_baked() -> None:
    """One image starts every runtime, and they disagree about the variable.

    It read `CLAUDE_CONFIG_DIR` with a fallback to `$HOME/.claude`, so a
    Codex session -- started with `CODEX_HOME` pointed at the same mount --
    seeded its trust into a directory nothing was reading.
    """
    entrypoint = Image().dockerfile(Manifest())
    assert f"config={Image().config_home}" in entrypoint
    assert "CLAUDE_CONFIG_DIR:-" not in entrypoint


def test_an_engine_is_identified_by_what_it_reports_not_by_its_name() -> None:
    """The `podman-docker` package installs a `docker` that is really podman.

    Trusting the path's spelling would hand it Docker's arguments and lose
    the identity mapping, so detection asks the client who it is.
    """

    found = detected_client(
        ("docker",),
        lambda _name: "podman version 6.1.0",
        lambda _name: '[{"Name":"Podman Engine"}]',
    )
    assert found is not None
    assert found.engine() == Podman(binary="docker")
    assert found.engine().identity_arguments(1000, 1000)[-1] == "--userns=keep-id"


def test_a_real_docker_client_is_not_mistaken_for_podman() -> None:
    """The other direction of the same question, against Docker's own string."""
    found = detected_client(
        ("docker",),
        lambda _name: "Docker version 29.7.2",
        lambda _name: '[{"Name":"Engine"},{"Name":"containerd"}]',
    )
    assert found is not None
    assert found.engine() == Docker(binary="docker")
    assert found.drives_its_server()
