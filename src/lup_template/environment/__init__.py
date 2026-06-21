"""Environment harness for running the agent.

This package contains the domain-specific scaffolding:
- User interaction and I/O
- Game logic or application flow
- External system integration
- Session lifecycle management

The feedback loop focuses on improving lup_template.agent, not this code.
However, this code evolves as the application requirements change.

Structure:
- cli/__main__.py: Typer CLI — the ``lup`` entry point (run + loop with auto-commit)
"""

# claude: there should also be something about how we need to have this for website ui input, and expand more on when to tweak that (agents often tend to ignore environment and just put everything in)
