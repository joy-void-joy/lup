// Truncation: data is never cut to fit without a way to the rest.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const truncation = {
    'silent-truncation': {
        category: 'design',
        mistake: 'A sequence cut at a fixed bound to make it fit drops what lies past it, and nothing says so.',
        steer: 'Keep the whole value; where a format forces a limit, save the full copy, point at it, and say so in an `ignore`.',
        check(file) {
            for (const cut of file.cuts()) {
                // A bound a field sets is a setting, which a caller can change. A cut of
                // text is `string-slice`'s, and a cut serving a tool `fixed-tool-limit`'s.
                const text = cut.receiver !== undefined && file.isText(cut.receiver);
                if (cut.bound.source === 'field' || text || file.servedTool(cut.node) !== undefined) {
                    continue;
                }
                const what = cut.receiver ? `a \`${file.printType(cut.receiver)}\`` : 'an iterable';
                const bound =
                    cut.bound.source === 'literal' ? 'a literal bound' : `a constant bound, \`${cut.bound.text}\` (${cut.bound.value})`;
                file.report(cut.node, `\`${cut.text}\` cuts ${what} at ${bound}`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def shown(rows: list[str]) -> list[str]:
                            """Return the rows a report shows."""
                            return rows[:200]
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def shown(rows: list[str], saved: str) -> str:
                            """Return the report: every row, saved whole where the report points."""
                            Path(saved).write_text("\\n".join(rows))
                            return f"{len(rows)} rows, in {saved}"
                    `,
                },
                {
                    code: python`
                        from typing import ClassVar

                        from lup.types import Model


                        class Report(Model):
                            """A run's report."""

                            shown: ClassVar[int] = 200
                            rows: list[str]

                            def page(self) -> list[str]:
                                """Return the rows the report shows."""
                                return self.rows[: self.shown]
                    `,
                    rewritten: python`
                        from pathlib import Path

                        from lup.types import Model


                        class Report(Model):
                            """A run's report."""

                            rows: list[str]

                            def page(self, saved: str) -> str:
                                """Return the report: every row, saved whole where the report points."""
                                Path(saved).write_text("\\n".join(self.rows))
                                return f"{len(self.rows)} rows, in {saved}"
                    `,
                },
            ],
            passes: [
                python`
                    def body(rows: list[str]) -> list[str]:
                        """Return the rows after the header."""
                        return rows[1:]
                `,
                python`
                    def shown(rows: list[str], limit: int = 200) -> list[str]:
                        """Return the first \`limit\` rows: as many as the caller asks for."""
                        return rows[:limit]
                `,
            ],
        },
    },

    'fixed-tool-limit': {
        category: 'design',
        mistake:
            "A tool that stops its answer at a bound its caller can't set hands the agent part of what they asked for, " +
            'with no way to reach the rest.',
        steer:
            "Make the bound a field of the tool's input, defaulting to the value it has, and say in the answer when it " +
            'stopped short and how to reach the rest: a larger limit, or a narrower query. Where a format or an API ' +
            'forces the limit, keep it with an `ignore` that says so.',
        check(file) {
            const said = {
                literal: 'a literal',
                constant: 'a constant',
                field: 'a field of what the tool is bound to',
            };
            // A cut of text is `string-slice`'s.
            const cuts = file.cuts().filter((cut) => cut.receiver === undefined || !file.isText(cut.receiver));
            const capped = [
                ...cuts.map((cut) => ({ node: cut.node, bound: cut.bound, what: `\`${cut.text}\` stops at` })),
                ...file.limitsGiven().map((given) => ({ node: given.node, bound: given.bound, what: `\`${given.name}\` is given` })),
            ];
            for (const { node, bound, what } of capped) {
                const tool = file.servedTool(node);
                if (tool !== undefined) {
                    file.report(node, `${what} \`${bound.text}\`, ${said[bound.source]}, for the tool \`${tool}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pydantic import Field

                        import lup
                        from lup.types import Model


                        class Query(Model):
                            """A search of the notes."""

                            words: str = Field(description="The words a note holds.")


                        class Notes(Model):
                            """Notes an agent searches."""

                            notes: list[str]
                            shown: int = 50

                            @lup.tool
                            async def find_notes(self, query: Query) -> str:
                                """Find the notes holding some words."""
                                found = [note for note in self.notes if query.words in note]
                                return "\\n".join(found[: self.shown])
                    `,
                    rewritten: python`
                        from pydantic import Field, PositiveInt

                        import lup
                        from lup.types import Model


                        class Query(Model):
                            """A search of the notes."""

                            words: str = Field(description="The words a note holds.")
                            limit: PositiveInt = Field(default=50, description="How many notes to list at most.")


                        class Notes(Model):
                            """Notes an agent searches."""

                            notes: list[str]

                            @lup.tool
                            async def find_notes(self, query: Query) -> str:
                                """Find the notes holding some words."""
                                found = [note for note in self.notes if query.words in note]
                                shown = found[: query.limit]
                                more = len(found) - len(shown)
                                said = [f"{more} more match: a larger \`limit\` lists them."] if more else []
                                return "\\n".join([*shown, *said])
                    `,
                },
                {
                    code: python`
                        from pydantic import Field

                        import lup
                        from lup.programs import run
                        from lup.types import Model


                        class Query(Model):
                            """A search of the repository's issues."""

                            words: str = Field(description="What to search for, in GitHub's search syntax.")


                        @lup.tool
                        async def find_issues(query: Query) -> str:
                            """Search the repository's issues."""
                            return run("gh", "search", "issues", "--limit=100", "--", query.words).text()
                    `,
                    rewritten: python`
                        from pydantic import Field, PositiveInt

                        import lup
                        from lup.programs import run
                        from lup.types import Model


                        class Query(Model):
                            """A search of the repository's issues."""

                            words: str = Field(description="What to search for, in GitHub's search syntax.")
                            limit: PositiveInt = Field(default=100, description="How many issues to list at most.")


                        @lup.tool
                        async def find_issues(query: Query) -> str:
                            """Search the repository's issues."""
                            ran = run("gh", "search", "issues", f"--limit={query.limit}", "--", query.words)
                            found = ran.text().splitlines()
                            more = ["More may match: a larger \`limit\` lists them."] if len(found) == query.limit else []
                            return "\\n".join([*found, *more])
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class Notes(Model):
                        """Notes, read a page at a time."""

                        notes: list[str]
                        shown: int = 50

                        def page(self) -> list[str]:
                            """Return the first page of notes."""
                            return self.notes[: self.shown]
                `,
                python`
                    from pydantic import Field, PositiveInt

                    import lup
                    from lup.types import Model


                    class Query(Model):
                        """A search of the notes."""

                        words: str = Field(description="The words a note holds.")
                        limit: PositiveInt = Field(default=50, description="How many notes to list at most.")


                    def search(notes: list[str], words: str, limit: int) -> list[str]:
                        """Return the first \`limit\` notes holding \`words\`."""
                        return [note for note in notes if words in note][:limit]


                    class Notes(Model):
                        """Notes an agent searches."""

                        notes: list[str]

                        @lup.tool
                        async def find_notes(self, query: Query) -> str:
                            """Find the notes holding some words, \`limit\` at most."""
                            return "\\n".join(search(self.notes, query.words, query.limit))
                `,
            ],
        },
    },
} satisfies Catalog;
