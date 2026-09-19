The command prints the `uv sync` and the regeneration it wants next. Run both
before anything reads the project's types.

#### 2. Merge the guidance template into the guidance declaration

The merge lands in `src/<project>/harness/content/guidance.py`, never in a tree's guidance file ({{ guidance_file_path }}): those are generation's outputs, and an edit made directly to one is undone the next time the harness runs. Take the sections from that tree's template flavor ({{ guidance_template_path }}), covering every tree the project commits:

1. Read the template and replace `<project>` placeholders with the actual project name
2. Read the existing declaration
3. Use the `<!-- section: ... -->` markers in the template to identify independent merge units
4. Compare sections: for each marked section, check whether the declaration already composes it (by heading match)
5. Add missing sections to the declaration
6. Leave existing sections untouched -- don't overwrite content the project already has
7. Regenerate with `uv run lup-devtools harness generate all`, which is what carries the merged sections into every tree

The template is a menu, not a document to adopt whole. Guidance is loaded on
every turn and is held to a byte budget for a reason a reader never sees
otherwise: a runtime that caps how much project documentation it will load
stops adding at the cap, so an over-budget guidance file is not an error, it is
silent truncation. Generation enforces that ceiling and refuses the merged
declaration, naming the overage — so take the sections this domain will act on,
and leave the rest to the pages under `docs/` that already carry them.

Clearing the scaffold flag is also what hands this domain its room. While the
flag stood, the template was held to a *smaller* ceiling than the runtime's,
holding roughly 11.5 KiB back on purpose — so what you inherit is a deliberately
lean document with space to say what is true of this domain, not a full budget
already spent on somebody else's conventions. `dev guidance` reports what each
section costs, and after adoption only the runtime ceiling applies.

Which runtimes the project carries is not a choice made here: every tree
arrives with the clone, and generation writes each one it finds. Dropping a
runtime is a later removal somebody decides on its own terms.

#### 3. Initialize upstream sync

