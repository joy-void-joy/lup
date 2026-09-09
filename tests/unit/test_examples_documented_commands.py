"""Every command the examples document is one a session is allowed to run.

The corpus opens with its own instructions, and an instruction the policy
refuses is worse than no instruction: `uv run -m examples.<name>` was
documented twelve times and denied every time, while the spelling that was
admitted — a bare script path — died on `from examples.common import Summary`
in eight of the nine examples. Neither half was wrong on its own. Nothing was
checking that they agreed, so a reader met the disagreement first.

Stated over what the corpus documents rather than over a list kept here, so an
example that grows a new invocation line is covered by having written it.
"""

import ast
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from lup.policy.models import ShellCommand
from lup.policy.rules import ShellPolicy
from lup_template.harness.catalog import declared_hook_set

REPOSITORY = Path(__file__).resolve().parents[2]
EXAMPLES = REPOSITORY / "examples"


def documented_commands() -> list[tuple[str, str]]:
    """Every `uv run` line the corpus tells a reader to run, and where from.

    The README's fenced blocks and each module's own docstring, which are the
    two places an example says how to run itself. Prose naming a command
    inline is not an instruction and is left out, which is what asking the
    markdown parser for fences buys over scanning the file.
    """
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    fences = "\n".join(
        token.content for token in MarkdownIt().parse(readme) if token.type == "fence"
    )
    docstrings = [
        (
            path.name,
            ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or "",
        )
        for path in sorted(EXAMPLES.glob("*.py"))
    ]
    found = [
        (source, line.strip())
        for source, text in [("README.md", fences), *docstrings]
        for line in text.splitlines()
        if line.strip().startswith("uv run")
    ]
    assert found, "the examples document no commands to check"
    return found


@pytest.mark.parametrize(("source", "command"), documented_commands())
def test_a_documented_command_is_one_a_session_may_run(
    source: str, command: str
) -> None:
    hooks = declared_hook_set()
    policy = ShellPolicy(
        hooks.resolved_shell_rules(), runner_targets=hooks.runner_targets
    )

    decision = policy.decide(ShellCommand(command=command, cwd=REPOSITORY))

    assert decision.effect == "allow", (
        f"{source} documents `{command}`, which this project's own policy "
        f"answers {decision.effect}: {decision.reason}"
    )
