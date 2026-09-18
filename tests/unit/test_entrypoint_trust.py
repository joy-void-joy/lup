"""The entrypoint trusts the checkout and the repository it belongs to, every start.

Measured on a contained session probe: the runtime asked for the linked
worktree's main repository to be trusted -- `/home/.../lup.git`, not the
worktree under `tree/` -- and, finding only the worktree in the document,
dropped the declared `permissions.allow` entries with a notice and refused the
turn. The document outlives the image in its volume, so a seed written once
on first start could never have carried the second path; it is merged on
every start instead.
"""

from lup.harness.image import Image
from lup.harness.requirements import Manifest


def entrypoint() -> str:
    rendered = Image().dockerfile(Manifest())
    start = rendered.index("COPY <<'ENTRY' /usr/local/bin/lup-entrypoint")
    return rendered[start : rendered.index("\nENTRY\n", start)]


def test_the_repository_root_is_trusted_beside_the_checkout() -> None:
    script = entrypoint()

    assert "rev-parse --path-format=absolute --git-common-dir" in script
    assert ".projects[$here] = ((.projects[$here] // {})" in script
    assert ".projects[$repository] = ((.projects[$repository] // {})" in script
    assert 'case "$repository" in */.git) repository=${repository%/.git} ;; esac' in (
        script
    )


def test_trust_is_merged_on_every_start_and_the_seed_only_on_the_first() -> None:
    """A document already in the volume is amended, never replaced or skipped."""
    script = entrypoint()
    seeded = script.index('cp /opt/lup/trust-seed.json "$config/.claude.json"')
    merged = script.index("jq --arg here")

    assert script.index('if [ ! -f "$config/.claude.json" ]') < seeded < merged
    assert script.count("fi\n", 0, merged) >= 2
    assert 'mv "$config/.claude.json.lup" "$config/.claude.json"' in script
