## Directory Structure

Where each part of the application sits is in
[docs/template.md](docs/template.md), which walks the checkout when the page is
generated rather than describing it from memory, and carries the prose about
each part beside it.

The library beneath it is described in [docs/library.md](docs/library.md)
rather than drawn here, because in three of the four ways a project can obtain
`lup` its source is not on disk at all — a diagram of `packages/lup/` would be
describing a directory most projects never have.

---

<!-- section: Code Style & Patterns -->
# Code Style & Patterns

## Primary Libraries

- **lup**: The runtime this project composes against, and it is provider-neutral. `Client` opens a `Session`; a `TurnRequest` carries the prompt and the type the answer must arrive as; a strict `TurnResult[T]` hands back `.output` already validated. `Client.query(prompt, Model)` is the whole of a one-shot.
- **pydantic**: For data validation and settings
- **pydantic-settings**: For configuration (not dotenv)

Which runtimes this project drives is an extra rather than a rewrite —
`lup[claude]`, `lup[codex]`, or both — and the same declarations render into
each. A provider's own SDK is that adapter's dependency, never this
application's.

## Model Selection

Default to the **strongest** tier for the main agent, every subagent, reviewer, and background agent. This runs on a subscription where the best model is the point: reach for **balanced** only when latency or cost provably dominates and quality is non-critical, and for **fast** almost never. A role that genuinely warrants a cheaper model declares that tier explicitly with a reason; otherwise it inherits the strongest default.

State the tier, not a model id. A declaration says what the role needs and each runtime spells whichever model in its own lineup honors it, so a role pinned to one provider's model name is a role that only works on one runtime and stops being right the next time that lineup moves. The one place a concrete model belongs is the runtime configuration a deployment sets (`AGENT_MODEL`), where naming a specific model is the whole point.

## Type Safety Requirements

- **Never silently swallow exceptions** -- no `except ...: pass`, no `contextlib.suppress`; log with `logger.exception()`, handle meaningfully, or re-raise. Catch-all `except Exception` is fine at boundaries (task loops, subagent delegation) that do so; bare `except:` and `except BaseException` are never fine
- **Every function must specify input and output types**
- **Never use `Any`, `dict[str, Any]`, or `dict[str, object]`** -- these erase type information and defeat static analysis. Which typed stand-in replaces one depends on where the dict came from, and [docs/conventions.md](docs/conventions.md) carries the row for each
- **Provider SDKs are the adapter's, not yours**: application code composes against `lup`'s provider-neutral runtime — `Client`, `Session`, `TurnRequest`, `TurnResult` — and never imports a provider SDK. Each SDK is one adapter's dependency behind an extra, so importing it here pins the application to one runtime and trips `seam-boundary` outside a composition root that names it.
- **Use Python 3.12+ generics syntax**: `class A[T]`, not `Generic[T]`
- Never manually parse an agent's output -- ask for it as a type. `TurnRequest(output_type=Model)` binds that turn's own `submit_output` to the schema, and `TurnResult[Model].output` arrives validated
- **Never use `# type: ignore`** -- Ask the user how to properly fix type errors
- **`# lup: ignore` escape hatch** -- When `Any` or another anti-pattern is genuinely needed (untyped library boundaries, MCP), add an inline ignore to request user approval. Prefer the typed, pyright-style `# lup: ignore[rule-id]` so a site silences exactly the rule it needs and still trips the others; the bare `# lup: ignore` stays valid but the auditor flags it as untyped. A standalone ignore in the first 10 lines applies file-wide. Each rule id is shown in its deny message; the generated `docs/rules.md` (`uv run lup-devtools dev rules`) indexes every rule family with the `lup.harness.codescan` module that defines it.
- **Use Pydantic BaseModel instead of dataclasses**
- **Use `match`/`case` instead of `if`/`elif` chains** for dispatching on values or ranges

## Tool Input Schemas

Define tool inputs as BaseModel classes with `Field(description=...)`: one declaration is where both the `@lup_tool` schema and the validation come from. The decorator infers each schema from the handler's annotations, validates the input before the handler runs, and serializes the returned model — so validating arguments or assembling a response envelope by hand is work already done for you, and a recoverable failure is a raised `ToolError` carrying what to do about it. [docs/conventions.md](docs/conventions.md) puts each typed form beside the raw dict it replaces.

## No String Manipulation on Structured Data

Reaching for `re`, `.replace()`, `.split()`, or string slicing to extract, transform, or filter structured data means the structured API was missed. Operate on the structure directly: [docs/conventions.md](docs/conventions.md) names a parser per format — web pages, XML, JSON, turn results, dates, URLs, filesystem paths.

String operations are for formatting output. If you are using them to understand or transform data, you are working at the wrong abstraction level, and `import re` in particular is a code smell -- if you find yourself writing a regex, stop and look for the structured API.

## Use Standard Libraries

When integrating with external services (APIs, data sources, etc.):

- **Use existing Python libraries first** -- Check PyPI for official or well-maintained client libraries before writing raw HTTP requests
- **Don't rebuild the wheel** -- If a library exists with good documentation and maintenance, use it

## Code as Documentation

The codebase should read as a **monolithic source of truth** -- understandable without any knowledge of its history.

**The test:** Before adding a comment, ask: "Would this comment exist if the code had always been written this way?" If no -- don't add it.

**Do not:**

- Add comments to explain modifications you made
- Reference what code used to do (e.g., "Previously this returned None")
- Add inline comments when changing a line
- Use phrases like "now", "new", "updated", "fixed", or "changed" in comments

**Do:**

- Write comments that would make sense to someone who never saw previous versions
- Use commit messages for change history, not code comments
- Only add comments that document genuinely non-obvious behavior

## Inline `# lup:` Notes

A `# lup:` (or `// lup:`) comment is **actionable review feedback** for the agent to address — distinct from the `# lup: ignore` anti-pattern escape hatch. The edits hook prompts whenever an edit changes a file's `# lup:` marker count, and `lup-devtools` scans for unresolved notes.

**Never delete a `# lup:` note until its concern is actually resolved** — fix the code it points at, or answer the question and reflect that answer in code, docs, or an explicit user decision. Making a file parse or tidying up does not count. A note in a comment-less format (e.g. JSON) still can't be silently dropped: resolve it, or relocate it to a file that can hold it. Use `{{ resolve_skill }}` to clear resolved notes.

## Error Handling Philosophy

**MCP tools should:**

- Return `{"content": [...], "is_error": True}` for recoverable errors
- Log exceptions with `logger.exception()` for debugging
- Include actionable error messages (what failed, why, what to try)

**Agent code should:**

- Raise exceptions for unrecoverable errors (missing config, invalid state)
- Use the `with_retry` decorator for transient failures (HTTP timeouts, rate limits)
- Validate inputs early with Pydantic models

**Never silently swallow errors** -- either handle them meaningfully or let them propagate.

## DRY: Don't Repeat Yourself

- **Never duplicate code** -- If logic exists in the `lup` library, import it. Don't copy-paste.
- **Utilities belong in `packages/lup/`** -- Functions like `print_block`, `TraceLogger`, formatters go in the lup package, not the application package.
- **The application imports from `lup`** -- The agent layer uses lup abstractions, never redefines them.
- **Check before writing** -- Before creating a utility, search the `lup` package for existing implementations.

## lup (library) vs application Boundary

Code in `packages/lup/` must be **complete-as-is and configurable through function arguments** — never by modifying the source. Domain-specific code belongs in `src/<project>/`. If a lup module requires subclassing or source modification to customize, it violates this principle.

- **Use function parameters** for customization (callbacks, config objects, path overrides)
- **Use `configure()`-style functions** for module-level state that needs overriding
- **No imports from the application package** in lup code — the dependency arrow points one way
- **Placement test:** Can this module be used as-is in a different project without modification? If yes → `packages/lup/`. Does it import from the application package? If yes → `src/<project>/`.

## Imports: No Barrel Files

**Never use `__init__.py` re-exports or `__all__` in internal packages.** Import directly from the module that defines the symbol.

- `from lup.tools.mcp import lup_tool` -- not `from lup import lup_tool`
- `__init__.py` files should contain only the module docstring (no imports, no `__all__`)
- Barrel files drift out of sync and hide real dependencies

**Exception:** Standalone library packages under `packages/` may use re-exports with `__all__` in their top-level `__init__.py` to declare a public API. Only the package root -- not subpackages.

## Naming: No Private Prefixes

**Never use `_` prefixes** on functions, methods, classes, or constants. Nothing is private.

- Module-level functions: just name them `build_options`, not `_build_options`
- Class methods: `remove_stale_container`, not `_remove_stale_container`
- Constants: `PACE_THRESHOLDS`, not `_PACE_THRESHOLDS`
- Classes: `PendingReminder`, not `_PendingReminder`

**If a helper truly shouldn't pollute the module namespace**, nest it inside its only caller:

```python
def build_display(usage, stats):
    def place_label(text, position, width):
        ...
    # use place_label here
```

**Avoid useless mini-wrappers.** If a function's only purpose is to call another function with no additional logic, inline it.

**Exceptions:** `_` prefix is fine for unused parameters (`_context`, `_exc_type`) -- that's a linting convention, not a privacy convention.

## Tools

- **uv**: Package manager. Use `uv add <package>` (never edit pyproject.toml directly)
- **ruff**: Formatting and linting
- **pyright**: Type checking

