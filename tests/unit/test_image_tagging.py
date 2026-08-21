"""Naming an image after the declaration it was built from, and sweeping up.

Content-addressing is what lets two checkouts share one image without anybody
asserting their toolchains match, and the cost that comes with it is that a
declaration edit leaves the old image standing. These pin both halves: what
two checkouts get, and what the sweep is willing to delete.
"""

from pathlib import Path

from lup.devtools.harness.contained import (
    checkout_tag,
    finished_tags,
    image_tag,
)

BASE = "FROM archlinux:base\nRUN pacman -Syu --noconfirm\n"


def test_one_declaration_is_one_image_whatever_renders_it() -> None:
    """The property the whole choice was made for.

    Two worktrees declaring the same toolchain build it once and share it,
    and nothing had to assume they would -- the name is a function of what
    would be built.
    """
    assert image_tag(BASE) == image_tag(BASE)


def test_a_changed_declaration_is_a_different_image() -> None:
    """And the other half: they diverge exactly when the declaration does.

    Which is what stops two checkouts rebuilding over each other on every
    switch -- the failure a repository-wide name has, because
    `image_matches` compares the declaration digest and each finds the
    other's.
    """
    assert image_tag(BASE) != image_tag(BASE + "RUN pacman -S --noconfirm jq\n")


def test_a_checkout_name_says_nothing_about_the_declaration(tmp_path: Path) -> None:
    """The readable tag is stateable inside the manifest; the digest is not.

    The preflight has to name the image it probes, and the digest is computed
    from the manifest that preflight is part of. A name that does not depend
    on the declaration is the only one that can be written down there.
    """
    assert checkout_tag(tmp_path / "feat-thing") == "lup-agent:feat-thing"


def test_a_digest_tag_a_checkout_points_at_is_kept() -> None:
    """The whole test the sweep applies: is anybody still naming this image."""
    listing = (
        "abc123 localhost/lup-agent:77d332d7914c\nabc123 localhost/lup-agent:dev\n"
    )

    assert finished_tags(listing, keep="lup-agent:000000000000") == []


def test_a_digest_tag_nothing_points_at_is_finished() -> None:
    """A declaration edit leaves this behind, and nothing else will name it."""
    listing = "abc123 localhost/lup-agent:77d332d7914c\n"

    assert finished_tags(listing, keep="lup-agent:000000000000") == [
        "lup-agent:77d332d7914c"
    ]


def test_the_image_this_declaration_would_build_is_never_swept() -> None:
    """A sweep between a declaration edit and the next launch must not take it.

    Nothing is tagged onto it yet -- the launch that will reuse it has not
    happened -- so the only thing holding it is that it is what this
    declaration renders to.
    """
    listing = "abc123 localhost/lup-agent:77d332d7914c\n"

    assert finished_tags(listing, keep="lup-agent:77d332d7914c") == []


def test_another_project_s_images_are_left_alone() -> None:
    """The sweep names one prefix, and everything else on the host is somebody's."""
    listing = "abc123 docker.io/library/archlinux:base\nabc123 localhost/other:latest\n"

    assert finished_tags(listing, keep="lup-agent:000000000000") == []


def test_a_line_the_engine_shaped_differently_is_skipped() -> None:
    """An engine free to add a column must not turn a sweep into a crash."""
    listing = "abc123\nabc123 localhost/lup-agent:77d332d7914c extra\n\n"

    assert finished_tags(listing, keep="lup-agent:000000000000") == []
