# lup: The generated header at @rules.md is not the same header as @permissions.md. Why? shouldn't the generated header be the same everywhere?
# lup: In general, I find the docs a bit hard to read and repetitive, can you refactor it out?

# Adopting and extending the Lup harness

The committed Claude and Codex trees are build products. Author skills,
agents, guidance, and policy inputs in typed Python; generate both native
trees; review the source and generated diff together. Native artifact edits
are preserved as conflicts because Lup cannot safely infer an arbitrary Python
source change from rendered Markdown, TOML, JSON, or shell.

## Add a skill

Create one module beneath
`src/lup_template/devtools/harness/content/skills/`. The declaration is
ordinary typed Python and the prompt remains readable prose:

```python
"""The project-triage skill."""

from lup.harness.models import Argument, ArgumentsRef, PromptDocument, Skill, TextPart

SKILL = Skill(
    id="skill.triage",
    name="triage",
    description="Classify one reported problem and identify the next investigation",
    arguments=[
        Argument(
            name="report",
            description="Problem report or error text to classify",
            required=True,
        )
    ],
    prompt=PromptDocument(
        parts=[
            TextPart(
                text="""Read the report, inspect the relevant boundary, and return the
most likely failure class with one concrete next check.

Report:
"""
            ),
            ArgumentsRef(),
        ]
    ),
)
```

Import the declaration explicitly in
`harness/content/catalog.py` and append it to `SKILLS`. Explicit imports make a
misspelled or missing module a type-checking error; the package does not use a
dynamic registry or barrel file.

Run the complete authoring loop:

```bash
uv run lup-devtools harness generate all
uv run lup-devtools harness check all
uv run ruff check src/lup_template/devtools/harness/content
uv run pyright
uv run pytest tests/unit/test_harness_compilation.py -q
```

The Claude renderer emits command Markdown and `$ARGUMENTS`; the Codex
renderer emits a skill and its native argument phrase. A declaration must not
branch on a provider name. Argument declarations and `ArgumentsRef` must occur
together; model validation rejects either one without the other. Use semantic
prompt parts such as `ArgumentsRef` or `SkillInvocation`, then let each
renderer choose its spelling.

## Change the fetch allowlist

The application-owned `HookSet` is constructed by `portable_harness()` in
`src/lup_template/devtools/harness/catalog.py`. Add the narrowest origin and
path prefix that supports the workflow:

```python
allowed_fetch=[
    HookUrlScope.model_validate(
        {
            "origin": "https://docs.example.com",
            "path_prefix": "/agent-api/",
        }
    ),
]
```

Origins are normalized into scheme, host, port, and path-prefix rows. Put an
explicit exclusion in `denied_fetch` when a permitted host has a sensitive
subtree; deny rows win over allow rows. Do not add provider-specific fetch
logic to the kernel or generated dispatcher.

Regenerate both packages and run the policy fixtures:

```bash
uv run lup-devtools harness generate all
uv run pytest tests/unit/test_semantic_policy.py -q
uv run lup-devtools harness check all
```

Inspect `hooks/runtime/policy_data.py` in both generated trees. The rows should
change while `hooks/runtime/kernel.py` remains identical: configuration is
generated data, policy control flow is one copied module.

## Change the shell classification

The shell auto-allow vocabulary is data too, and it is yours: lup ships the
rule models and the erasure, not the words. This project's table lives in
`devtools/harness/content/shell_vocabulary.py` and reaches the engine as
`HookSet.shell_rules` — a read-only command allows unless a listed `ask_flags`
writer flag appears, and a subcommand command (`git`, `gh`) allows only the
subcommands and operations it lists. To teach the fleet a downstream
toolchain, add rules to your own table — never edit the kernel:

```python
SHELL_RULES: list[ShellCommandRule] = [
    ...,
    ShellCommandRule(name="cargo", default_effect="ask", subcommands=[
        ShellSubcommandRule(name="check"),
        ShellSubcommandRule(name="build"),
        ShellSubcommandRule(name="test"),
    ]),
]
```

The whole table is erased into the `SHELL_RULES` rows the kernel interprets,
so a command lup never heard of and one it happens to ship in this template
are the same kind of entry. Regenerate and run the policy fixtures exactly as
for the fetch allowlist. Destructive forms should
stay `ask`: guard a writer flag with `ask_flags`, or a destructive
sub-operation with an `ask` `ShellOperationRule`, rather than widening a
`default_effect`.

## Understand a reconciliation conflict

`harness reconcile` compares the current files, the desired render, and the
ownership manifest. It does not mutate either native tree. A conflict means
one of these conditions is true:

| Category | Meaning | Action |
|---|---|---|
| `backpropagation_candidate` | A previously generated file differs from its owned digest. | Reproduce the intended change in the typed content or policy source, then regenerate. |
| `unknown_conflict` | Lup has no ownership proof for the existing bytes. | Decide whether the file belongs in typed generation or should remain local-only. |
| `local_only` | The recipe explicitly leaves the path to the user. | Keep it outside generation. |
| `sensitive_local_only` | The path may contain credentials or trust state. | Never import or commit it through the harness. |

The ordinary path is intentionally short:

```bash
uv run lup-devtools harness reconcile all
# edit the corresponding module under harness/content/ or harness/catalog.py
uv run lup-devtools harness generate all
uv run lup-devtools harness check all
```

### Apply a source-patch reconciliation proposal

A source-aware tool may produce a Git-format patch against canonical Python
without applying it. Keep the source tree at the patch's preimage, then persist
the proposal:

```bash
uv run lup-devtools harness propose-reconciliation tmp/source.patch
```

The command prints a proposal id and writes immutable `source.patch` and
`metadata.json` files under `.lup/reconcile/<id>/`. Review both files and the
named preimages. Apply only the reviewed proposal:

```bash
uv run lup-devtools harness apply-reconciliation <proposal-id>
```

The apply command verifies the patch digest, proposal identity, and current
preimage digest before showing the patch and asking for confirmation. It then
runs `git apply --check`, applies the canonical-source patch, regenerates both
native targets, and removes the consumed proposal. A changed source preimage,
malformed path, digest mismatch, or non-applying patch stops before mutation.

This is a patch transport, not a native-body importer. A renderer artifact is
never parsed heuristically back into Python.
