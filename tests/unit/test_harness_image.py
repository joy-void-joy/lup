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


def test_declared_tooling_reaches_the_layer_its_manager_installs() -> None:
    """The third door a package gets into an image through.

    `baseline` is the library's answer to what a shell needs, and a
    requirement is what a capability asked for and something exercises.
    Neither has room for a program this project's own work shells out to, and
    a declaration that did not reach the layer would be a field that reads
    like a decision and installs nothing.
    """
    rendered = Image(
        tooling=[
            Package(name="poppler"),
            Package(name="prettier", manager="bun", version="3.4.2"),
        ]
    ).dockerfile(Manifest())

    assert "poppler" in rendered
    assert "bun add -g prettier@3.4.2" in rendered


def test_declared_tooling_is_the_images_alone_and_not_the_manifests() -> None:
    """The two audiences a package list has, kept apart.

    `Manifest.packages` feeds an image *and* answers for what a machine is
    expected to have; merging the two produced `apt-get install -y uv` against
    a runner that cannot satisfy it. Tooling is the image's alone, so nothing
    reading the manifest learns a new prerequisite from it.
    """
    manifest = Manifest()

    assert Package(name="poppler") in Image(tooling=[Package(name="poppler")]).packages(
        manifest
    )
    assert Package(name="poppler") not in manifest.packages()


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
    assert "chown -R $UID:$GID /opt/bun" in rendered


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
    """The hatch is refused by rule, not removed -- so it has to still work.

    The rendered layer names the digest beside the line, because that comment
    is the only place a reader of the Dockerfile can see what the install was
    checked against: the line itself does the checking somewhere in the middle
    of a shell pipeline nobody reads to the end.
    """
    rendered = Image().dockerfile(
        Manifest(
            requirements=[
                requirement(
                    "odd",
                    [
                        Package(
                            name="odd",
                            manager="script",
                            command="make install",
                            digest="ab" * 32,
                        )
                    ],
                )
            ]
        )
    )
    assert "RUN make install" in rendered
    assert "ab" * 32 in rendered


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


def test_the_project_environment_is_keyed_per_project_rather_than_per_machine() -> None:
    """An absolute value is one environment for every project mounted here.

    Measured on uv 0.12.7: `uv sync` is exact by default, so syncing a second
    project into a shared environment uninstalls the first and its
    dependencies. Relative is what makes `uv` do the keying, and it has to
    reach the container as-is -- resolved to an absolute path on the way out
    would restore the collision while still reading as a fix.
    """
    image = Image()
    assert not Path(image.project_environment).is_absolute()
    assert image.environment()["UV_PROJECT_ENVIRONMENT"] == image.project_environment


def test_the_build_cannot_pre_create_a_project_relative_environment() -> None:
    """A path relative to each project root has no directory here to make.

    The caches and the registry root are absolute and stay; the environment
    leaving the `mkdir` is what forces the run to bind one instead, and a
    `mkdir .venv-contained` in a Dockerfile would silently make one directory
    in the build's working directory and satisfy nothing.
    """
    rendered = Image().dockerfile(Manifest())
    handed = [line for line in rendered.splitlines() if "chown -R" in line]
    assert handed, "the build hands its directories to the session's uid somewhere"
    assert Image().project_environment not in "\n".join(handed)
    assert "mkdir -p /opt/bun" in rendered


def test_each_mounted_project_gets_its_own_environment_directory() -> None:
    """One shared environment is the collision; one per root is the fix.

    Two roots, two private directories, each bound at the environment's name
    inside its own tree -- so a `uv sync` in either reaches only its own.
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
        environments={
            Path("/home/u/repo"): Path("/home/u/.cache/lup/environments/repo-aaaa"),
            Path("/home/u/other"): Path("/home/u/.cache/lup/environments/other-bbbb"),
        },
    )
    name = Image().project_environment
    assert (
        f"/home/u/.cache/lup/environments/repo-aaaa:/home/u/repo/{name}:rw" in started
    )
    assert (
        f"/home/u/.cache/lup/environments/other-bbbb:/home/u/other/{name}:rw" in started
    )


def test_an_environment_mount_is_emitted_after_the_bind_it_sits_inside() -> None:
    """The order a reader takes it in, though both engines sort by depth.

    Measured on podman 6.1.0: a nested mount emitted first still wins. Pinned
    anyway, because the day an engine applies the list in order is the day
    the environment silently becomes the host's `.venv` again -- and nothing
    else in a session would report it.
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
        environments={Path("/home/u/repo"): Path("/held")},
    )
    name = Image().project_environment
    assert started.index("/home/u/repo:/home/u/repo:rw") < started.index(
        f"/held:/home/u/repo/{name}:rw"
    )


def test_a_session_without_declared_environments_binds_none() -> None:
    """A probe and a one-off `run` pass none, and must still assemble.

    The variable is still baked -- it is an image fact -- so what must be
    absent is the mount, not the name.
    """
    started = Image().session_arguments(
        tag="lup-agent:x",
        checkout=Path("/home/u/repo"),
        uid=1000,
        gid=1000,
        writable={},
        read_only={},
        state_volume="lup-cfg-x",
        config_home_env="CLAUDE_CONFIG_DIR",
    )
    suffix = f"/{Image().project_environment}:rw"
    assert not [argument for argument in started if argument.endswith(suffix)]


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
        credential_renewable=".a > 1",
    )
    assert f"/home/u/.claude/.credentials.json:{image.credential_seed}:ro" in started
    assert image.credential_seed.startswith(f"{image.config_home}/") is False
    # The filename is the runtime's own word, and one image starts every
    # runtime the harness declares, so the entrypoint is told rather than
    # assuming Claude Code's.
    assert "LUP_CREDENTIAL_NAME=.credentials.json" in started
    # And so is what counts as a login still worth keeping, for the same
    # reason: the entrypoint cannot read a format it was not told.
    assert "LUP_CREDENTIAL_RENEWABLE=.a > 1" in started


def test_the_entrypoint_seeds_a_login_only_where_none_can_still_be_renewed() -> None:
    """Both directions have to be safe, and only this order makes them so.

    Copying unconditionally would overwrite a login made inside with the
    host's at every launch, which is the feature undone. Writing back to the
    host's file would let a contained agent rotate the credential every host
    session depends on. Seeding only where nothing usable sits is neither.

    The seed is tested the same way as the target, which is the half a first
    draft would leave out: copying a host login that has itself aged out
    replaces one credential nothing will answer with another, and reports a
    recovery that did not happen.
    """
    entrypoint = Image().dockerfile(Manifest())
    assert 'cp "$seed" "$stored"' in entrypoint
    assert 'usable "$seed" && ! usable "$stored"' in entrypoint
    # Size rather than presence, and a removal first. Every config home that
    # predates this holds an empty file here -- the mount point the old
    # read-only bind needed, owned by the uid that created it -- which a
    # presence test reads as a login and a copy cannot write through.
    assert '[ -s "$1" ] || return 1' in entrypoint
    assert 'rm -f "$stored"' in entrypoint


def test_a_runtime_that_declares_no_renewal_test_keeps_the_older_rule() -> None:
    """An unanswerable question must not read as the answer "expired".

    Codex states no deadline in its stored login, so the filter is empty for
    it -- and an empty filter reaching `jq` would evaluate to nothing and
    condemn every login it was asked about, re-seeding a working one at every
    launch. The guard is what keeps "cannot be asked" and "past renewing"
    apart.
    """
    entrypoint = Image().dockerfile(Manifest())
    assert '[ -n "$LUP_CREDENTIAL_RENEWABLE" ] || return 0' in entrypoint


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


def test_every_baked_variable_is_a_line_the_dockerfile_parser_accepts() -> None:
    """The check that was missing, and the shape of what it missed.

    `ENV name=value` takes whitespace as separating *more* pairs, so a value
    with a space in it makes the rest of that value into names with no
    values -- `ENV GIT_SSH_COMMAND=ssh -o BatchMode=yes` fails the whole file
    with `can't find = in "-o"`.

    Nothing caught it for as long as the tests asked what `environment()`
    returned. That is the declaration; the Dockerfile is the artifact, and a
    variable can be perfectly correct in the first and unparseable in the
    second. Generation does not build, so the image stayed broken through a
    green `harness generate all` and was found by a build.
    """
    baked = [
        line.removeprefix("ENV ")
        for line in Image().dockerfile(Manifest()).splitlines()
        if line.startswith("ENV ")
    ]
    assert baked
    for pair in baked:
        value = pair.split("=", 1)[1]
        quoted = value.startswith('"') and value.endswith('"')
        assert quoted or not any(character.isspace() for character in value), pair
