"""Which modules the preservation walk counts as a surface somebody could hold.

The gate refuses a name that stopped resolving, on the reasoning that an adopter
meets one as an import that stopped working. That reasoning needs somebody to
have been able to write the import, and two shapes of module here are reachable
by name without anybody being able to: the scaffold, which is copied and renamed
on the way out of the template, and the permission kernel, which is compiled into
each plugin's dispatcher and reached there as bare ``kernel.*``.

Nothing in a module's text says which it is -- this repository refuses the
leading underscore -- so it is declared, and these pin that the declaration is
read as a subtree rather than as text.
"""

from lup.devtools.dev.preservation import offers_a_surface

INTERNAL = ["lup_template", "lup.policy.kernel"]


def test_an_undeclared_module_offers_a_surface() -> None:
    """The default answer, and the one a repository declaring nothing gets."""
    assert offers_a_surface(["lup", "tools", "mcp"], INTERNAL)
    assert offers_a_surface(["lup", "tools", "mcp"], [])


def test_a_declared_prefix_covers_the_subtree_beneath_it() -> None:
    """One entry answers for every module under it, at any depth."""
    assert not offers_a_surface(["lup", "policy", "kernel"], INTERNAL)
    assert not offers_a_surface(["lup", "policy", "kernel", "lex"], INTERNAL)
    assert not offers_a_surface(["lup", "policy", "kernel", "a", "b"], INTERNAL)


def test_a_declared_root_covers_the_package_it_names() -> None:
    """The scaffold half, which an adopter receives as its own source."""
    assert not offers_a_surface(["lup_template", "agent", "toolsets"], INTERNAL)


def test_a_sibling_sharing_a_prefix_is_not_covered() -> None:
    """Compared as segments, so the match cannot run past a name boundary.

    ``lup.policy.kernels`` starts with the declared text and is a different
    module; a test on the string would have swallowed it.
    """
    assert offers_a_surface(["lup", "policy", "kernels"], INTERNAL)
    assert offers_a_surface(["lup", "policy"], INTERNAL)
    assert offers_a_surface(["lup_templates", "agent"], INTERNAL)


def test_a_prefix_longer_than_the_module_matches_nothing() -> None:
    """A parent of a declared subtree still publishes its own names."""
    assert offers_a_surface(["lup"], INTERNAL)
