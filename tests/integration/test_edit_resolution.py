"""The edit gate's route to a checker, end to end.

The unit tests pin each half against a fake: the kernel asks when nothing
resolved a receiver and admits the line when something did, and the grammar
refutes a declaration outside the family. What neither can show is that the
host half actually reaches a checker and comes back with an answer the kernel
can read — a chain of a subprocess, a CLI, a language server and a JSON
contract, every link of which is silent when it breaks. A gate that always
answered "nothing resolved" would pass every unit test in the suite and ask
about every `.get(` an agent ever writes.
"""

from pathlib import Path

import pytest

from lup.devtools.dev.pyright_oracle import langserver_path
from lup.policy.assets.host import resolved_refutations
from lup.workspace.paths import project_root

pytestmark = pytest.mark.skipif(
    langserver_path() is None, reason="pyright-langserver is not installed"
)

RESOLUTION_COMMAND = [".venv/bin/lup-devtools", "dev", "refutations"]

PROPOSED = 'import httpx\n\nresponse = httpx.get("https://example.com")\n'
"""A module-qualified receiver, which resolves outside the mapping family."""


def unwritten(root: Path) -> str:
    """A path inside the checkout that nothing has ever written.

    The point of the buffer: the content is judged before it exists, so the
    file it belongs to need not. What the path decides is import resolution
    and the module's own name, and those follow from where it *would* be.
    """
    return str(root / "packages" / "lup" / "src" / "lup" / "codescan" / "unwritten.py")


def test_the_host_resolves_a_receiver_the_gate_could_not() -> None:
    root = project_root()

    refuted = resolved_refutations(unwritten(root), PROPOSED, RESOLUTION_COMMAND)

    assert refuted == {"dict-get": [3]}
    assert not Path(unwritten(root)).exists(), "resolving wrote the file"


def test_a_mapping_receiver_comes_back_unrefuted() -> None:
    """Empty is an answer: a checker looked and the rule stands.

    This and a checker that never ran have to arrive differently, because one
    is evidence the gate should deny on and the other is why it must ask.
    """
    root = project_root()
    proposed = 'payload: dict[str, str] = {}\nvalue = payload.get("name")\n'

    refuted = resolved_refutations(unwritten(root), proposed, RESOLUTION_COMMAND)

    assert refuted == {}


def test_no_declared_resolver_is_not_an_empty_refutation() -> None:
    """Nothing looked, so the gate has to ask rather than refuse."""
    root = project_root()

    assert resolved_refutations(unwritten(root), PROPOSED, []) is None


def test_a_resolver_that_is_not_installed_reports_nothing_resolved() -> None:
    """A declared path that is not there is the same silence as none declared."""
    root = project_root()

    assert (
        resolved_refutations(unwritten(root), PROPOSED, ["nowhere/lup-devtools"])
        is None
    )
