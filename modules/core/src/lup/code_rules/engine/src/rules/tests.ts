// Tests: a promise checks what someone relies on, so it breaks only when that changes,
// never when something nobody promised does.

import { answered, heard, isProse, isReason, sides, writesCollection, writesList, writtenByTheTest } from '../asserted';
import type { Catalog } from '../catalog';
import { python } from '../examples';

export const tests = {
    'asserted-words': {
        category: 'design',
        reads: 'tests',
        mistake: "Asserting a message's words breaks the promise when the message is reworded, though nobody relied on them.",
        steer:
            "Check the structured result behind the words: the names a refusal's or an error's `about` holds " +
            '(`rejection.about`, `LupError.about`), or a field of the model answered.',
        check(file) {
            // An exception's text is `error-text`'s, which reads tests too.
            const errors = new Set(file.exceptionTexts().map((each) => each.node));
            for (const compared of file.asserted()) {
                const found = sides(compared).find(([words, text]) => {
                    const written = file.isStringLiteral(words) ? file.literalText(words) : undefined;
                    if (written === undefined || errors.has(text)) {
                        return false;
                    }
                    const prose = isProse(written) && file.isText(text) && !writtenByTheTest(file, written);
                    return prose || isReason(file, text);
                });
                if (found) {
                    const [words, text] = found;
                    file.report(compared.node, `\`${file.text(text)}\` is checked for the words ${file.text(words)}`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import lup
                        from lup import Agent, Part, Project
                        from lup.testing import Refused, Testing


                        class MergingPromises(Part):
                            """What merging is counted on for."""

                            @lup.promise
                            async def main_is_never_merged_into(self, by: Testing) -> None:
                                """A merge into \`main\` is refused."""
                                started = await by.started(Project())
                                merged = await started.call("merge", {"into": "main"}, by.any(Agent))
                                assert isinstance(merged, Refused)
                                assert "never merges into \`main\`" in merged.rejection.reason
                    `,
                    rewritten: python`
                        import lup
                        from lup import Agent, Part, Project
                        from lup.testing import Refused, Testing


                        class MergingPromises(Part):
                            """What merging is counted on for."""

                            @lup.promise
                            async def main_is_never_merged_into(self, by: Testing) -> None:
                                """A merge into \`main\` is refused."""
                                started = await by.started(Project())
                                merged = await started.call("merge", {"into": "main"}, by.any(Agent))
                                assert isinstance(merged, Refused)
                                assert "main" in merged.rejection.about
                    `,
                },
            ],
            passes: [
                python`
                    import lup
                    from lup import Agent, Operator, Part, Project
                    from lup.testing import Accepted, Testing


                    class InboxPromises(Part):
                        """What the inbox is counted on for."""

                        @lup.promise
                        async def a_question_is_shown_as_asked(self, by: Testing) -> None:
                            """A question an agent asks is shown to the operator as it was asked, saying who asked."""
                            started = await by.started(Project())
                            await started.call("ask", {"question": "which way?"}, by.any(Agent))
                            shown = await started.view("inbox", "waiting", {}, Operator())
                            assert isinstance(shown, Accepted)
                            assert "which way?" in shown.answer()
                            assert "agent" in shown.answer()
                `,
            ],
        },
    },

    'whole-answer': {
        category: 'design',
        reads: 'tests',
        mistake:
            'Comparing a whole answer, or a whole list in one, breaks the promise when a field or an entry is added ' +
            'that nobody relied on.',
        steer: 'Compare the one field promised, or check membership: `x in …`, `all(…)`.',
        check(file) {
            for (const compared of file.asserted()) {
                if (compared.kind !== 'equals') {
                    continue;
                }
                const found = sides(compared).find(
                    ([whole, written]) =>
                        writesCollection(written) && answered(file, whole) && heard(file, whole) === undefined
                );
                if (found) {
                    file.report(compared.node, `\`${file.text(found[0])}\`, an answer, is compared whole`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import json

                        import lup
                        from lup import Machine, Part, Project
                        from lup.testing import Accepted, Testing


                        class ApprovalPromises(Part):
                            """What approving a commit is counted on for."""

                            @lup.promise
                            async def nothing_is_approved_at_first(self, by: Testing) -> None:
                                """Before any approval, a project has no commit approved."""
                                started = await by.started(Project())
                                approval = await started.serve("approval", {"project": "harmon"}, Machine())
                                assert isinstance(approval, Accepted)
                                assert json.loads(approval.answer()) == {"commit": None}
                    `,
                    rewritten: python`
                        import json

                        import lup
                        from lup import Machine, Part, Project
                        from lup.testing import Accepted, Testing


                        class ApprovalPromises(Part):
                            """What approving a commit is counted on for."""

                            @lup.promise
                            async def nothing_is_approved_at_first(self, by: Testing) -> None:
                                """Before any approval, a project has no commit approved."""
                                started = await by.started(Project())
                                approval = await started.serve("approval", {"project": "harmon"}, Machine())
                                assert isinstance(approval, Accepted)
                                assert json.loads(approval.answer())["commit"] is None
                    `,
                },
            ],
            passes: [
                python`
                    import json

                    import lup
                    from lup import Machine, Part, Project
                    from lup.testing import Accepted, Testing


                    class OpeningPromises(Part):
                        """What opening a project is counted on for."""

                        @lup.promise
                        async def nothing_opens_what_was_never_run(self, by: Testing) -> None:
                            """As the machine starts with nothing run before, it opens nothing, and says what it holds of each project asked."""
                            started = await by.started(Project())
                            asked = ["harmon", "story"]
                            resumed = await started.serve("resumed", {"projects": asked}, Machine())
                            assert isinstance(resumed, Accepted)
                            answer = json.loads(resumed.answer())
                            assert answer["opened"] == []
                            assert [each["project"] for each in answer["held"]] == asked
                `,
            ],
        },
    },

    'whole-arguments': {
        category: 'design',
        reads: 'tests',
        mistake:
            'Comparing the whole argument list a stand-in heard breaks the promise when the program is asked the ' +
            'same thing spelled another way.',
        steer: "Check that what matters is among a run's arguments: `\"init\" in each`, with `any(…)` or `all(…)` over the runs.",
        check(file) {
            for (const compared of file.asserted()) {
                const found = sides(compared).find(([written, ran]) => {
                    const kind = heard(file, ran);
                    const whole = compared.kind === 'contains' ? kind === 'runs' : kind !== undefined;
                    return whole && writesList(file, written);
                });
                if (found) {
                    file.report(compared.node, `\`${file.text(found[1])}\` is compared with a whole argument list`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import lup
                        from lup import Operator, Part, Project
                        from lup.testing import Testing


                        class SetupPromises(Part):
                            """What setting up a project is counted on for."""

                            @lup.promise
                            async def a_project_is_made_a_repository(self, by: Testing) -> None:
                                """Setting up a project makes it a git repository."""
                                started = await by.started(Project())
                                await started.run("setup", "init", {}, Operator())
                                assert ["init", "--quiet"] in started.ran("git")
                    `,
                    rewritten: python`
                        import lup
                        from lup import Operator, Part, Project
                        from lup.testing import Testing


                        class SetupPromises(Part):
                            """What setting up a project is counted on for."""

                            @lup.promise
                            async def a_project_is_made_a_repository(self, by: Testing) -> None:
                                """Setting up a project makes it a git repository."""
                                started = await by.started(Project())
                                await started.run("setup", "init", {}, Operator())
                                assert any("init" in each for each in started.ran("git"))
                    `,
                },
            ],
            passes: [
                python`
                    import lup
                    from lup import Machine, Operator, Part, Project
                    from lup.testing import Refused, Testing


                    class BuildingPromises(Part):
                        """What building an image is counted on for."""

                        @lup.promise
                        async def an_image_is_built_from_what_is_there(self, by: Testing) -> None:
                            """An image is built from what the machine holds, pulling nothing; an agent asking builds nothing."""
                            started = await by.started(Project())
                            await started.serve("built", {"image": "harmon"}, Machine())
                            assert all("--pull=never" in each for each in started.ran("podman"))
                            refused = await started.run("hosting", "build", {}, Operator())
                            assert isinstance(refused, Refused)
                            assert started.ran("uv") == []
                `,
            ],
        },
    },
} satisfies Catalog;
